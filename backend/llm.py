"""LLM access: OpenAI first, Anthropic Claude as fallback, only when classical methods fail.

call_llm(prompt, schema, agent_name) -> (parsed_model, method)
  * tries OpenAI, then Claude; a provider is skipped if its key or model env var is empty
  * per-call timeout, 2 retries with exponential backoff on 429 / 5xx / timeouts
  * the reply must be JSON matching `schema` (Pydantic); one repair retry if it is not
  * raises LLMUnavailable when no provider succeeds, so the caller uses its classical fallback
Every call (success or failure) is appended to LLM_LOG for the transparency panel.
"""
import base64
import json
import os
import re
import threading
import time
from pathlib import Path

from pydantic import BaseModel, ValidationError

from state import now_iso


def load_env_file(path: Path = Path(__file__).parent / ".env") -> None:
    """Minimal .env reader for local runs (Cloud Run injects real env vars). Never overrides."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


load_env_file()

TIMEOUT_S = float(os.environ.get("LLM_TIMEOUT_S", "45"))
RETRIES = 2
SYSTEM = ("You are a careful financial-document assistant. Reply with a single JSON object only. "
          "Never guess: if a value is not visible in the input, say it was not found.")

LLM_LOG: list[dict] = []
_log_lock = threading.Lock()


class LLMUnavailable(Exception):
    pass


class _Retryable(Exception):
    pass


def configured_providers() -> list[str]:
    out = []
    if os.environ.get("OPENAI_API_KEY") and os.environ.get("OPENAI_MODEL"):
        out.append("openai")
    if os.environ.get("ANTHROPIC_API_KEY") and os.environ.get("ANTHROPIC_MODEL"):
        out.append("claude")
    return out


def call_llm(prompt: str, schema: type[BaseModel], agent_name: str, *,
             image_png: bytes | None = None, doc_id: str | None = None) -> tuple[BaseModel, str]:
    full_prompt = (f"{prompt}\n\nReply with JSON matching this JSON Schema:\n"
                   f"{json.dumps(schema.model_json_schema())}")
    errors = []
    for provider in configured_providers():
        try:
            parsed = _call_with_repair(provider, full_prompt, schema, agent_name, image_png, doc_id)
            return parsed, f"llm_{provider}"
        except Exception as e:  # any failure -> try the next provider
            errors.append(f"{provider}: {type(e).__name__}: {e}"[:300])
    raise LLMUnavailable("; ".join(errors) or "no LLM provider configured (keys/models missing)")


def _call_with_repair(provider, prompt, schema, agent_name, image_png, doc_id):
    text = _call_with_retries(provider, prompt, agent_name, image_png, doc_id)
    try:
        return schema.model_validate_json(_strip_fences(text))
    except ValidationError as e:
        repair = (f"{prompt}\n\nYour previous reply was:\n{text[:2000]}\n"
                  f"It did not match the schema ({str(e)[:500]}). Reply again with only valid JSON.")
        text = _call_with_retries(provider, repair, agent_name, image_png, doc_id)
        return schema.model_validate_json(_strip_fences(text))


def _call_with_retries(provider, prompt, agent_name, image_png, doc_id) -> str:
    for attempt in range(RETRIES + 1):
        t0 = time.perf_counter()
        entry = {"at": now_iso(), "agent": agent_name, "provider": provider, "doc_id": doc_id,
                 "model": os.environ.get("OPENAI_MODEL" if provider == "openai" else "ANTHROPIC_MODEL"),
                 "prompt": prompt[:4000], "has_image": image_png is not None, "attempt": attempt + 1}
        try:
            text, tokens = (_openai if provider == "openai" else _claude)(prompt, image_png)
            _log({**entry, "ok": True, "response": text[:4000], "tokens": tokens,
                  "latency_ms": round((time.perf_counter() - t0) * 1000)})
            return text
        except _Retryable as e:
            _log({**entry, "ok": False, "error": str(e)[:500], "latency_ms": round((time.perf_counter() - t0) * 1000)})
            if attempt == RETRIES:
                raise
            time.sleep(2 ** attempt)
        except Exception as e:
            _log({**entry, "ok": False, "error": f"{type(e).__name__}: {e}"[:500],
                  "latency_ms": round((time.perf_counter() - t0) * 1000)})
            raise


def _openai(prompt: str, image_png: bytes | None) -> tuple[str, dict]:
    import openai
    client = openai.OpenAI(timeout=TIMEOUT_S, max_retries=0)
    content = [{"type": "text", "text": prompt}]
    if image_png:
        content.append({"type": "image_url", "image_url": {
            "url": "data:image/png;base64," + base64.b64encode(image_png).decode()}})
    try:
        resp = client.chat.completions.create(
            model=os.environ["OPENAI_MODEL"], response_format={"type": "json_object"},
            messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}])
    except (openai.RateLimitError, openai.InternalServerError, openai.APITimeoutError, openai.APIConnectionError) as e:
        raise _Retryable(f"{type(e).__name__}: {e}")
    usage = resp.usage.model_dump() if resp.usage else {}
    return resp.choices[0].message.content or "", usage


def _claude(prompt: str, image_png: bytes | None) -> tuple[str, dict]:
    import anthropic
    client = anthropic.Anthropic(timeout=TIMEOUT_S, max_retries=0)
    content = []
    if image_png:
        content.append({"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                     "data": base64.b64encode(image_png).decode()}})
    content.append({"type": "text", "text": prompt})
    try:
        resp = client.messages.create(model=os.environ["ANTHROPIC_MODEL"], max_tokens=2048, system=SYSTEM,
                                      messages=[{"role": "user", "content": content}])
    except (anthropic.RateLimitError, anthropic.InternalServerError, anthropic.APITimeoutError,
            anthropic.APIConnectionError) as e:
        raise _Retryable(f"{type(e).__name__}: {e}")
    text = "".join(block.text for block in resp.content if getattr(block, "type", "") == "text")
    return text, {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens}


def _strip_fences(text: str) -> str:
    """Models sometimes wrap JSON in ```json fences; take the outermost {...}."""
    m = re.search(r"\{.*\}", text, re.S)
    return m.group(0) if m else text


def _log(entry: dict) -> None:
    with _log_lock:
        LLM_LOG.append(entry)

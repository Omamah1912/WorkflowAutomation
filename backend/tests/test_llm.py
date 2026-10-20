import os

import pytest

import llm
import prompts


def test_no_keys_raises_llm_unavailable(monkeypatch):
    for key in ("OPENAI_API_KEY", "OPENAI_MODEL", "ANTHROPIC_API_KEY", "ANTHROPIC_MODEL"):
        monkeypatch.delenv(key, raising=False)
    with pytest.raises(llm.LLMUnavailable):
        llm.call_llm("hello", prompts.ConsequenceOut, "test")


def test_strip_fences():
    assert llm._strip_fences('```json\n{"a": 1}\n```') == '{"a": 1}'


@pytest.mark.skipif(not llm.configured_providers(), reason="no LLM keys configured")
def test_live_llm_returns_schema():
    out, method = llm.call_llm(prompts.CONSEQUENCE.format(doc="test", failures="DIV-01: unit mismatch"),
                               prompts.ConsequenceOut, "test")
    assert method in ("llm_openai", "llm_claude")
    assert out.sentence
    assert llm.LLM_LOG and llm.LLM_LOG[-1]["ok"]

// Small display helpers (no data lives here).
export const num = (n, digits = 0) =>
  n === null || n === undefined || Number.isNaN(n) ? "—" : Number(n).toLocaleString("en-US", { maximumFractionDigits: digits });

export const pct = (x, digits = 0) => (x === null || x === undefined ? "—" : `${(x * 100).toFixed(digits)}%`);

export function compact(n) {
  if (n === null || n === undefined) return "—";
  const abs = Math.abs(n);
  if (abs >= 1e9) return `${(n / 1e9).toFixed(1)} billion`;
  if (abs >= 1e6) return `${(n / 1e6).toFixed(1)} million`;
  return num(n);
}

export function ago(iso) {
  if (!iso) return "—";
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${Math.round(s / 60)}m`;
  if (s < 86400) return `${Math.round(s / 3600)}h`;
  return `${Math.round(s / 86400)}d`;
}

export function clock(ms) {
  if (ms === null || ms === undefined || ms < 0) return "—";
  const t = Math.floor(ms / 1000);
  const pad = (v) => String(v).padStart(2, "0");
  return `${pad(Math.floor(t / 3600))}:${pad(Math.floor((t % 3600) / 60))}:${pad(t % 60)}`;
}

/** Offset of an event from the batch start, as 00:01:02.345 */
export function offset(iso, startIso) {
  if (!iso || !startIso) return "";
  const ms = new Date(iso).getTime() - new Date(startIso).getTime();
  return `${clock(ms)}.${String(Math.max(0, ms) % 1000).padStart(3, "0")}`;
}

export const methodKind = (m) =>
  !m || m === "none" ? "none" : m.startsWith("llm_") ? "llm" : m === "human" ? "human" : "classical";

export function methodLabel(m) {
  if (!m || m === "none") return "No method";
  if (m === "llm_openai") return "LLM · OpenAI";
  if (m === "llm_claude") return "LLM · Claude";
  if (m === "human") return "Human";
  if (m === "ocr_tesseract") return "OCR";
  if (m === "derived_from_filing") return "Derived";
  if (m === "fixture") return "Fixture";
  return "Classical";
}

export const short = (s, n = 26) => (!s ? "" : s.length > n ? s.slice(0, n - 1) + "…" : s);

export const valueText = (v) =>
  v === null || v === undefined ? "—" : typeof v === "number" ? num(v, 4) : typeof v === "boolean" ? (v ? "yes" : "no") : String(v);

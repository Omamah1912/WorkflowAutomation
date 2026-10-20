// Top bar from the mockups: logo, page pills, live API status, Run batch menu.
import { useEffect, useRef, useState } from "react";
import { get, post, uploadPdfs } from "../api.js";
import { Arrow, Logo } from "./ui.jsx";

const PAGES = [["overview", "Overview", "#/"], ["pipeline", "Pipeline", "#/pipeline"], ["review", "Review", "#/review"],
               ["metrics", "Metrics", "#/metrics"], ["llm-log", "LLM log", "#/llm-log"]];

export const BATCHES = [
  ["csv", "CSV batch", "450 metadata rows (ps01 + ps07)"],
  ["manifest", "Real PSX filings", "12 PDFs from the manifest"],
  ["fixture", "Samsung replay", "Reconstruction from public reporting"],
];

export function useHealth() {
  const [health, setHealth] = useState(null);
  useEffect(() => {
    let alive = true;
    const check = () => get("/health").then((h) => alive && setHealth(h)).catch(() => alive && setHealth(false));
    check();
    const t = setInterval(check, 8000);
    return () => { alive = false; clearInterval(t); };
  }, []);
  return health;
}

export default function Header({ active, onError }) {
  const health = useHealth();
  const [open, setOpen] = useState(false);
  const fileRef = useRef(null);

  const start = async (source) => {
    setOpen(false);
    try {
      const { batch_id } = await post("/batch", { source });
      window.location.hash = `#/pipeline/${batch_id}`;
    } catch (e) { onError(`Could not start batch: ${e.message}`); }
  };
  const upload = async (files) => {
    setOpen(false);
    if (!files?.length) return;
    try {
      const { batch_id } = await uploadPdfs(files);
      window.location.hash = `#/pipeline/${batch_id}`;
    } catch (e) { onError(`Upload failed: ${e.message}`); }
  };

  const online = health && health.ok;
  return (
    <header className="header">
      <a className="logo" href="#/"><Logo />GhostStop</a>
      <nav aria-label="Primary" className="pillgroup">
        {PAGES.map(([key, label, href]) => (
          <a key={key} className={`pill ${active === key ? "pill-on" : ""}`} href={href}
             aria-current={active === key ? "page" : undefined}>{label}</a>
        ))}
      </nav>
      <div className="pillgroup">
        <span className="pill pill-static" title={health ? `LLM: ${health.llm_providers?.join(", ") || "none"} · OCR: ${health.ocr_tesseract ? "tesseract" : "off"}` : ""}>
          <span className="dot" style={{ background: online ? "#5EE0A8" : health === null ? "#8FB0E3" : "#FF6B76" }} />
          {online ? "API online" : health === null ? "Connecting…" : "API offline"}
        </span>
        <button type="button" className="cta" onClick={() => setOpen((o) => !o)} aria-expanded={open} disabled={!online}>
          Run batch<span className="box"><Arrow /></span>
        </button>
        {open && (
          <div className="menu" role="menu">
            {BATCHES.map(([source, label, hint]) => (
              <button key={source} type="button" role="menuitem" onClick={() => start(source)}>{label}<small>{hint}</small></button>
            ))}
            <label role="menuitem">Upload PDFs<small>Run your own filings through the pipeline</small>
              <input ref={fileRef} type="file" accept="application/pdf" multiple hidden onChange={(e) => upload(e.target.files)} />
            </label>
          </div>
        )}
      </div>
    </header>
  );
}

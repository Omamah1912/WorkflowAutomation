// Transparency panel: every LLM call (success or failure), newest first.
import { Fragment, useEffect, useState } from "react";
import { get } from "../api.js";
import { num } from "../format.js";

export default function LlmLog({ onError }) {
  const [log, setLog] = useState(null);
  const [open, setOpen] = useState(null);
  useEffect(() => {
    const load = () => get("/llm-log").then(setLog).catch((e) => onError(e.message));
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);
  const rows = (log || []).slice().reverse();
  return (
    <section className="wrap stack" style={{ paddingTop: 40, paddingBottom: 72, gap: 28 }}>
      <span className="tag"><span className="sq" />LLM log</span>
      <h1 className="h1">Every model call</h1>
      <p className="lead" style={{ maxWidth: 680 }}>The LLM is only a fallback. Each call is listed with its prompt, reply, latency and tokens; failures (timeouts, unavailable keys) appear too.</p>
      <div className="panel">
        <span className="tag tag-sm"><span className="sq" />{rows.length} call(s)</span>
        <div className="scroll-x">
          <table className="table">
            <thead><tr><th>When</th><th>Agent</th><th>Provider</th><th>Model</th><th>Doc</th><th>OK</th><th>Latency</th><th>Tokens</th></tr></thead>
            <tbody>
              {rows.length === 0 && <tr><td colSpan={8} className="muted">No LLM calls yet: everything so far was decided classically.</td></tr>}
              {rows.map((e, i) => (
                <Fragment key={i}>
                  <tr className="click" onClick={() => setOpen(open === i ? null : i)}>
                    <td className="mono">{new Date(e.at).toLocaleTimeString()}</td>
                    <td className="mono">{e.agent}</td>
                    <td>{e.provider}</td>
                    <td className="mono">{e.model}</td>
                    <td>{e.doc_id ? <a href={`#/doc/${e.doc_id}`} onClick={(ev) => ev.stopPropagation()}>{e.doc_id}</a> : "—"}</td>
                    <td>{e.ok ? <span className="chip chip-ok">ok</span> : <span className="chip chip-crit">failed</span>}</td>
                    <td className="mono">{num(e.latency_ms)} ms</td>
                    <td className="mono">{e.tokens ? num(e.tokens.total_tokens ?? ((e.tokens.input_tokens || 0) + (e.tokens.output_tokens || 0))) : "—"}</td>
                  </tr>
                  {open === i && (
                    <tr><td colSpan={8}>
                      <div className="stack" style={{ gap: 8 }}>
                        <span className="tag tag-sm">Prompt{e.has_image ? " (+ page image)" : ""}</span>
                        <pre className="mono" style={{ whiteSpace: "pre-wrap", fontSize: 12, margin: 0 }}>{e.prompt}</pre>
                        <span className="tag tag-sm">{e.ok ? "Response" : "Error"}</span>
                        <pre className="mono" style={{ whiteSpace: "pre-wrap", fontSize: 12, margin: 0 }}>{e.ok ? e.response : e.error}</pre>
                      </div>
                    </td></tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}

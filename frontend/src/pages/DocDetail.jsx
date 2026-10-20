// One document: page image with a bbox per extracted value, fields with provenance, rule results, audit trail.
import { useEffect, useState } from "react";
import { get } from "../api.js";
import { num, valueText } from "../format.js";
import PageImage from "../components/PageImage.jsx";
import { MethodBadge, Recon, RuleChip, StatusChip } from "../components/ui.jsx";

export default function DocDetail({ docId, onError }) {
  const [doc, setDoc] = useState(null);
  const [page, setPage] = useState(1);
  const [sel, setSel] = useState(null);

  useEffect(() => {
    setDoc(null); setSel(null);
    get(`/doc/${encodeURIComponent(docId)}`).then((d) => {
      setDoc(d);
      const first = d.tracks.flatMap((t) => t.fields).find((f) => f.evidence?.page);
      setPage(first?.evidence.page || 1);
    }).catch((e) => onError(e.message));
  }, [docId]);

  if (!doc) return <div className="wrap" style={{ padding: "80px 40px" }}><span className="tag">Loading {docId}…</span></div>;

  const fields = doc.tracks.flatMap((t) => t.fields.map((f) => ({ ...f, track: t.entity_label, key: `${t.track_id}:${f.name}` })));
  if (doc.company) fields.unshift({ ...doc.company, track: "document", key: "doc:company" });
  if (doc.period) fields.unshift({ ...doc.period, track: "document", key: "doc:period" });
  const boxes = fields.filter((f) => f.evidence?.page === page && f.evidence?.bbox).map((f) => ({ key: f.key, bbox: f.evidence.bbox, label: f.name }));
  const hasPdf = doc.path && doc.path.endsWith(".pdf") && doc.pages > 0;

  return (
    <>
      <section className="wrap stack" style={{ paddingTop: 40, paddingBottom: 32, gap: 18 }}>
        <div className="wrap-row" style={{ justifyContent: "space-between", gap: 12 }}>
          <span className="tag"><span className="sq" />Document · {doc.doc_id}</span>
          <Recon label={doc.label} />
        </div>
        <h1 className="h2" style={{ wordBreak: "break-word" }}>{doc.company?.value || doc.filename.split("/").pop()}</h1>
        <div className="wrap-row mono" style={{ gap: "8px 24px", fontSize: 12, letterSpacing: "0.04em", textTransform: "uppercase", color: "#D6E2F7" }}>
          <span>{doc.doc_type || "unclassified"} · conf <span style={{ color: "#FFFFFF" }}>{doc.doc_type_confidence?.toFixed(2)}</span></span>
          <span className="row">Classified <MethodBadge method={doc.doc_type_method} /></span>
          <span>Route <span style={{ color: "#FFFFFF" }}>{doc.route || "—"}</span></span>
          <span>Source <span style={{ color: "#FFFFFF" }}>{doc.source}</span></span>
          {doc.symbol && <span>Symbol <span style={{ color: "#FFFFFF" }}>{doc.symbol}</span></span>}
          {doc.period && <span>Period <span style={{ color: "#FFFFFF" }}>{doc.period.value}</span></span>}
          {doc.duplicate_of && <span>Duplicate of <a href={`#/doc/${doc.duplicate_of}`}>{doc.duplicate_of}</a></span>}
          {doc.route === "needs_review" && <a href={`#/review/${doc.doc_id}`} style={{ color: "#FFC98A" }}>Open review packet →</a>}
        </div>
        {doc.escalation_reasons.length > 0 && (
          <ul style={{ margin: 0, paddingLeft: 18, fontSize: 14, color: "#FFC98A" }}>{doc.escalation_reasons.map((r, i) => <li key={i}>{r}</li>)}</ul>
        )}
      </section>

      <div className="wrap wrap-row" style={{ paddingBottom: 72, gap: 24, alignItems: "flex-start" }}>
        {hasPdf && (
          <section className="panel" style={{ flex: "1 1 420px", maxWidth: 640 }}>
            <div className="between">
              <span className="tag tag-sm"><span className="sq" />Page {page} of {doc.pages}</span>
              <span className="tag tag-sm muted">read via {doc.page_methods?.[page] || "—"}</span>
            </div>
            <div className="wrap-row" style={{ gap: 4 }}>
              {Array.from({ length: doc.pages }, (_, i) => i + 1).map((n) => (
                <button key={n} type="button" className={`pill pill-sm ${n === page ? "pill-on" : ""}`} onClick={() => setPage(n)}>{n}</button>
              ))}
            </div>
            <PageImage docId={doc.doc_id} page={page} boxes={boxes} selected={sel} onSelect={setSel} />
          </section>
        )}

        <div className="stack" style={{ flex: "999 1 520px", minWidth: 0, gap: 24 }}>
          <section className="panel">
            <span className="tag tag-sm"><span className="sq" />Extracted values · {doc.tracks.length} track(s)</span>
            <div className="scroll-x">
              <table className="table">
                <thead><tr><th>Track</th><th>Field</th><th>Value</th><th>Unit type</th><th>Method</th><th>Conf</th><th>Source</th></tr></thead>
                <tbody>
                  {fields.map((f) => (
                    <tr key={f.key} className={`click ${sel === f.key ? "sel" : ""}`}
                        onClick={() => { setSel(f.key); if (f.evidence?.page) setPage(f.evidence.page); }}>
                      <td className="mono">{f.track}</td>
                      <td className="mono">{f.name}</td>
                      <td>{valueText(f.value)} <span className="muted">{f.unit}</span></td>
                      <td className="mono" style={{ color: f.unit_type === "share_ratio" ? "#FFB3B9" : undefined }}>{f.unit_type}</td>
                      <td><MethodBadge method={f.method} /></td>
                      <td className="mono">{f.confidence?.toFixed(2)}</td>
                      <td className="muted" style={{ fontSize: 12 }}>
                        {f.evidence?.page ? `p.${f.evidence.page}${f.evidence.bbox ? "" : " (no bbox)"} · ` : ""}"{f.evidence?.text}"
                        {f.evidence?.source_url && <> · <a href={f.evidence.source_url} target="_blank" rel="noreferrer">source</a></>}
                      </td>
                    </tr>
                  ))}
                  {fields.length === 0 && <tr><td colSpan={7} className="muted">No values extracted (CSV rows carry metadata only, admin documents are archived without extraction).</td></tr>}
                </tbody>
              </table>
            </div>
          </section>

          {doc.tracks.map((t) => t.rule_results.length > 0 && (
            <section key={t.track_id} className="panel">
              <span className="tag tag-sm"><span className="sq" />Rules · {t.entity_label}</span>
              <div className="scroll-x">
                <table className="table">
                  <thead><tr><th>Rule</th><th>Status</th><th>Message</th><th>Clause</th></tr></thead>
                  <tbody>
                    {t.rule_results.map((r) => (
                      <tr key={r.rule_id}>
                        <td><RuleChip rule={r.rule_id} severity={r.status === "fail" ? r.severity : "none"} /></td>
                        <td><StatusChip status={r.status} /></td>
                        <td>{r.message}</td>
                        <td className="muted" style={{ fontSize: 12 }}>{r.source_clause}{r.verify && <> <span className="chip chip-line" style={{ height: 18, fontSize: 10 }}>verify</span></>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          ))}

          <section className="panel">
            <span className="tag tag-sm"><span className="sq" />Audit trail · {doc.audit.length} events</span>
            <div className="scroll-x" style={{ maxHeight: 420, overflowY: "auto" }}>
              <table className="table">
                <thead><tr><th>Stage</th><th>Agent</th><th>Method</th><th>Decision</th><th>ms</th></tr></thead>
                <tbody>
                  {doc.audit.map((e, i) => (
                    <tr key={i}><td className="mono">{e.stage}</td><td>{e.agent}</td><td><MethodBadge method={e.method} /></td>
                      <td style={{ color: e.status === "error" ? "#FFB3B9" : e.status === "warning" ? "#FFC98A" : undefined }}>{e.decision}</td>
                      <td className="mono">{e.duration_ms ? num(e.duration_ms, 1) : ""}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="panel">
            <span className="tag tag-sm"><span className="sq" />Ledger · {doc.ledger.length} row(s)</span>
            {doc.ledger.length === 0 && <span className="muted" style={{ fontSize: 14 }}>Nothing written. {doc.route === "needs_review" ? "Blocked until a human approves." : doc.source.startsWith("csv") ? "CSV rows are routed, not entered." : ""}</span>}
            {doc.ledger.map((l) => (
              <div key={l.track_id} className="mono" style={{ fontSize: 12 }}>{l.track_id} · approved by {l.approved_by} · {l.created_at}</div>
            ))}
          </section>
        </div>
      </div>
    </>
  );
}

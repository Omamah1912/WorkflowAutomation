// Review queue + review packet for escalated documents. Approve writes to the ledger.
import { useEffect, useRef, useState } from "react";
import { get, post } from "../api.js";
import { ago, methodKind, num, valueText } from "../format.js";
import PageImage from "../components/PageImage.jsx";
import { Arrow, MethodBadge, Recon, RuleChip } from "../components/ui.jsx";

const HOLD_MS = 1500;

export default function Review({ docId, onError }) {
  const [queue, setQueue] = useState(null);
  const [doc, setDoc] = useState(null);
  const [reviewer, setReviewer] = useState(() => { try { return localStorage.getItem("gs-reviewer") || ""; } catch { return ""; } });

  const loadQueue = () => get("/review-queue").then(setQueue).catch((e) => onError(e.message));
  useEffect(() => { loadQueue(); }, []);
  const selected = docId || queue?.[0]?.doc_id;
  useEffect(() => {
    if (!selected) { setDoc(null); return; }
    get(`/doc/${encodeURIComponent(selected)}`).then(setDoc).catch((e) => onError(e.message));
  }, [selected]);
  useEffect(() => { try { localStorage.setItem("gs-reviewer", reviewer); } catch { /* storage blocked */ } }, [reviewer]);

  const critical = (queue || []).filter((q) => q.critical).length;
  const after = async () => {
    const q = await get("/review-queue");
    setQueue(q);
    if (selected) setDoc(await get(`/doc/${encodeURIComponent(selected)}`));
  };

  return (
    <>
      <section className="wrap stack" style={{ paddingTop: 40, paddingBottom: 40, gap: 20 }}>
        <span className="tag"><span className="sq" />Review queue</span>
        <div className="wrap-row" style={{ alignItems: "flex-end", justifyContent: "space-between", gap: 24 }}>
          <div className="stack" style={{ gap: 14 }}>
            <h1 className="h1">Review queue</h1>
            <span className="tag muted" style={{ whiteSpace: "normal" }}>
              {queue ? queue.length : "…"} escalated · <span style={{ color: "#FFB3B9" }}>{critical} critical</span> · ledger blocked until a human acts
            </span>
          </div>
          <div className="stack" style={{ gap: 8 }}>
            <label htmlFor="reviewer" className="tag tag-sm muted">Reviewer</label>
            <input id="reviewer" className="input" style={{ width: 240 }} placeholder="Your name" value={reviewer} onChange={(e) => setReviewer(e.target.value)} />
          </div>
        </div>
      </section>

      <div className="wrap wrap-row" style={{ paddingBottom: 72, gap: 40, alignItems: "flex-start" }}>
        <nav aria-label="Escalated items" className="stack" style={{ flex: "1 1 340px", maxWidth: 400, gap: 10 }}>
          <div className="between tag tag-sm muted" style={{ padding: "0 2px 6px", borderBottom: "1px solid rgba(255,255,255,0.18)" }}>
            <span>Severity, then age</span><span>{queue?.length ?? 0} items</span>
          </div>
          {queue && queue.length === 0 && <p className="muted" style={{ fontSize: 14 }}>Nothing is waiting. Run a batch (try the Samsung replay) to see escalations here.</p>}
          {(queue || []).map((q) => (
            <button key={q.doc_id} type="button" className={`item ${q.doc_id === selected ? "item-on" : ""}`}
                    aria-current={q.doc_id === selected} onClick={() => { window.location.hash = `#/review/${q.doc_id}`; }}>
              <span className="wrap-row" style={{ gap: 6 }}>
                <span className={`chip ${q.critical ? "chip-crit" : "chip-warn"}`}>{q.critical ? "Critical" : "Review"}</span>
                {q.label && <span className="chip" style={{ border: "1px solid #B54708", color: q.doc_id === selected ? "#B54708" : "#FFC98A" }}>Reconstruction</span>}
              </span>
              <span className="cons">{q.consequence}</span>
              <span className="meta">{q.company || "Unknown company"} · {q.doc_type}</span>
              <span className="between">
                <span className="wrap-row" style={{ gap: 6 }}>{q.failed_rules.slice(0, 3).map((r) => <RuleChip key={r.rule_id} rule={r.rule_id} severity={r.severity} />)}</span>
                <span className="age">{ago(q.escalated_at)}</span>
              </span>
            </button>
          ))}
        </nav>

        <main aria-label="Review packet" className="stack" style={{ flex: "999 1 640px", minWidth: 0, gap: 28 }}>
          {doc ? <Packet doc={doc} reviewer={reviewer} onDone={after} onError={onError} /> : selected ? <span className="tag">Loading packet…</span> : null}
        </main>
      </div>
    </>
  );
}

function Packet({ doc, reviewer, onDone, onError }) {
  const packet = doc.review_packet;
  const awaiting = doc.route === "needs_review";
  const allRules = doc.tracks.flatMap((t) => t.rule_results.map((r) => ({ ...r, track_id: t.track_id })));
  const failed = allRules.filter((r) => r.status === "fail");
  const passed = allRules.filter((r) => r.status === "pass").length;
  const isCritical = failed.some((r) => r.severity === "critical");
  const routedAt = [...doc.audit].reverse().find((e) => e.stage === "route")?.started_at;
  const classifyMethod = doc.doc_type_method;
  const div02 = failed.find((r) => r.rule_id === "DIV-02");
  const multiple = div02?.message.match(/~([\d.]+)x/)?.[1];

  return (
    <>
      <div className="stack" style={{ gap: 22 }}>
        <div className="wrap-row" style={{ justifyContent: "space-between", gap: 12 }}>
          <span className="tag"><span className="sq" />Review packet · {doc.doc_id}</span>
          <Recon label={doc.label} />
        </div>
        <span className="row">
          {awaiting
            ? <span className={`chip ${isCritical ? "chip-crit" : "chip-warn"}`} style={{ height: 26, padding: "0 10px" }}>● {isCritical ? "Critical" : "Needs review"} · Ledger entry blocked</span>
            : <span className="chip chip-ok" style={{ height: 26, padding: "0 10px" }}>Decision recorded · route {doc.route}</span>}
        </span>
        <h2 style={{ margin: 0, fontSize: 48, lineHeight: "54px", fontWeight: 400, letterSpacing: "-0.035em", maxWidth: 880 }}>
          {packet?.consequence || doc.escalation_reasons[0] || "No review packet"}
        </h2>
        {packet && (
          <p className="lead" style={{ maxWidth: 720 }}>
            {packet.computed_consequence}
            {packet.consequence_method !== "classical" && <span className="muted"> (sentence written by <MethodBadge method={packet.consequence_method} />; facts above computed by the rules)</span>}
          </p>
        )}
        <div className="wrap-row mono" style={{ gap: "8px 24px", paddingTop: 18, borderTop: "1px solid rgba(255,255,255,0.22)", fontSize: 12, letterSpacing: "0.04em", textTransform: "uppercase", color: "#D6E2F7" }}>
          <span>{doc.company?.value || "Unknown company"} · {doc.doc_type}</span>
          <span>Source <span style={{ color: "#FFFFFF" }}>{doc.source}</span></span>
          <span className="row">Classified <MethodBadge method={classifyMethod} /></span>
          <span>Resolver <span style={{ color: "#FFFFFF" }}>{doc.resolver_loops}/2</span>{failed.some((r) => r.severity === "critical") ? " unresolved" : ""}</span>
          <span>Escalated <span style={{ color: "#FFFFFF" }}>{ago(routedAt)}</span> ago</span>
          <a href={`#/doc/${doc.doc_id}`} style={{ color: "#FFFFFF" }}>Full document →</a>
        </div>
      </div>

      {doc.escalation_reasons.length > 0 && (
        <section className="panel">
          <div className="between"><span className="tag tag-sm"><span className="sq" />Why it was escalated</span><span className="tag tag-sm muted">{doc.escalation_reasons.length} reason(s)</span></div>
          <ul style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 6, fontSize: 14 }}>
            {doc.escalation_reasons.map((r, i) => <li key={i}>{r}</li>)}
          </ul>
        </section>
      )}

      <div className="wrap-row" style={{ gap: 16, alignItems: "stretch" }}>
        <section className="panel" style={{ flex: "1 1 360px" }} aria-labelledby="rules-h">
          <div className="between"><span className="tag tag-sm"><span className="sq" />Validate</span><span className="tag tag-sm muted">{failed.length} failed · {passed} passed</span></div>
          <h3 id="rules-h" className="h3">Failing rules</h3>
          {failed.length === 0 && <span className="muted" style={{ fontSize: 14 }}>No rule failed. The escalation comes from the reasons above.</span>}
          {failed.map((r, i) => (
            <div key={i} className="rule">
              <div className="between">
                <span className="row"><RuleChip rule={r.rule_id} severity={r.severity} /><span style={{ fontSize: 13 }} className="muted mono">{r.track_id.split("/").pop()}</span></span>
                <span className="tag" style={{ fontSize: 11, color: r.severity === "critical" ? "#FFB3B9" : "#FFC98A" }}>✕ {r.severity}</span>
              </div>
              <span style={{ fontSize: 14, lineHeight: "20px" }}>{r.message}</span>
              <dl className="kv">
                <dt>Expected</dt><dd>{fmtVal(r.expected)}</dd>
                <dt>Actual</dt><dd style={{ color: "#FFB3B9" }}>{fmtVal(r.actual)}</dd>
              </dl>
              <div className="wrap-row" style={{ gap: 8, fontSize: 12 }}>
                <span className="mono muted">{r.source_clause}</span>
                {r.verify && <span className="chip chip-line" style={{ height: 20, fontSize: 11 }}>clause to verify</span>}
              </div>
            </div>
          ))}
        </section>
        <Evidence doc={doc} packet={packet} />
      </div>

      {packet?.suggested_fix?.length > 0 && <SuggestedFix doc={doc} packet={packet} />}

      {awaiting
        ? <Decision doc={doc} reviewer={reviewer} isCritical={isCritical} multiple={multiple} div02={div02} onDone={onDone} onError={onError} />
        : <LedgerResult doc={doc} />}
    </>
  );
}

function fmtVal(v) {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return num(v, 4);
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

function Evidence({ doc, packet }) {
  const items = packet?.evidence || [];
  const onPage = items.find((e) => e.page && e.bbox) || items.find((e) => e.page);
  const [sel, setSel] = useState(0);
  const pageBoxes = onPage ? items.filter((e) => e.page === onPage.page).map((e, i) => ({ key: i, bbox: e.bbox, label: e.field })) : [];
  return (
    <section className="panel" style={{ flex: "1 1 360px" }} aria-labelledby="ev-h">
      <div className="between">
        <span className="tag tag-sm"><span className="sq" />Evidence</span>
        <span className="tag tag-sm muted">{onPage ? `p.${onPage.page}${onPage.bbox ? ` · bbox [${onPage.bbox.map((v) => Math.round(v)).join(",")}]` : ""}` : "no source page"}</span>
      </div>
      <h3 id="ev-h" className="h3">Source {onPage ? "on the page" : "for each value"}</h3>
      {onPage && doc.path && <PageImage docId={doc.doc_id} page={onPage.page} boxes={pageBoxes} selected={sel} onSelect={setSel} />}
      <div className="stack" style={{ gap: 10 }}>
        {items.length === 0 && <span className="muted" style={{ fontSize: 14 }}>No field-level evidence: see the escalation reasons.</span>}
        {items.map((e, i) => (
          <div key={i} style={{ fontSize: 13, lineHeight: "20px" }}>
            <span className="mono" style={{ color: "#FFFFFF" }}>{e.field}</span> = <span className="tok">{valueText(e.value)} {e.unit}</span>{" "}
            <span className="mono" style={{ color: e.unit_type === "share_ratio" ? "#FFB3B9" : "#D6E2F7" }}>({e.unit_type})</span>{" "}
            <MethodBadge method={e.method} />
            <div className="muted">"{e.text}"{e.page ? ` · p.${e.page}` : ""}</div>
            {e.source_url && <a href={e.source_url} target="_blank" rel="noreferrer" className="mono" style={{ fontSize: 12 }}>{e.source_url}</a>}
          </div>
        ))}
      </div>
    </section>
  );
}

function SuggestedFix({ doc, packet }) {
  const primary = doc.tracks[0];
  const entered = primary?.fields.find((f) => f.name === "cash_dividend");
  const declared = primary?.fields.find((f) => f.name === "declared_cash_dividend");
  const showSwap = entered && declared && entered.unit_type !== declared.unit_type;
  return (
    <section className="panel" aria-labelledby="fix-h">
      <div className="between"><span className="tag tag-sm"><span className="sq" />Suggested fix</span><span className="row muted" style={{ fontSize: 12 }}>From the rules <MethodBadge method="classical" /></span></div>
      <h3 id="fix-h" className="h3">{showSwap ? "Re-type the entitlement as cash per share" : "What would resolve this"}</h3>
      {showSwap && (
        <div className="wrap-row" style={{ gap: 16 }}>
          <div className="stack" style={{ flex: "1 1 220px", padding: "14px 16px", border: "1px solid rgba(255,179,185,0.5)", borderRadius: 4, gap: 4 }}>
            <span className="tag" style={{ fontSize: 11 }}>Current</span>
            <span className="mono" style={{ fontSize: 15, color: "#FFB3B9", textDecoration: "line-through" }}>{num(entered.value)} {entered.unit} · {entered.unit_type}</span>
          </div>
          <span className="mono" aria-hidden="true">→</span>
          <div className="stack" style={{ flex: "1 1 220px", padding: "14px 16px", border: "1px solid rgba(94,224,168,0.6)", borderRadius: 4, gap: 4 }}>
            <span className="tag" style={{ fontSize: 11 }}>Suggested</span>
            <span className="mono" style={{ fontSize: 15, color: "#8EF0C4" }}>{num(declared.value)} {declared.unit} · {declared.unit_type}</span>
          </div>
        </div>
      )}
      <ul style={{ margin: 0, paddingLeft: 18, display: "flex", flexDirection: "column", gap: 6, fontSize: 14 }}>
        {packet.suggested_fix.map((f, i) => <li key={i}>{f}</li>)}
      </ul>
    </section>
  );
}

function Decision({ doc, reviewer, isCritical, multiple, div02, onDone, onError }) {
  const [confirmed, setConfirmed] = useState(false);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [holdPct, setHoldPct] = useState(0);
  const [result, setResult] = useState(null);
  const timer = useRef(null);
  const needName = !reviewer.trim();

  const act = async (action, extra = {}) => {
    if (needName) { onError("Enter your name as reviewer first."); return; }
    setBusy(true);
    try {
      const r = await post(`/review/${encodeURIComponent(doc.doc_id)}`, { action, reviewer: reviewer.trim(), ...extra });
      setResult(r);
      await onDone();
    } catch (e) { onError(e.message); } finally { setBusy(false); }
  };

  // Critical items need a 1.5 s press-and-hold; releasing early cancels.
  const startHold = () => {
    if (!isCritical) { act("approve"); return; }
    const t0 = Date.now();
    timer.current = setInterval(() => {
      const p = Math.min(1, (Date.now() - t0) / HOLD_MS);
      setHoldPct(p);
      if (p >= 1) { clearInterval(timer.current); setHoldPct(0); act("approve"); }
    }, 30);
  };
  const stopHold = () => { clearInterval(timer.current); setHoldPct(0); };

  const consequence = div02
    ? <>I confirm this will issue <span className="tok">{num(div02.actual)}</span> shares{multiple ? ` (~${multiple}× shares outstanding)` : ""}.</>
    : <>I confirm I have read the escalation reasons and the evidence for {doc.doc_id}.</>;

  return (
    <section aria-labelledby="act-h" className="stack" style={{ gap: 20, paddingTop: 24, borderTop: "1px solid rgba(255,255,255,0.22)" }}>
      <div className="between"><span className="tag tag-sm"><span className="sq" /><span id="act-h">Decision</span></span><span className="tag tag-sm muted">Approve writes to the ledger</span></div>
      <label className="confirm" htmlFor="confirm">
        <input id="confirm" type="checkbox" checked={confirmed} onChange={() => setConfirmed((c) => !c)} />
        <span style={{ fontSize: 17, lineHeight: "26px" }}>{consequence}</span>
      </label>
      <div className="wrap-row" style={{ justifyContent: "space-between", gap: 16 }}>
        <div className="wrap-row" style={{ gap: 12 }}>
          <button type="button" className="cta cta-lg hold" disabled={!confirmed || busy}
                  onPointerDown={startHold} onPointerUp={stopHold} onPointerLeave={stopHold}>
            <span className="fill" style={{ width: `${holdPct * 100}%` }} />
            {isCritical ? "Hold to approve" : "Approve"}<span className="box"><Arrow size={16} /></span>
          </button>
          <button type="button" className="ghost" disabled={busy} onClick={() => setEditing((e) => !e)}>Edit</button>
          <button type="button" className="ghost ghost-danger" disabled={busy} onClick={() => act("reject")}>Reject</button>
        </div>
        <span className="tag tag-sm muted" style={{ whiteSpace: "normal" }}>
          {needName ? "Enter your reviewer name above." : !confirmed ? "Approve unlocks once you confirm the consequence."
            : isCritical ? "Critical item: hold 1.5 s. Release early to cancel." : "Approving writes every track to the ledger."}
        </span>
      </div>
      {editing && <EditForm doc={doc} busy={busy} onSubmit={(edits, trackId) => act("edit", { edits, track_id: trackId })} />}
      {result && (
        <div className="panel" style={{ fontSize: 14 }}>
          <span>Result: route <b>{result.route}</b> · ledger rows written {result.ledger_rows_written}
            {result.critical_still_failing.length > 0 && <> · <span style={{ color: "#FFB3B9" }}>critical still failing: {result.critical_still_failing.join(", ")}</span></>}</span>
        </div>
      )}
    </section>
  );
}

function EditForm({ doc, busy, onSubmit }) {
  const [trackId, setTrackId] = useState(doc.tracks[0]?.track_id);
  const track = doc.tracks.find((t) => t.track_id === trackId) || doc.tracks[0];
  const editable = (track?.fields || []).filter((f) => typeof f.value === "number" || typeof f.value === "string");
  const [field, setField] = useState(editable[0]?.name || "");
  const current = editable.find((f) => f.name === field);
  const [value, setValue] = useState("");
  const [unit, setUnit] = useState("");
  useEffect(() => { setValue(current ? String(current.value) : ""); setUnit(current?.unit || ""); }, [field, trackId]);

  const submit = () => {
    const parsed = value.trim() !== "" && !Number.isNaN(Number(value)) ? Number(value) : value;
    onSubmit({ [field]: { value: parsed, unit } }, trackId);
  };
  return (
    <div className="panel">
      <span className="tag tag-sm"><span className="sq" />Edit a value · rules re-run immediately</span>
      <div className="wrap-row" style={{ gap: 12 }}>
        {doc.tracks.length > 1 && (
          <select className="input" value={trackId} onChange={(e) => setTrackId(e.target.value)}>
            {doc.tracks.map((t) => <option key={t.track_id} value={t.track_id}>{t.entity_label}</option>)}
          </select>
        )}
        <select className="input" value={field} onChange={(e) => setField(e.target.value)}>
          {editable.map((f) => <option key={f.name} value={f.name}>{f.name}</option>)}
        </select>
        <input className="input" style={{ width: 160 }} value={value} onChange={(e) => setValue(e.target.value)} aria-label="Value" />
        <input className="input" style={{ width: 200 }} value={unit} onChange={(e) => setUnit(e.target.value)} aria-label="Unit" placeholder="unit, e.g. KRW per share" />
        <button type="button" className="ghost ghost-sm" disabled={busy || !field} onClick={submit}>Apply edit</button>
      </div>
      {current && <span className="muted" style={{ fontSize: 13 }}>Was {valueText(current.value)} {current.unit} ({current.unit_type}, {methodKind(current.method)})</span>}
    </div>
  );
}

function LedgerResult({ doc }) {
  const decision = [...doc.audit].reverse().find((e) => e.stage === "review");
  return (
    <section className="panel">
      <span className="tag tag-sm"><span className="sq" />Decision</span>
      <span style={{ fontSize: 15 }}>{decision ? decision.decision : `Route: ${doc.route}`}</span>
      <span className="muted" style={{ fontSize: 13 }}>{doc.ledger.length} ledger row(s) for this document.</span>
    </section>
  );
}

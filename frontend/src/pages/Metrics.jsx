// Metrics vs the ps07 manual baseline, all computed by GET /metrics.
import { useEffect, useState } from "react";
import { get } from "../api.js";
import { num, pct } from "../format.js";

export default function Metrics({ onError }) {
  const [m, setM] = useState(null);
  useEffect(() => {
    const load = () => get("/metrics").then(setM).catch((e) => onError(e.message));
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);
  if (!m) return <div className="wrap" style={{ padding: "80px 40px" }}><span className="tag">Loading metrics…</span></div>;

  const err = m.errors_caught_vs_baseline, time = m.time_saved_vs_baseline, acc = m.relevance_accuracy_vs_ps07_ground_truth;
  const share = m.classical_vs_llm_share;
  const totalEvents = Object.values(share.counts || {}).reduce((a, b) => a + b, 0);
  return (
    <section className="wrap stack" style={{ paddingTop: 40, paddingBottom: 72, gap: 40 }}>
      <div className="stack" style={{ gap: 20 }}>
        <span className="tag"><span className="sq" />Metrics · refreshes every 5 s</span>
        <h1 className="h1">Against the manual baseline</h1>
        <p className="lead" style={{ maxWidth: 680 }}>Baseline = the ps07 analysts' own log: {num(time.baseline_total_minutes)} minutes across 250 jobs. Every figure below is recomputed from processed documents and audit events.</p>
      </div>
      {m.documents_processed === 0 && <p className="muted">No documents processed yet. Run the CSV batch to compare against the baseline.</p>}
      <div className="wrap-row" style={{ gap: 32, alignItems: "stretch" }}>
        <div className="stat"><span className="statlbl">Automation rate</span><span className="statnum">{pct(m.automation_rate)}</span><span className="statcap">of {num(m.documents_processed)} documents closed with no human</span></div>
        <div className="stat"><span className="statlbl">Throughput</span><span className="statnum">{num(m.throughput_docs_per_min, 1)}</span><span className="statcap">documents per minute</span></div>
        <div className="stat"><span className="statlbl">Errors caught</span><span className="statnum">{num(err.caught_by_pipeline)}/{num(err.baseline_errors_total)}</span><span className="statcap">analyst errors in ps07 the pipeline prevents</span></div>
        <div className="stat"><span className="statlbl">Time saved</span><span className="statnum">{num(time.minutes_saved)}</span><span className="statcap">analyst minutes ({pct(time.share_of_baseline, 1)} of baseline)</span></div>
      </div>
      <div className="wrap-row" style={{ gap: 16, alignItems: "stretch" }}>
        <div className="panel" style={{ flex: "1 1 360px" }}>
          <span className="tag tag-sm"><span className="sq" />Errors in the manual baseline</span>
          <dl className="kv" style={{ gridTemplateColumns: "1fr auto" }}>
            <dt>Irrelevant docs processed</dt><dd>{err.baseline_irrelevant_docs_processed_by_analysts}</dd>
            <dt>Duplicates processed twice</dt><dd>{err.baseline_duplicates_processed_twice}</dd>
            <dt>Caught by pipeline</dt><dd>{err.caught_by_pipeline}</dd>
            <dt>Critical failures kept out of ledger</dt><dd>{err.critical_rule_failures_blocked_from_ledger}</dd>
          </dl>
          {err.critical_failure_docs.length > 0 && <div className="wrap-row" style={{ gap: 6 }}>{err.critical_failure_docs.map((d) => <a key={d} className="chip chip-crit" href={`#/doc/${d}`}>{d}</a>)}</div>}
        </div>
        <div className="panel" style={{ flex: "1 1 360px" }}>
          <span className="tag tag-sm"><span className="sq" />Relevance vs ps07 was_relevant</span>
          <span className="statnum" style={{ fontSize: 40 }}>{acc ? pct(acc.accuracy, 1) : "—"}</span>
          <span className="muted" style={{ fontSize: 14 }}>{acc ? `${acc.correct} of ${acc.total} jobs classified correctly` : "Run the CSV batch"}</span>
        </div>
        <div className="panel" style={{ flex: "1 1 360px" }}>
          <span className="tag tag-sm"><span className="sq" />Who made the decisions</span>
          {Object.entries(share.counts || {}).map(([k, v]) => (
            <div key={k} className="stack" style={{ gap: 4 }}>
              <div className="between" style={{ fontSize: 13 }}><span className="mono">{k}</span><span className="mono">{num(v)}</span></div>
              <div className="bar"><span style={{ width: `${(v / totalEvents) * 100}%`, background: k.startsWith("llm") ? "#FFC98A" : "#FFFFFF" }} /></div>
            </div>
          ))}
          <span className="muted" style={{ fontSize: 13 }}>LLM share {pct(share.llm_share, 1)}</span>
        </div>
      </div>
      <div className="wrap-row" style={{ gap: 16 }}>
        <div className="panel" style={{ flex: "1 1 360px" }}>
          <span className="tag tag-sm"><span className="sq" />Routes</span>
          <div className="wrap-row" style={{ gap: 8 }}>{Object.entries(m.routes).map(([k, v]) => <span key={k} className="chip chip-neutral">{k} {v}</span>)}</div>
        </div>
        <div className="panel" style={{ flex: "1 1 360px" }}>
          <span className="tag tag-sm"><span className="sq" />Queue depth by stage</span>
          <div className="wrap-row" style={{ gap: 8 }}>{Object.entries(m.queue_depth_by_stage).map(([k, v]) => <span key={k} className="chip chip-neutral">{k} {v}</span>)}</div>
        </div>
      </div>
    </section>
  );
}

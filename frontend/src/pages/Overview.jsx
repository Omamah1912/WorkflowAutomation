// Landing page. Live numbers come from /metrics and /baseline; Samsung facts from /fixtures;
// the 31.6x "router output" only appears after the replay has actually run through the pipeline.
import { useEffect, useState } from "react";
import { API, get, post, runAndWait } from "../api.js";
import { compact, num, pct } from "../format.js";
import { Arrow, Logo, Recon } from "../components/ui.jsx";

const AGENTS = [
  ["Intake", "Normalises IDs and dates, fingerprints files, holds duplicates.", "Classical only", "M3 13h5l1 3h6l1-3h5|M5 13V5h14v8"],
  ["Classifier", "Decides type, relevance and stream; archives admin noise.", "Classical first → LLM fallback", "M3 12V4h8l10 10-8 8z|M7.5 7.5h.01"],
  ["Extractor", "Reads values with page and bounding box for every figure.", "Classical first → LLM fallback", "M4 8V4h4M16 4h4v4M20 16v4h-4M8 20H4v-4|M8 12h8"],
  ["Transformer", "Converts units, splits consolidated and unconsolidated tracks.", "Classical first → LLM fallback", "M4 8h14l-3-3M20 16H6l3 3"],
  ["Validator", "Runs YAML rules: unit types, share limits, cross-record checks.", "Classical only", "M12 3l8 3v6c0 4.5-3.4 8-8 9-4.6-1-8-4.5-8-9V6z|M8.5 12l2.5 2.5 4.5-5"],
  ["Resolver", "Re-reads a failed field on its page before escalating (max 2 loops).", "Classical first → LLM fallback", "M20 12a8 8 0 1 1-2.3-5.6|M20 4v5h-5"],
  ["Router", "Approves, archives or escalates with a consequence sentence.", "Classical first → LLM fallback", "M4 12h7l5-6h4M11 12l5 6h4"],
];
const CATCHES = [["Unit-type mismatches", "DIV-01"], ["Share issuance beyond shares outstanding", "DIV-02"],
                 ["Declared vs credited amount mismatches", "DIV-05"], ["Duplicate and re-posted filings", "CSV-03"]];

export default function Overview({ onError }) {
  const [metrics, setMetrics] = useState(null);
  const [baseline, setBaseline] = useState(null);
  const [fixture, setFixture] = useState(null);
  const [replay, setReplay] = useState(null);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    get("/metrics").then(setMetrics).catch(() => {});
    get("/baseline").then(setBaseline).catch((e) => onError(e.message));
    get("/fixtures").then((f) => setFixture(f[0] || null)).catch(() => {});
    get(`/doc/${fixtureId()}`).then(setReplay).catch(() => setReplay(null));
  }, []);

  const field = (name) => fixture?.fields.find((f) => f.name === name);
  const entered = field("cash_dividend"), declared = field("declared_cash_dividend");
  const eligible = field("eligible_shares"), accounts = field("credited_accounts");
  const ghost = entered && eligible ? entered.value * eligible.value : null;
  const div02 = replay?.tracks.flatMap((t) => t.rule_results).find((r) => r.rule_id === "DIV-02" && r.status === "fail");
  const multiple = div02?.message.match(/~([\d.]+)x/)?.[1];
  const err = metrics?.errors_caught_vs_baseline, time = metrics?.time_saved_vs_baseline;
  const ran = metrics && metrics.documents_processed > 0;

  const runReplay = async () => {
    setRunning(true);
    try {
      await runAndWait("fixture");
      window.location.hash = `#/review/${fixtureId()}`;
    } catch (e) { onError(e.message); setRunning(false); }
  };
  const start = async (source) => {
    try {
      const { batch_id } = await post("/batch", { source });
      window.location.hash = `#/pipeline/${batch_id}`;
    } catch (e) { onError(e.message); }
  };

  return (
    <div>
      {/* HERO */}
      <section aria-label="Introduction" style={{ position: "relative", minHeight: 760, display: "flex", flexDirection: "column" }}>
        <div className="wrap" style={{ flex: 1, width: "100%", position: "relative", display: "flex", flexDirection: "column", justifyContent: "flex-end", paddingBottom: 48 }}>
          <GateGraphic />
          <div className="wrap-row" style={{ position: "relative", alignItems: "flex-end", justifyContent: "space-between", gap: 40, paddingTop: 400 }}>
            <div className="stack" style={{ flex: "1 1 640px", maxWidth: 820, gap: 28 }}>
              <span className="tag"><span className="sq" />PS-13 · Document workflow automation</span>
              <h1 className="display">Stop ghost shares before they exist.</h1>
              <p className="lead" style={{ maxWidth: 600 }}>An agentic pipeline that reads PSX corporate filings, checks every figure against the rules, and escalates to a human only when something is wrong.</p>
              <div className="wrap-row" style={{ gap: 12 }}>
                <button type="button" className="cta cta-lg" onClick={() => start("manifest")}>Run the pipeline<span className="box"><Arrow size={16} /></span></button>
                <button type="button" className="ghost" onClick={runReplay} disabled={running}>{running ? "Replaying…" : "Replay the Samsung error"}</button>
              </div>
            </div>
            <div className="stack" style={{ flex: "0 1 400px", gap: 12 }}>
              <span className="tag tag-sm muted"><span className="sq" />Live metrics</span>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(2, minmax(0,1fr))", gap: 8 }}>
                <Mini label="Automation rate" value={ran ? pct(metrics.automation_rate) : "—"} />
                <Mini label="Docs / min" value={ran ? num(metrics.throughput_docs_per_min, 1) : "—"} />
                <Mini label="Errors caught" value={ran && err ? `${err.caught_by_pipeline}/${err.baseline_errors_total}` : "—"} />
                <Mini label="Time saved" value={ran && time ? `${num(time.minutes_saved)} min` : "—"} />
              </div>
              <div className="between" style={{ fontSize: 13 }}>
                <span className="muted">{ran ? `${num(metrics.documents_processed)} documents processed so far.` : "Run a batch to see live results."}</span>
                <a className="tag tag-sm" href="#/metrics">All metrics</a>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* RUNS ON */}
      <section aria-label="Data sources" style={{ borderTop: "1px solid rgba(255,255,255,0.2)", borderBottom: "1px solid rgba(255,255,255,0.2)" }}>
        <div className="wrap wrap-row" style={{ paddingTop: 28, paddingBottom: 28, gap: "12px 16px" }}>
          <span className="tag muted" style={{ marginRight: 12 }}><span className="sq" />Runs on</span>
          <span className="src">ps01 <span className="muted">· {baseline ? num(baseline.ps01_rows) : "…"} docs</span></span>
          <span className="src">ps07 <span className="muted">· {baseline ? num(baseline.jobs) : "…"} jobs</span></span>
          <span className="src">PSX filings</span><span className="src">PSX Rule Book</span><span className="src">Companies Act 2017</span>
        </div>
      </section>

      {/* PROBLEM */}
      <section aria-labelledby="problem-h">
        <div className="wrap stack" style={{ paddingTop: 112, paddingBottom: 112, gap: 56 }}>
          <div className="wrap-row" style={{ alignItems: "flex-end", justifyContent: "space-between", gap: 32 }}>
            <div className="stack" style={{ gap: 24, maxWidth: 760 }}>
              <span className="tag"><span className="sq" />The problem</span>
              <h2 id="problem-h" className="h2">Approvers check the entry, not its consequence.</h2>
            </div>
            <p className="lead" style={{ maxWidth: 440 }}>Filings arrive in volume, units hide in prose, and the approval step trusts the person who typed the number.</p>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(280px, 1fr))", gap: 16 }}>
            <Tile n="01" title={baseline ? `${pct(baseline.irrelevant_share)} noise` : "…"}
                  text={baseline ? `${baseline.irrelevant_jobs} of ${baseline.jobs} ps07 jobs are admin noise, and analysts still processed ${baseline.irrelevant_processed} of them (${num(baseline.minutes_on_irrelevant)} minutes).` : ""} />
            <Tile n="02" title="Unit traps" text={'"40%" is a cash dividend on face value in one filing; "1,000 per share" was shares instead of won in another.'} />
            <Tile n="03" title="Rubber-stamp approval" text="Approvers check the entry, not its consequence. GhostStop shows the consequence first." />
          </div>
        </div>
      </section>

      {/* AGENTS */}
      <section aria-labelledby="agents-h">
        <div className="wrap stack" style={{ paddingTop: 16, paddingBottom: 112, gap: 48 }}>
          <div className="stack" style={{ gap: 24 }}>
            <span className="tag"><span className="sq" />The agents</span>
            <h2 id="agents-h" className="display" style={{ maxWidth: 900 }}>Seven agents. Classical first.</h2>
            <p className="lead" style={{ maxWidth: 560 }}>Each document runs through rule-based steps first. A model is called only when a classical method can't decide, and every decision records which one made it.</p>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: 16 }}>
            {AGENTS.map(([name, text, foot, icon]) => (
              <a key={name} className="tile" href={name === "Router" ? "#/review" : "#/pipeline"} style={{ minHeight: 240 }}>
                <div className="between">
                  <span className="icon"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#FFFFFF" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{icon.split("|").map((d) => <path key={d} d={d} />)}</svg></span>
                  <span className="tag tag-sm muted">[ {name} ]</span>
                </div>
                <span style={{ fontSize: 28, lineHeight: "32px", letterSpacing: "-0.02em", marginTop: 12 }}>{name}</span>
                <span className="muted" style={{ fontSize: 15, lineHeight: "22px" }}>{text}</span>
                <span className="foot">{foot}</span>
              </a>
            ))}
            <a className="tile" href="#/pipeline" style={{ minHeight: 240, background: "#FFFFFF", color: "#0449B4" }}>
              <span className="tag tag-sm" style={{ color: "#0449B4" }}><span className="sq" style={{ background: "#0449B4" }} />Pipeline</span>
              <span style={{ fontSize: 28, lineHeight: "32px", letterSpacing: "-0.02em", marginTop: "auto", color: "#0B1220" }}>Watch every document move, live.</span>
              <span className="between" style={{ fontWeight: 500 }}>Open the board<span className="cta" style={{ padding: 0, background: "#0449B4", width: 44, height: 44, justifyContent: "center" }}><Arrow size={16} /></span></span>
            </a>
          </div>
        </div>
      </section>

      {/* HOOK */}
      <section aria-labelledby="hook-h" style={{ background: "#0B1220" }}>
        <div className="wrap stack" style={{ paddingTop: 96, paddingBottom: 96, gap: 48 }}>
          <div className="wrap-row" style={{ justifyContent: "space-between", gap: 16 }}>
            <Recon label={fixture?.label || "Reconstruction from public reporting"} />
            <details>
              <summary className="tag tag-sm muted" style={{ cursor: "pointer" }}>Sources ↗</summary>
              <ul style={{ margin: "8px 0 0", paddingLeft: 18, fontSize: 13 }}>
                {(fixture?.sources || []).map((s) => <li key={s}><a href={s} target="_blank" rel="noreferrer">{s}</a></li>)}
              </ul>
            </details>
          </div>
          <div className="wrap-row" style={{ gap: 48, alignItems: "stretch" }}>
            <div className="stack" style={{ flex: "1 1 520px", gap: 36 }}>
              <h2 id="hook-h" className="h2" style={{ fontSize: 64 }}>
                {fixture ? `${fixture.event.split(":")[0]}. One unit error. ${compact(ghost)} ghost shares.` : "Loading the reconstruction…"}
              </h2>
              <ol style={{ listStyle: "none", margin: 0, padding: 0 }}>
                <Fact n="01">Declared: <span className="tok">{declared ? `${num(declared.value)} ${declared.unit}` : "…"}</span>, cash</Fact>
                <Fact n="02">Entered: <span className="tok">{entered ? `${num(entered.value)} ${entered.unit}` : "…"}</span></Fact>
                <Fact n="03" last>Approved by a reviewer, then credited to <span className="tok">{accounts ? num(accounts.value) : "…"}</span> accounts</Fact>
              </ol>
              <span className="tag tag-sm" style={{ color: "#98A2B3", whiteSpace: "normal" }}>Facts load from the fixture file, never typed into the UI</span>
            </div>
            <div className="stack" style={{ flex: "1 1 440px", background: "#121A2B", border: "1px solid rgba(255,255,255,0.12)", borderRadius: 6, padding: 32, gap: 20, boxShadow: "0 0 0 6px rgba(255,107,118,0.10)" }}>
              <div className="between"><span className="tag tag-sm"><span className="sq" />Router output</span>{div02 && <span className="chip chip-crit">● Critical</span>}</div>
              <span className="mono" style={{ fontSize: 120, lineHeight: "120px", letterSpacing: "-0.04em" }}>{multiple ? `${multiple}×` : "—"}</span>
              <p style={{ margin: 0, fontSize: 22, lineHeight: "30px" }}>{div02 ? replay.review_packet?.consequence || div02.message : "The pipeline's verdict appears here once the replay has run."}</p>
              {div02 && <div className="wrap-row" style={{ gap: 8 }}>{replay.tracks[0].rule_results.filter((r) => r.status === "fail").map((r) => <span key={r.rule_id} className="chip chip-crit">{r.rule_id}</span>)}</div>}
              <div className="wrap-row" style={{ marginTop: "auto", paddingTop: 20, borderTop: "1px solid rgba(255,255,255,0.12)", justifyContent: "space-between", gap: 16 }}>
                <span style={{ fontSize: 14, color: "#D0D5DD" }}>{div02 ? `Route: ${replay.route}` : "Shown after the replay has run"}</span>
                <button type="button" className="cta cta-lg" onClick={runReplay} disabled={running}>{running ? "Running…" : div02 ? "Open the review" : "Run the replay"}<span className="box"><Arrow size={16} /></span></button>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* CATCHES */}
      <section aria-labelledby="catch-h">
        <div className="wrap wrap-row" style={{ paddingTop: 112, paddingBottom: 112, gap: 48, alignItems: "flex-start" }}>
          <div className="stack" style={{ flex: "1 1 320px", maxWidth: 420, gap: 24 }}>
            <span className="tag"><span className="sq" />What it catches</span>
            <h2 id="catch-h" className="h2">Four errors that never reach the ledger.</h2>
          </div>
          <nav aria-label="Error classes" className="stack" style={{ flex: "999 1 560px" }}>
            {CATCHES.map(([text, rule], i) => (
              <a key={rule} className="catch" href="#/review" style={i === CATCHES.length - 1 ? { borderBottom: "1px solid rgba(255,255,255,0.28)" } : undefined}>
                <span className="row" style={{ alignItems: "baseline", gap: 28 }}><span className="mono" style={{ fontSize: 13, color: "#8FB0E3" }}>{rule}</span><span style={{ fontSize: 34, lineHeight: "40px", letterSpacing: "-0.03em" }}>{text}</span></span>
                <span className="arrowbox"><Arrow size={16} /></span>
              </a>
            ))}
          </nav>
        </div>
      </section>

      {/* CLOSING CTA */}
      <section aria-labelledby="cta-h" style={{ borderTop: "1px solid rgba(255,255,255,0.2)" }}>
        <div className="wrap stack" style={{ paddingTop: 120, paddingBottom: 120, alignItems: "center", gap: 36, textAlign: "center" }}>
          <span className="tag"><span className="sq" />Run it</span>
          <h2 id="cta-h" className="display" style={{ maxWidth: 900 }}>See every document's journey.</h2>
          <div className="wrap-row" style={{ justifyContent: "center", gap: 12 }}>
            <button type="button" className="cta cta-lg" onClick={() => start("csv")}>Run CSV batch<span className="box"><Arrow size={16} /></span></button>
            <button type="button" className="ghost" onClick={() => start("manifest")}>Run real filings</button>
            <button type="button" className="ghost" onClick={runReplay} disabled={running}>Replay Samsung</button>
          </div>
        </div>
      </section>

      <footer style={{ background: "#0B1220", color: "rgba(255,255,255,0.78)" }}>
        <div className="wrap stack" style={{ paddingTop: 72, paddingBottom: 40, gap: 56 }}>
          <div className="wrap-row" style={{ justifyContent: "space-between", gap: 48, alignItems: "flex-start" }}>
            <div className="stack" style={{ flex: "1 1 280px", gap: 16 }}>
              <span className="logo"><Logo dim="#4A78C9" />GhostStop</span>
              <span style={{ fontSize: 15, lineHeight: "22px", maxWidth: 300 }}>Validation and escalation for PSX corporate filings.</span>
            </div>
            <nav aria-label="Product" className="stack" style={{ flex: "0 1 180px", gap: 12 }}>
              <span className="tag tag-sm" style={{ color: "#98A2B3" }}>Product</span>
              {[["Overview", "#/"], ["Pipeline", "#/pipeline"], ["Review", "#/review"], ["Metrics", "#/metrics"], ["LLM log", "#/llm-log"]].map(([l, h]) => <a key={l} className="flink" href={h}>{l}</a>)}
            </nav>
            <div className="stack" style={{ flex: "0 1 220px", gap: 12, fontSize: 15 }}>
              <span className="tag tag-sm" style={{ color: "#98A2B3" }}>Data sources</span>
              <span>ps01</span><span>ps07</span><span>PSX filings</span><span>PSX Rule Book</span><span>Companies Act 2017</span>
            </div>
          </div>
          <div className="wrap-row mono" style={{ justifyContent: "space-between", gap: 12, paddingTop: 24, borderTop: "1px solid rgba(255,255,255,0.12)", fontSize: 12, letterSpacing: "0.04em", textTransform: "uppercase", color: "#98A2B3" }}>
            <span>Built for the atomcamp National AI Hackathon · PS-13</span>
            <span>API · {API}</span>
          </div>
        </div>
      </footer>
    </div>
  );
}

const fixtureId = () => "FIX-SAMSUNG-2018";

function Mini({ label, value }) {
  return <div className="mini"><span className="tag" style={{ fontSize: 11, whiteSpace: "normal" }}>{label}</span><span className="num">{value}</span></div>;
}

function Tile({ n, title, text }) {
  return (
    <div className="tile" style={{ minHeight: 280 }}>
      <span className="tag muted">[ {n} ]</span>
      <span style={{ fontSize: 44, lineHeight: "48px", letterSpacing: "-0.03em", marginTop: "auto" }}>{title}</span>
      <span className="muted" style={{ fontSize: 16, lineHeight: "24px" }}>{text}</span>
    </div>
  );
}

function Fact({ n, children, last }) {
  return (
    <li className="row" style={{ gap: 20, padding: "18px 0", borderTop: "1px solid rgba(255,255,255,0.18)", borderBottom: last ? "1px solid rgba(255,255,255,0.18)" : undefined, alignItems: "baseline" }}>
      <span className="mono" style={{ color: "#8FB0E3", fontSize: 13 }}>{n}</span>
      <span style={{ fontSize: 17, lineHeight: "26px", color: "#E4E7EC" }}>{children}</span>
    </li>
  );
}

function GateGraphic() {
  const sq = (x, y, o, key) => <rect key={key} x={x} y={y} width="16" height="16" fill="#FFFFFF" fillOpacity={o} />;
  const inbound = [0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 1, 1, 1].map((o, i) => sq(6 + i * 28, 202, o, `in${i}`));
  const out = [1, 1, 0.85, 0.7, 0.55, 0.4, 0.28, 0.18].map((o, i) => sq(314 + i * 28, 202, o, `out${i}`));
  const ghosts = [[258.5, 146.5], [230.5, 146.5], [202.5, 146.5], [258.5, 118.5], [230.5, 118.5], [258.5, 90.5]];
  return (
    <svg role="img" aria-label="Documents flow through a validation gate; ghost shares are stopped and escalated" width="560" height="440" viewBox="0 0 560 440" fill="none"
         style={{ position: "absolute", top: 0, left: "50%", marginLeft: -150, maxWidth: "70%", height: "auto" }}>
      <defs><pattern id="gs-grid" width="28" height="28" patternUnits="userSpaceOnUse"><rect x="6" y="6" width="16" height="16" fill="#FFFFFF" fillOpacity="0.07" /></pattern></defs>
      <rect x="0" y="0" width="560" height="420" fill="url(#gs-grid)" />
      {inbound}{out}
      {ghosts.map(([x, y]) => <rect key={`g${x}${y}`} x={x} y={y} width="15" height="15" stroke="#FFC98A" strokeDasharray="3 2" />)}
      <path d="M281 20 V400" stroke="#FFFFFF" strokeWidth="2" />
      <rect x="276" y="196" width="10" height="28" fill="#FFFFFF" />
      {[[286, 258, 1], [286, 286, 0.75], [286, 314, 0.5], [314, 314, 0.35]].map(([x, y, o]) => <rect key={`e${x}${y}`} x={x} y={y} width="16" height="16" fill="#FFC98A" fillOpacity={o} />)}
      <text x="6" y="250" fill="#FFFFFF" fontFamily="IBM Plex Mono, monospace" fontSize="11" letterSpacing="0.6">INTAKE...</text>
      <text x="292" y="32" fill="#FFFFFF" fontFamily="IBM Plex Mono, monospace" fontSize="11" letterSpacing="0.6">VALIDATE...</text>
      <text x="120" y="84" fill="#FFC98A" fontFamily="IBM Plex Mono, monospace" fontSize="11" letterSpacing="0.6">DIV-02 ✕ BLOCKED</text>
      <text x="342" y="327" fill="#FFC98A" fontFamily="IBM Plex Mono, monospace" fontSize="11" letterSpacing="0.6">ESCALATE...</text>
      <text x="454" y="250" fill="#D6E2F7" fontFamily="IBM Plex Mono, monospace" fontSize="11" letterSpacing="0.6">LEDGER...</text>
    </svg>
  );
}

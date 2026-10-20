// Pipeline board: one batch, its documents in stage columns (polled), and the live audit feed (SSE).
import { useEffect, useMemo, useState } from "react";
import { get, post, streamUrl } from "../api.js";
import { clock, methodKind, num, offset, short } from "../format.js";
import { BATCHES } from "../components/Header.jsx";
import { MethodBadge, RuleChip, Traces } from "../components/ui.jsx";

const COLUMNS = [
  { key: "queued", label: "Queued", statuses: ["queued", "intake"], color: "#8FB0E3" },
  { key: "classified", label: "Classified", statuses: ["classified"], color: "#FFFFFF" },
  { key: "extracting", label: "Extracting", statuses: ["extracting"], color: "#FFFFFF" },
  { key: "validating", label: "Validating", statuses: ["validating"], color: "#FFFFFF" },
  { key: "review", label: "Needs review", statuses: ["needs_review"], color: "#FFB45C", amber: true },
  { key: "done", label: "Done", statuses: ["done"], color: "#5EE0A8" },
  { key: "archived", label: "Archived", statuses: ["archived"], color: "#8FB0E3", muted: true },
  { key: "duplicate", label: "Duplicate", statuses: ["duplicate"], color: "#8FB0E3", muted: true },
  { key: "rejected", label: "Rejected", statuses: ["rejected"], color: "#FF6B76", muted: true },
];
const CARD_LIMIT = 60;

export default function Pipeline({ batchId, onError }) {
  const [batches, setBatches] = useState(null);
  const [batch, setBatch] = useState(null);
  const [events, setEvents] = useState([]);
  const [streamState, setStreamState] = useState("idle");
  const [method, setMethod] = useState("all");
  const [source, setSource] = useState("all");
  const [expanded, setExpanded] = useState({});
  const [now, setNow] = useState(Date.now());

  // Which batch: the one in the URL, else the most recent one.
  useEffect(() => { get("/batches").then(setBatches).catch((e) => onError(e.message)); }, [batchId]);
  const id = batchId || (batches && batches.length ? batches[batches.length - 1].batch_id : null);

  // Poll the batch while it runs (document statuses), stop when done.
  useEffect(() => {
    if (!id) return;
    let alive = true, timer;
    const load = async () => {
      try {
        const b = await get(`/batch/${id}`);
        if (!alive) return;
        setBatch(b);
        if (b.status === "running") timer = setTimeout(load, 900);
      } catch (e) { onError(e.message); }
    };
    setBatch(null); setEvents([]); setExpanded({});
    load();
    return () => { alive = false; clearTimeout(timer); };
  }, [id]);

  // Live audit feed over Server-Sent Events.
  useEffect(() => {
    if (!id) return;
    const es = new EventSource(streamUrl(id));
    setStreamState("live");
    es.addEventListener("audit", (e) => setEvents((prev) => [...prev.slice(-400), JSON.parse(e.data)]));
    es.addEventListener("done", () => { setStreamState("complete"); es.close(); });
    es.onerror = () => { setStreamState((s) => (s === "complete" ? s : "reconnecting")); };
    return () => es.close();
  }, [id]);

  useEffect(() => {
    if (batch?.status !== "running") return;
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, [batch?.status]);

  const docs = useMemo(() => (batch?.documents || []).filter((d) => {
    if (source !== "all" && !d.source.startsWith(source === "csv" ? "csv" : source)) return false;
    if (method === "human") return d.human_reviewed;
    if (method !== "all" && methodKind(d.doc_type_method) !== method) return false;
    return true;
  }), [batch, method, source]);

  if (batches && !id) return <EmptyState />;
  if (!batch) return <div className="wrap" style={{ padding: "80px 40px" }}><span className="tag">Loading batch…</span></div>;

  const all = batch.documents;
  const routed = all.filter((d) => d.route).length;
  const progress = all.length ? Math.round((routed / all.length) * 100) : 0;
  const count = (route) => all.filter((d) => d.route === route).length;
  const elapsed = (batch.finished_at ? new Date(batch.finished_at).getTime() : now) - new Date(batch.started_at).getTime();
  const byCol = Object.fromEntries(COLUMNS.map((c) => [c.key, docs.filter((d) => c.statuses.includes(d.status))]));

  return (
    <>
      <section style={{ position: "relative" }}>
        <Traces style={{ top: -60, right: -40 }} />
        <div className="wrap stack" style={{ paddingTop: 40, paddingBottom: 48, gap: 36, position: "relative" }}>
          <div className="stack" style={{ gap: 20 }}>
            <span className="tag"><span className="sq" />Pipeline · {batch.status === "running" ? "Live" : "Complete"}</span>
            <div className="wrap-row" style={{ alignItems: "flex-end", justifyContent: "space-between", gap: 24 }}>
              <h1 className="h1">Pipeline board</h1>
              <dl className="mono" style={{ margin: 0, display: "grid", gridTemplateColumns: "auto auto", gap: "6px 20px", fontSize: 13, lineHeight: "18px", textTransform: "uppercase", letterSpacing: "0.04em" }}>
                <dt className="muted">Batch</dt>
                <dd style={{ margin: 0 }}>
                  <select className="input" style={{ height: 28, fontSize: 12, padding: "0 6px" }} value={id}
                          onChange={(e) => { window.location.hash = `#/pipeline/${e.target.value}`; }}>
                    {(batches || []).slice().reverse().map((b) => <option key={b.batch_id} value={b.batch_id}>{b.batch_id} · {b.source}</option>)}
                  </select>
                </dd>
                <dt className="muted">Source</dt><dd style={{ margin: 0, fontWeight: 500 }}>{batch.source}</dd>
                <dt className="muted">Elapsed</dt><dd style={{ margin: 0, fontWeight: 500 }}>{clock(elapsed)}</dd>
                <dt className="muted">Stream</dt>
                <dd style={{ margin: 0, fontWeight: 500 }} className="row">
                  <span className="dot" style={{ background: streamState === "live" ? "#5EE0A8" : streamState === "complete" ? "#8FB0E3" : "#FFC98A" }} />{streamState}
                </dd>
              </dl>
            </div>
          </div>

          <div className="stack" style={{ gap: 12 }}>
            <div className="between mono" style={{ fontSize: 13, letterSpacing: "0.04em", textTransform: "uppercase" }}>
              <span><b style={{ fontWeight: 500 }}>{routed} / {all.length}</b> <span className="muted">documents processed</span></span>
              <span style={{ fontWeight: 500 }}>{progress}%</span>
            </div>
            <div className="progress" role="progressbar" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100}><div style={{ width: `${progress}%` }} /></div>
          </div>

          <div className="wrap-row" style={{ gap: 32, alignItems: "stretch" }}>
            <div className="stat"><span className="statlbl">Auto-approved</span><span className="statnum">{count("auto_approve")}</span><span className="statcap">Routed or written to ledger, no human touch</span></div>
            <div className="stat stat-amber"><span className="statlbl">Needs review</span><span className="statnum">{count("needs_review")}</span><span className="statcap">Blocked from ledger until approved</span></div>
            <div className="stat"><span className="statlbl">Archived</span><span className="statnum">{count("archive")}</span><span className="statcap">Admin noise, extraction skipped</span></div>
            <div className="stat"><span className="statlbl">Duplicates</span><span className="statnum">{count("duplicate")}</span><span className="statcap">Held and linked to the original</span></div>
          </div>
        </div>
      </section>

      <section>
        <div className="wrap wrap-row" style={{ paddingBottom: 56, gap: 24, alignItems: "flex-start" }}>
          <div className="stack" style={{ flex: "999 1 640px", minWidth: 0, gap: 20 }}>
            <div className="wrap-row" style={{ justifyContent: "space-between", gap: 12 }}>
              <Filter label="Method" value={method} onChange={setMethod}
                      options={[["all", "All"], ["classical", "Classical"], ["llm", "LLM"], ["human", "Human"]]} />
              <Filter label="Source" value={source} onChange={setSource}
                      options={[["all", "All"], ["csv", "csv"], ["manifest", "manifest"], ["fixture", "fixture"], ["upload", "upload"]]} />
            </div>

            <nav aria-label="Jump to stage" className="rail">
              {COLUMNS.map((c, i) => (
                <span key={c.key} className="row" style={{ gap: 12 }}>
                  <button type="button" className="stagelink" style={c.amber ? { color: "#FFC98A" } : undefined}
                          onClick={() => document.getElementById(`col-${c.key}`)?.scrollIntoView({ behavior: "smooth", inline: "start", block: "nearest" })}>
                    {c.label} {byCol[c.key].length}
                  </button>
                  {i < COLUMNS.length - 1 && <span className="sep" aria-hidden="true">{i < 4 ? "→" : "/"}</span>}
                </span>
              ))}
            </nav>

            <div className="columns">
              {COLUMNS.map((c) => {
                const list = byCol[c.key];
                const shown = list.slice(0, expanded[c.key] ? CARD_LIMIT : 3);
                return (
                  <section key={c.key} id={`col-${c.key}`} className={`col ${c.amber ? "col-amber" : ""}`} aria-label={c.label}>
                    <div className="colhead" style={c.amber ? { color: "#FFC98A" } : undefined}>
                      <span className="row"><span className="dot" style={{ background: c.color }} />{c.label}</span><span>{list.length}</span>
                    </div>
                    {list.length === 0 && <span className="empty">Nothing here</span>}
                    {shown.map((d) => <DocCard key={d.doc_id} doc={d} column={c} />)}
                    {list.length > shown.length && !expanded[c.key] && (
                      <button type="button" className="more" onClick={() => setExpanded((x) => ({ ...x, [c.key]: true }))}>
                        and {list.length - shown.length} more
                      </button>
                    )}
                    {expanded[c.key] && list.length > CARD_LIMIT && <span className="empty">Showing {CARD_LIMIT} of {list.length}</span>}
                  </section>
                );
              })}
            </div>
            <div className="between mono" style={{ fontSize: 12, letterSpacing: "0.06em", textTransform: "uppercase", color: "#D6E2F7" }}>
              <span>{all.length} documents · live from the API</span><span style={{ color: "#FFFFFF" }}>Scroll →</span>
            </div>
          </div>

          <AuditFeed events={events} start={batch.started_at} streamState={streamState} />
        </div>
      </section>
    </>
  );
}

function Filter({ label, value, onChange, options }) {
  return (
    <div className="wrap-row" style={{ gap: 12 }}>
      <span className="tag tag-sm muted">{label}</span>
      <div className="pillgroup" role="group" aria-label={`${label} filter`}>
        {options.map(([v, l]) => (
          <button key={v} type="button" className={`pill pill-sm ${value === v ? "pill-on" : ""}`} aria-pressed={value === v} onClick={() => onChange(v)}>{l}</button>
        ))}
      </div>
    </div>
  );
}

function DocCard({ doc, column }) {
  const critical = doc.failed_rules.filter((r) => r.severity === "critical");
  const warnings = doc.failed_rules.filter((r) => r.severity === "warning");
  const chips = [...critical, ...warnings];
  const conf = doc.doc_type_confidence;
  const href = doc.route === "needs_review" ? `#/review/${doc.doc_id}` : `#/doc/${doc.doc_id}`;
  const dot = critical.length ? "#FF6B76" : doc.route === "needs_review" ? "#FFB45C" : column.color;
  return (
    <a className={`card ${column.muted ? "card-muted" : ""}`} href={href} title={doc.filename}>
      <div className="row"><span className="dot" style={{ background: dot }} /><span className="fname">{short(doc.filename.split("/").pop(), 28)}</span></div>
      <div className="dtype">
        {doc.duplicate_of ? <>Held · links <span className="mono">{doc.duplicate_of}</span></>
          : doc.doc_type ? `${doc.doc_type}${column.key === "archived" ? " · admin" : ""}` : "Awaiting intake"}
      </div>
      <div className="between">
        {doc.doc_type ? <MethodBadge method={doc.human_reviewed ? "human" : doc.doc_type_method} /> : <span className="chip chip-neutral">{doc.source.replace("csv_", "")}</span>}
        <span className="conf">{doc.doc_type ? conf.toFixed(2) : "—"}</span>
      </div>
      {doc.doc_type && <div className="bar"><span style={{ width: `${Math.round(conf * 100)}%`, background: conf < 0.8 ? "#FFC98A" : column.key === "done" ? "#5EE0A8" : column.muted ? "#8FB0E3" : "#FFFFFF" }} /></div>}
      {(chips.length > 0 || doc.tracks > 1 || doc.label || doc.resolver_loops > 0) && (
        <div className="wrap-row" style={{ gap: 6 }}>
          {chips.slice(0, 2).map((r) => <RuleChip key={r.rule_id} rule={r.rule_id} severity={r.severity} />)}
          {chips.length > 2 && <span className="chip chip-crit">+{chips.length - 2}</span>}
          {doc.tracks > 1 && <span className="chip chip-neutral">{doc.tracks} tracks</span>}
          {doc.resolver_loops > 0 && <span className="chip chip-warn">Resolver {doc.resolver_loops}/2</span>}
          {doc.label && <span className="chip" style={{ border: "1px solid #FFC98A", color: "#FFC98A" }}>Reconstruction</span>}
        </div>
      )}
    </a>
  );
}

function AuditFeed({ events, start, streamState }) {
  const latest = events.slice(-50).reverse();
  return (
    <aside className="feed" aria-label="Live audit feed">
      <div className="stack" style={{ padding: 18, gap: 10 }}>
        <div className="between">
          <span className="tag tag-sm"><span className="sq" />Audit</span>
          <span className="tag tag-sm" style={{ color: streamState === "live" ? "#5EE0A8" : "#D6E2F7" }}>
            <span className="dot" style={{ background: streamState === "live" ? "#5EE0A8" : "#8FB0E3" }} />{streamState === "live" ? "Live" : "Replayed"}
          </span>
        </div>
        <h2 style={{ margin: 0, fontSize: 24, lineHeight: "30px", fontWeight: 400, letterSpacing: "-0.02em" }}>Live audit feed</h2>
        <span style={{ fontSize: 13 }} className="muted">Newest first · last 50 of {num(events.length)} events</span>
      </div>
      <ol>
        {latest.length === 0 && <li className="feedrow"><span className="dec">Waiting for events…</span></li>}
        {latest.map((e, i) => (
          <li key={`${e.started_at}-${i}`} className={`feedrow ${e.status === "error" ? "feedrow-error" : e.status === "warning" ? "feedrow-warn" : ""}`}>
            <div className="between"><span className="time">{offset(e.started_at, start)}</span><span className="ms">{e.duration_ms ? `${num(e.duration_ms, 0)} ms` : "—"}</span></div>
            <div className="between"><span className="agent">{e.agent}</span><MethodBadge method={e.method} /></div>
            <span className="dec"><a href={`#/doc/${e.doc_id}`} className="mono" style={{ color: "#FFFFFF" }}>{e.doc_id}</a> · {e.stage} · {short(e.decision, 160)}</span>
          </li>
        ))}
      </ol>
    </aside>
  );
}

function EmptyState() {
  return (
    <section className="wrap stack" style={{ paddingTop: 64, paddingBottom: 96, gap: 24 }}>
      <span className="tag"><span className="sq" />Pipeline</span>
      <h1 className="h1">No batch has run yet.</h1>
      <p className="lead" style={{ maxWidth: 560 }}>Start one with the Run batch button. Every card on this board comes from the live pipeline.</p>
      <div className="wrap-row" style={{ gap: 12 }}>
        {BATCHES.map(([source, label]) => <StartButton key={source} source={source} label={label} />)}
      </div>
    </section>
  );
}

function StartButton({ source, label }) {
  const start = async () => {
    const { batch_id } = await post("/batch", { source });
    window.location.hash = `#/pipeline/${batch_id}`;
  };
  return <button type="button" className="ghost" onClick={start}>{label}</button>;
}

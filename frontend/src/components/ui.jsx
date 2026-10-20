// Shared visual pieces from the mockups: logo, arrow icon, method badge, rule chips, reconstruction badge.
import { methodKind, methodLabel } from "../format.js";

export function Logo({ dim = "#8FB0E3" }) {
  const cells = [[0, 0, 1], [8, 0, 1], [16, 0, 0], [0, 8, 1], [8, 8, 0], [16, 8, 1], [0, 16, 0], [8, 16, 1], [16, 16, 1]];
  return (
    <svg width="22" height="22" viewBox="0 0 20 20" aria-hidden="true">
      {cells.map(([x, y, on]) => <rect key={`${x}-${y}`} x={x} y={y} width="4" height="4" fill={on ? "#FFFFFF" : dim} />)}
    </svg>
  );
}

export function Arrow({ size = 14 }) {
  const px = [[6, 2], [8, 2], [10, 2], [10, 4], [10, 6], [8, 4], [6, 6], [4, 8], [2, 10]];
  return (
    <svg width={size} height={size} viewBox="0 0 14 14" aria-hidden="true" fill="#FFFFFF">
      {px.map(([x, y]) => <rect key={`${x}-${y}`} x={x} y={y} width="2" height="2" />)}
    </svg>
  );
}

export function MethodBadge({ method }) {
  const kind = methodKind(method);
  const cls = { llm: "b-llm", human: "b-human", none: "b-none", classical: "b-classical" }[kind];
  return <span className={`badge ${cls}`}>{methodLabel(method)}</span>;
}

export function RuleChip({ rule, severity }) {
  const cls = severity === "critical" ? "chip-crit" : severity === "warning" ? "chip-warn" : "chip-na";
  return <span className={`chip ${cls}`}>{rule}</span>;
}

export function StatusChip({ status }) {
  const cls = { pass: "chip-ok", fail: "chip-crit", not_applicable: "chip-na" }[status] || "chip-na";
  return <span className={`chip ${cls}`}>{status === "not_applicable" ? "n/a" : status}</span>;
}

export function Recon({ label }) {
  if (!label) return null;
  return (
    <span className="recon">
      <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d="M12 3l9 16H3z" /><path d="M12 10v4M12 17h.01" />
      </svg>
      {label}
    </span>
  );
}

export function Traces({ style, width = 900, height = 520 }) {
  return (
    <svg className="traces" aria-hidden="true" width={width} height={height} viewBox="0 0 900 520" fill="none" style={style}>
      <path d="M0 470 H250 Q270 470 270 450 V250 Q270 230 290 230 H640 Q660 230 660 250 V330 Q660 350 680 350 H780 Q800 350 800 330 V60 Q800 40 820 40 H900" stroke="#FFFFFF" strokeOpacity="0.32" />
      <path d="M30 490 H280 Q300 490 300 470 V270 Q300 250 320 250 H610 Q630 250 630 270 V350 Q630 370 650 370 H810 Q830 370 830 350 V90 Q830 70 850 70 H900" stroke="#FFFFFF" strokeOpacity="0.14" />
      <path d="M640 230 H560" stroke="#FFFFFF" strokeOpacity="0.9" strokeWidth="1.5" />
    </svg>
  );
}

export function Toast({ message, onClose }) {
  if (!message) return null;
  return <div className="toast" role="alert" onClick={onClose}>{message}</div>;
}

import { useState, type PointerEvent, type ReactNode } from "react";

/** Hand-drawn SVG charts. Colors come from the theme tokens, so each chart follows light and dark automatically. */
export const SERIES = { blue: "var(--chart-1)", amber: "var(--chart-2)", green: "var(--chart-3)", grey: "var(--chart-4)" };

export interface Series {
  name: string;
  values: number[];
  color: string;
}

interface TipState {
  x: number;
  y: number;
  title: string;
  rows: { name: string; value: string; color?: string }[];
}

function useTip() {
  const [tip, setTip] = useState<TipState | null>(null);
  const bind = (title: string, rows: TipState["rows"]) => ({
    onPointerMove: (e: PointerEvent) => setTip({ x: e.clientX, y: e.clientY, title, rows }),
    onPointerLeave: () => setTip(null),
  });
  const node = tip && (
    <div className="chart-tip" style={{ left: Math.min(tip.x + 14, window.innerWidth - 190), top: Math.max(8, tip.y - 60) }}>
      <div className="chart-tip-title">{tip.title}</div>
      {tip.rows.map((r) => (
        <div className="chart-tip-row" key={r.name}>
          {r.color && <i style={{ background: r.color }} />}
          <span>{r.name}</span>
          <b>{r.value}</b>
        </div>
      ))}
    </div>
  );
  return { bind, node };
}

/** The same numbers as a table for screen readers: a chart alone says nothing to them. */
function ChartTable({ caption, labels, series, format }: { caption: string; labels: string[]; series: Series[]; format: (v: number) => string }) {
  return (
    <table className="sr-only">
      <caption>{caption}</caption>
      <thead>
        <tr><th>Period</th>{series.map((s) => <th key={s.name}>{s.name}</th>)}</tr>
      </thead>
      <tbody>
        {labels.map((label, i) => (
          <tr key={label}><td>{label}</td>{series.map((s) => <td key={s.name}>{format(s.values[i] ?? 0)}</td>)}</tr>
        ))}
      </tbody>
    </table>
  );
}

const identity = (v: number) => String(v);

/** Bar with rounded top corners and a square foot, so it stands on the baseline. */
function barPath(x: number, y: number, w: number, h: number) {
  const r = Math.min(4, w / 2, h);
  return `M${x} ${y + h}V${y + r}Q${x} ${y} ${x + r} ${y}H${x + w - r}Q${x + w} ${y} ${x + w} ${y + r}V${y + h}Z`;
}

/** Daily counts as side-by-side bars. Counts are separate days, often zero, so nothing is drawn between days. */
export function TrendBars({ title, series, labels, format = identity }: { title: string; series: Series[]; labels: string[]; format?: (v: number) => string }) {
  const { bind, node } = useTip();
  const [hover, setHover] = useState<number | null>(null);
  const W = 760, H = 250, L = 30, R = 6, T = 12, B = 28;
  const n = labels.length;
  const top = Math.max(Math.ceil(Math.max(1, ...series.flatMap((s) => s.values)) / 4) * 4, 4);
  const plotH = H - T - B;
  const slot = (W - L - R) / n;
  const gap = 2;
  const barW = Math.min(20, Math.max(3, (slot * 0.74 - gap * (series.length - 1)) / series.length));
  const groupW = barW * series.length + gap * (series.length - 1);
  const Y = (v: number) => T + plotH - (v / top) * plotH;
  const step = Math.ceil(n / 7);
  return (
    <div className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={title}>
        {[0, 0.25, 0.5, 0.75, 1].map((f) => {
          const v = top * f;
          return (
            <g key={f}>
              <line className="chart-grid" x1={L} x2={W - R} y1={Y(v)} y2={Y(v)} />
              <text className="chart-text" x={L - 8} y={Y(v) + 4} textAnchor="end">{v}</text>
            </g>
          );
        })}
        {labels.map((label, i) => {
          if ((n - 1 - i) % step !== 0) return null;
          const last = i === n - 1;
          return <text key={label} className="chart-text" x={last ? W - R : L + i * slot + slot / 2} y={H - 8} textAnchor={last ? "end" : "middle"}>{label}</text>;
        })}
        {labels.map((label, i) => {
          const start = L + i * slot + (slot - groupW) / 2;
          const { onPointerMove, onPointerLeave } = bind(label, series.map((s) => ({ name: s.name, value: format(s.values[i] ?? 0), color: s.color })));
          return (
            <g key={label} className="trend-day" onPointerMove={(e) => { setHover(i); onPointerMove(e); }} onPointerLeave={() => { setHover(null); onPointerLeave(); }}>
              <rect x={L + i * slot} y={T} width={slot} height={plotH} fill={hover === i ? "var(--surface-3)" : "transparent"} opacity={0.6} rx={4} />
              {series.map((s, k) => {
                const v = s.values[i] ?? 0;
                if (!v) return null;
                const h = Math.max(3, (v / top) * plotH);
                return <path key={s.name} d={barPath(start + k * (barW + gap), T + plotH - h, barW, h)} fill={s.color} />;
              })}
            </g>
          );
        })}
      </svg>
      {series.length > 1 && (
        <div className="chart-legend">
          {series.map((s) => (
            <span key={s.name}><i className="chart-key" style={{ background: s.color }} />{s.name}<b>{format(s.values.reduce((sum, v) => sum + v, 0))}</b></span>
          ))}
        </div>
      )}
      <ChartTable caption={title} labels={labels} series={series} format={format} />
      {node}
    </div>
  );
}

export function HBars({ rows, color = SERIES.blue, empty = "Nothing in this period yet." }: {
  rows: { label: string; value: number; text?: string }[];
  color?: string;
  empty?: string;
}) {
  const { bind, node } = useTip();
  if (!rows.length || rows.every((r) => !r.value)) return <p className="muted small">{empty}</p>;
  const top = Math.max(...rows.map((r) => r.value), 1);
  return (
    <div>
      {rows.map((r) => (
        <div className="hbar" key={r.label} {...bind(r.label, [{ name: "Value", value: r.text ?? String(r.value) }])}>
          <span className="hbar-label" title={r.label}>{r.label}</span>
          <span className="hbar-track"><i style={{ width: `${Math.max(3, (r.value / top) * 100)}%`, background: color }} /></span>
          <b>{r.text ?? r.value}</b>
        </div>
      ))}
      {node}
    </div>
  );
}

export function Donut({ title, center, centerLabel, parts }: {
  title: string;
  center: ReactNode;
  centerLabel: string;
  parts: { label: string; value: number; color: string }[];
}) {
  const { bind, node } = useTip();
  const total = parts.reduce((sum, p) => sum + p.value, 0);
  const circumference = 2 * Math.PI * 44;
  const shown = parts.filter((p) => p.value > 0);
  const gap = shown.length > 1 ? 3 : 0; // a single full ring has no segments to separate
  let offset = 0;
  return (
    <div className="donut">
      <svg width={124} height={124} viewBox="0 0 124 124" role="img" aria-label={title}>
        <circle cx={62} cy={62} r={44} fill="none" stroke="var(--border)" strokeWidth={17} />
        {total > 0 && shown.map((p) => {
          const length = (p.value / total) * circumference;
          const drawn = Math.max(length - gap, 1);
          const segment = (
            <circle key={p.label} cx={62} cy={62} r={44} fill="none" stroke={p.color} strokeWidth={17}
              strokeDasharray={`${drawn} ${circumference - drawn}`} strokeDashoffset={-offset} transform="rotate(-90 62 62)"
              {...bind(p.label, [{ name: "Orders", value: String(p.value) }])} />
          );
          offset += length;
          return segment;
        })}
        <text x={62} y={60} textAnchor="middle" fontSize={23} fontWeight={800} fill="var(--text)">{center}</text>
        <text className="chart-text" x={62} y={77} textAnchor="middle">{centerLabel}</text>
      </svg>
      <div className="donut-legend">
        {parts.map((p) => <div key={p.label}><i style={{ background: p.color }} />{p.label}<b>{p.value}</b></div>)}
      </div>
      {node}
    </div>
  );
}

export function Pipeline({ steps }: { steps: { label: string; value: number }[] }) {
  const first = steps[0]?.value ?? 0;
  if (!first) return <p className="muted small">No orders yet.</p>;
  return (
    <div className="pipeline">
      {steps.map((s, i) => {
        const previous = steps[i - 1]?.value;
        return (
          <div key={s.label}>
            <div className="pipeline-row"><span>{s.label}</span><b>{s.value}</b></div>
            <span className="pipeline-bar" style={{ width: `${Math.max(2, (s.value / first) * 100)}%`, opacity: 1 - i * 0.14 }} />
            {i > 0 && previous ? <small className="muted">{Math.round((s.value / previous) * 100)}% of previous step</small> : null}
          </div>
        );
      })}
    </div>
  );
}

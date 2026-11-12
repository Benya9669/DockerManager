import { useEffect, useMemo, useRef, useState } from "react";

// Categorical slots (dataviz reference palette, dark-surface steps), fixed order — never cycled.
export const SERIES = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181", "#008300", "#9085e9", "#e66767"];
const MAX_SERIES = SERIES.length;

export type Series = { name: string; points: [number, number][] }; // [unix ts, value]

const fmtTime = (ts: number, span: number) => {
  const d = new Date(ts * 1000);
  return span > 86400
    ? d.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })
    : d.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
};

function niceMax(v: number) {
  if (v <= 0) return 1;
  const p = Math.pow(10, Math.floor(Math.log10(v)));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p;
  return 10 * p;
}

/** Multi-series line chart: one y-axis, crosshair tooltip, legend with latest values. */
export function LineChart({ title, series, format, yMax, height = 180 }: {
  title: string; series: Series[]; format: (v: number) => string; yMax?: number; height?: number;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const [w, setW] = useState(600);
  const [hover, setHover] = useState<number | null>(null); // ts
  useEffect(() => {
    const ro = new ResizeObserver(([e]) => setW(Math.max(280, e.contentRect.width)));
    if (wrap.current) ro.observe(wrap.current);
    return () => ro.disconnect();
  }, []);

  // keep the 8 largest series by average, fold the rest into "Прочие" (sum) — no generated 9th hue
  const shown = useMemo(() => {
    const valid = series.filter((s) => s.points.length);
    if (valid.length <= MAX_SERIES) return valid;
    const avg = (s: Series) => s.points.reduce((a, p) => a + p[1], 0) / s.points.length;
    const sorted = [...valid].sort((a, b) => avg(b) - avg(a));
    const keep = sorted.slice(0, MAX_SERIES - 1);
    const rest = sorted.slice(MAX_SERIES - 1);
    const sum = new Map<number, number>();
    rest.forEach((s) => s.points.forEach(([t, v]) => sum.set(t, (sum.get(t) || 0) + v)));
    return [...keep, { name: `Прочие (${rest.length})`, points: [...sum.entries()].sort((a, b) => a[0] - b[0]) as [number, number][] }];
  }, [series]);

  const pad = { l: 64, r: 12, t: 8, b: 22 };
  const all = shown.flatMap((s) => s.points);
  if (!all.length) {
    return (
      <div className="card chart">
        <div className="chart-title">{title}</div>
        <div className="muted small pad">Нет данных — метрики собираются раз в несколько секунд, первые точки появятся скоро.</div>
      </div>
    );
  }
  const t0 = Math.min(...all.map((p) => p[0]));
  const t1 = Math.max(...all.map((p) => p[0]));
  const span = Math.max(t1 - t0, 1);
  const top = yMax ?? niceMax(Math.max(...all.map((p) => p[1])) * 1.1);
  const iw = w - pad.l - pad.r;
  const ih = height - pad.t - pad.b;
  const x = (t: number) => pad.l + ((t - t0) / span) * iw;
  const y = (v: number) => pad.t + ih - (Math.min(v, top) / top) * ih;
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((k) => k * top);
  const xticks = [0, 0.33, 0.66, 1].map((k) => t0 + k * span);

  const nearest = (s: Series, t: number) =>
    s.points.reduce((best, p) => (Math.abs(p[0] - t) < Math.abs(best[0] - t) ? p : best), s.points[0]);
  const hoverRows = hover != null ? shown.map((s, i) => ({ s, i, p: nearest(s, hover) })) : [];
  const tipLeft = hover != null && x(hover) > w * 0.6;

  return (
    <div className="card chart" ref={wrap}>
      <div className="chart-title">{title}</div>
      <div style={{ position: "relative" }}>
        <svg width={w} height={height} role="img" aria-label={title}
          onMouseMove={(e) => {
            const r = (e.currentTarget as SVGSVGElement).getBoundingClientRect();
            const px = e.clientX - r.left;
            if (px < pad.l || px > w - pad.r) return setHover(null);
            setHover(t0 + ((px - pad.l) / iw) * span);
          }}
          onMouseLeave={() => setHover(null)}>
          {ticks.map((v) => (
            <g key={v}>
              <line x1={pad.l} x2={w - pad.r} y1={y(v)} y2={y(v)} className="grid" />
              <text x={pad.l - 6} y={y(v)} className="axis" textAnchor="end" dominantBaseline="central">{format(v)}</text>
            </g>
          ))}
          {xticks.map((t, i) => (
            <text key={i} x={x(t)} y={height - 6} className="axis" textAnchor={i === 0 ? "start" : i === 3 ? "end" : "middle"}>
              {fmtTime(t, span)}
            </text>
          ))}
          {shown.map((s, i) => (
            <polyline key={s.name} fill="none" stroke={SERIES[i]} strokeWidth={2} strokeLinejoin="round" strokeLinecap="round"
              points={s.points.map(([t, v]) => `${x(t).toFixed(1)},${y(v).toFixed(1)}`).join(" ")} />
          ))}
          {hover != null && (
            <>
              <line x1={x(hover)} x2={x(hover)} y1={pad.t} y2={pad.t + ih} className="crosshair" />
              {hoverRows.map(({ s, i, p }) => (
                <circle key={s.name} cx={x(p[0])} cy={y(p[1])} r={4} fill={SERIES[i]} stroke="var(--panel)" strokeWidth={2} />
              ))}
            </>
          )}
        </svg>
        {hover != null && hoverRows.length > 0 && (
          <div className="chart-tip" style={tipLeft ? { right: w - x(hover) + 10 } : { left: x(hover) + 10 }}>
            <div className="muted small">{new Date(hoverRows[0].p[0] * 1000).toLocaleString("ru-RU")}</div>
            {hoverRows.map(({ s, i, p }) => (
              <div key={s.name} className="tip-row"><span className="swatch" style={{ background: SERIES[i] }} />{s.name}<b>{format(p[1])}</b></div>
            ))}
          </div>
        )}
      </div>
      {shown.length > 1 && (
        <div className="legend">
          {shown.map((s, i) => (
            <span key={s.name} className="legend-item">
              <span className="swatch" style={{ background: SERIES[i] }} />{s.name}
              <span className="muted">{format(s.points[s.points.length - 1][1])}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

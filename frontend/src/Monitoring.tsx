import { t, tf } from "./i18n";
import { useState } from "react";
import { api } from "./api";
import { LineChart, type Series } from "./Chart";
import { Loading, fmtBytes, useFetch } from "./ui";

const RANGES: [number, string][] = [[1, t("1 ч")], [6, t("6 ч")], [24, t("24 ч")]];
const pct = (v: number) => `${v.toFixed(v < 10 ? 1 : 0)}%`;
const rate = (v: number) => `${fmtBytes(v)}/s`;

function RangePicker({ hours, setHours }: { hours: number; setHours: (h: number) => void }) {
  return (
    <div className="row">
      {RANGES.map(([h, l]) => (
        <button key={h} className={`btn sm ${hours === h ? "primary" : ""}`} onClick={() => setHours(h)}>{l}</button>
      ))}
    </div>
  );
}

/** cumulative byte counters -> bytes/second */
function toRate(points: [number, number][]): [number, number][] {
  const out: [number, number][] = [];
  for (let i = 1; i < points.length; i++) {
    const dt = points[i][0] - points[i - 1][0];
    const dv = points[i][1] - points[i - 1][1];
    if (dt > 0) out.push([points[i][0], dv >= 0 ? dv / dt : 0]); // counter reset on restart -> 0
  }
  return out;
}

export function HostMonitoring() {
  const [hours, setHours] = useState(6);
  const m = useFetch<any>(() => api(`/metrics/host?hours=${hours}`), [hours], 30000);
  const pts: any[] = m.data?.points || [];
  const last = pts[pts.length - 1];
  return (
    <div className="stack">
      <div className="row between">
        <h3>{t("Нагрузка на сервер")}</h3>
        <RangePicker hours={hours} setHours={setHours} />
      </div>
      <Loading error={m.error} loading={m.loading && !m.data} />
      {m.data && (
        <div className="charts">
          <LineChart title={t("CPU сервера")} yMax={100} format={pct}
            series={[{ name: "CPU", points: pts.filter((p) => p.cpu != null).map((p) => [p.ts, p.cpu]) }]} />
          <LineChart title={last?.mem_total ? tf("Память сервера (всего {0})", fmtBytes(last.mem_total)) : t("Память сервера")}
            yMax={last?.mem_total || undefined} format={fmtBytes}
            series={[{ name: t("Занято"), points: pts.filter((p) => p.mem_total).map((p) => [p.ts, p.mem_used]) }]} />
          <LineChart title={last?.disk_total ? tf("Диск (всего {0})", fmtBytes(last.disk_total)) : t("Диск")}
            yMax={last?.disk_total || undefined} format={fmtBytes}
            series={[{ name: t("Занято"), points: pts.filter((p) => p.disk_total).map((p) => [p.ts, p.disk_used]) }]} />
        </div>
      )}
    </div>
  );
}

export function ProjectMonitoring({ projectId }: { projectId: number }) {
  const [hours, setHours] = useState(6);
  const m = useFetch<any>(() => api(`/metrics/projects/${projectId}?hours=${hours}`), [projectId, hours], 30000);
  const raw: any[] = m.data?.series || [];
  const cpu: Series[] = raw.map((s) => ({ name: s.name, points: s.points.map((p: number[]) => [p[0], p[1]]) }));
  const mem: Series[] = raw.map((s) => ({ name: s.name, points: s.points.map((p: number[]) => [p[0], p[2]]) }));
  const rx: Series[] = raw.map((s) => ({ name: s.name, points: toRate(s.points.map((p: number[]) => [p[0], p[4]])) }));
  const tx: Series[] = raw.map((s) => ({ name: s.name, points: toRate(s.points.map((p: number[]) => [p[0], p[5]])) }));
  return (
    <div className="stack">
      <div className="row between">
        <span className="muted small">{t("Сбор раз в")} {m.data?.interval ?? 30} {t("с, хранение по DM_METRICS_RETENTION_HOURS")}</span>
        <RangePicker hours={hours} setHours={setHours} />
      </div>
      <Loading error={m.error} loading={m.loading && !m.data} />
      {m.data && (
        <div className="charts">
          <LineChart title={t("CPU по контейнерам")} format={pct} series={cpu} />
          <LineChart title={t("Память по контейнерам")} format={fmtBytes} series={mem} />
          <LineChart title={t("Сеть: входящий трафик")} format={rate} series={rx} />
          <LineChart title={t("Сеть: исходящий трафик")} format={rate} series={tx} />
        </div>
      )}
    </div>
  );
}

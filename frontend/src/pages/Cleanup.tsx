import { useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { JobPanel } from "../JobPanel";
import { ActionButton, Loading, fmtBytes, useFetch } from "../ui";

export function CleanupPage() {
  const { can } = useAuth();
  const info = useFetch<any>(() => api("/docker/info"), []);
  const df = useFetch<any>(() => api("/docker/df"), []);
  const [o, setO] = useState({
    containers: true, images: true, all_images: false, build_cache: true, networks: true, volumes: false, older_than_hours: 24,
  });
  const [job, setJob] = useState<number | null>(null);
  const tog = (k: keyof typeof o) => (e: any) => setO({ ...o, [k]: e.target.checked });

  const presets: [string, Partial<typeof o>][] = [
    ["Мягкая", { containers: true, images: true, all_images: false, build_cache: true, networks: true, volumes: false, older_than_hours: 24 }],
    ["Глубокая", { containers: true, images: true, all_images: true, build_cache: true, networks: true, volumes: false, older_than_hours: 72 }],
    ["Всё неиспользуемое", { containers: true, images: true, all_images: true, build_cache: true, networks: true, volumes: false, older_than_hours: 0 }],
  ];

  return (
    <div className="stack">
      <div className="page-head"><h1>Система и очистка</h1></div>
      <Loading error={info.error} loading={info.loading && !info.data} />
      {info.data && (
        <div className="grid stats-grid">
          <Stat label="Docker" value={info.data.server_version} sub={`${info.data.os} · ${info.data.arch}`} />
          <Stat label="Хост" value={info.data.name} sub={`${info.data.cpus} CPU · ${fmtBytes(info.data.mem_total)}`} />
          <Stat label="Контейнеры" value={`${info.data.running} / ${info.data.containers}`} sub={`остановлено: ${info.data.stopped}`} />
          {df.data && (
            <>
              <Stat label="Образы" value={fmtBytes(df.data.images.size)} sub={`${df.data.images.count} шт · можно освободить ~${fmtBytes(df.data.images.reclaimable)}`} />
              <Stat label="Build cache" value={fmtBytes(df.data.build_cache.size)} sub={`${df.data.build_cache.count} записей`} />
              <Stat label="Тома" value={fmtBytes(df.data.volumes.size)} sub={`${df.data.volumes.count} шт`} />
            </>
          )}
        </div>
      )}
      {!df.data && !df.error && <div className="muted small">Подсчёт места на диске…</div>}

      {can("admin") ? (
        <div className="card form">
          <h3>Очистка</h3>
          <div className="row wrap">
            {presets.map(([l, v]) => <button key={l} className="btn sm" onClick={() => setO({ ...o, ...v })}>{l}</button>)}
          </div>
          <label className="check"><input type="checkbox" checked={o.containers} onChange={tog("containers")} />Остановленные контейнеры</label>
          <label className="check"><input type="checkbox" checked={o.images} onChange={tog("images")} />Образы: dangling (&lt;none&gt;, старые слои после пересборки)</label>
          <label className="check sub"><input type="checkbox" checked={o.all_images} disabled={!o.images} onChange={tog("all_images")} />…и все образы, не используемые контейнерами</label>
          <label className="check"><input type="checkbox" checked={o.build_cache} onChange={tog("build_cache")} />Build cache</label>
          <label className="check"><input type="checkbox" checked={o.networks} onChange={tog("networks")} />Неиспользуемые сети</label>
          <label className="check danger-text"><input type="checkbox" checked={o.volumes} onChange={tog("volumes")} />Неиспользуемые тома (данные будут потеряны!)</label>
          <label className="inline">
            Только старше
            <input type="number" min={0} value={o.older_than_hours} onChange={(e) => setO({ ...o, older_than_hours: Number(e.target.value) })} style={{ width: 90 }} />
            часов (0 — без ограничения; на тома не влияет)
          </label>
          <div className="hint">Автоочистку по расписанию можно включить переменными DM_AUTO_PRUNE_INTERVAL_HOURS и DM_AUTO_PRUNE_OLDER_THAN_HOURS.</div>
          <div className="row end">
            <ActionButton className="btn danger" confirm={o.volumes ? "Будут удалены неиспользуемые ТОМА с данными. Продолжить?" : "Запустить очистку?"}
              onClick={async () => setJob((await api("/docker/prune", { body: o })).job_id)}>🧹 Запустить очистку</ActionButton>
          </div>
        </div>
      ) : (
        <div className="muted">Очистка доступна администраторам.</div>
      )}
      {job && <JobPanel jobId={job} title="Очистка" onClose={() => setJob(null)} onDone={() => { df.reload(); info.reload(); }} height={260} />}
    </div>
  );
}

function Stat({ label, value, sub }: { label: string; value: any; sub?: string }) {
  return (
    <div className="card stat">
      <div className="muted small">{label}</div>
      <div className="stat-value">{value}</div>
      {sub && <div className="muted small">{sub}</div>}
    </div>
  );
}

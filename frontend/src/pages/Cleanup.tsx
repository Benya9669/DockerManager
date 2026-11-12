import { useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { useServer, withServer } from "../server";
import { JobPanel } from "../JobPanel";
import { HostMonitoring } from "../Monitoring";
import { ActionButton, Loading, fmtAgo, fmtBytes, useFetch } from "../ui";

export function CleanupPage() {
  const { can } = useAuth();
  const { serverId } = useServer();
  const info = useFetch<any>(() => api(withServer("/docker/info", serverId)), [serverId]);
  const df = useFetch<any>(() => api(withServer("/docker/df", serverId)), [serverId]);
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
      {can("admin") && <UpdateCard />}
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
      {serverId == null ? <HostMonitoring /> : <div className="hint">История нагрузки хоста доступна для локального сервера; метрики контейнеров удалённых серверов — на вкладке «Мониторинг» проектов.</div>}

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
              onClick={async () => setJob((await api(withServer("/docker/prune", serverId), { body: o })).job_id)}>🧹 Запустить очистку</ActionButton>
          </div>
        </div>
      ) : (
        <div className="muted">Очистка доступна администраторам.</div>
      )}
      {job && <JobPanel jobId={job} title="Очистка" onClose={() => setJob(null)} onDone={() => { df.reload(); info.reload(); }} height={260} />}
    </div>
  );
}

function UpdateCard() {
  const st = useFetch<any>(() => api("/system/update"), []);
  const [job, setJob] = useState<number | null>(null);
  const [restarting, setRestarting] = useState(false);
  const [notes, setNotes] = useState(false);

  const waitForRestart = (oldVersion: string) => {
    setRestarting(true);
    let sawDown = false;
    const started = Date.now();
    const t = setInterval(async () => {
      try {
        const v = await api("/version");
        if (sawDown || v.version !== oldVersion || Date.now() - started > 15 * 60_000) {
          clearInterval(t);
          location.reload();
        }
      } catch {
        sawDown = true;
      }
    }, 3000);
  };

  const run = async (force: boolean) => {
    const r = await api("/system/update", { body: { force } });
    setJob(r.job_id);
    waitForRestart(st.data.current);
  };

  if (!st.data) return <Loading error={st.error} loading={st.loading} />;
  const s = st.data;
  const lc = s.last_check || {};
  const latest = lc.latest;

  return (
    <div className="card stack-sm">
      <div className="row between wrap">
        <div className="stack-sm">
          <h3>Версия панели</h3>
          <div>
            Текущая: <b>v{s.current}</b>{s.git_sha && <span className="muted mono small"> {s.git_sha.slice(0, 7)}</span>}
            {" · "}последняя: {latest ? <a href={latest.url} target="_blank" rel="noreferrer"><b>v{latest.version}</b></a> : <span className="muted">релизов нет</span>}
            {lc.update_available && <span className="badge yellow" style={{ marginLeft: 8 }}>доступно обновление</span>}
            {latest && !lc.update_available && <span className="badge green" style={{ marginLeft: 8 }}>актуальная</span>}
          </div>
          <div className="muted small">
            Режим: <b>{s.mode === "image" ? "образ из GHCR" : "git pull + сборка"}</b> · репозиторий {s.repo} ·
            автообновление: <b>{s.auto_update ? `вкл (раз в ${s.check_hours} ч)` : "выкл"}</b>
            {lc.checked_at && <> · проверено {fmtAgo(lc.checked_at)}</>}
          </div>
          {lc.error && <div className="danger-text small">Ошибка проверки: {lc.error}</div>}
          {!s.can_update && <div className="danger-text small">{s.reason}</div>}
        </div>
        <div className="row wrap">
          <ActionButton onClick={async () => st.setData(await api("/system/update?refresh=true"))}>Проверить</ActionButton>
          {latest?.notes && <button className="btn" onClick={() => setNotes(!notes)}>Что нового</button>}
          <ActionButton className="btn primary" disabled={!s.can_update || !lc.update_available || restarting}
            confirm={`Обновить панель до v${latest?.version}? Панель перезапустится.`} onClick={() => run(false)}>
            ⬆ Обновить
          </ActionButton>
          <ActionButton className="btn ghost" disabled={!s.can_update || restarting}
            confirm={s.mode === "image" ? "Скачать образ заново и перезапустить панель?" : "Выполнить git pull и пересобрать панель, даже если версия не изменилась?"}
            onClick={() => run(true)}>Принудительно</ActionButton>
        </div>
      </div>
      {notes && latest?.notes && <pre className="small">{latest.notes}</pre>}
      {restarting && (
        <div className="hint">
          Панель обновляется и перезапустится, страница перезагрузится сама. Ход обновления:{" "}
          {s.updater_name && <span className="mono">docker logs -f {s.updater_name}</span>}
        </div>
      )}
      {job && <JobPanel jobId={job} title="Обновление панели" height={140} />}
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

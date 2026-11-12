import { useState } from "react";
import { api, downloadFile } from "../api";
import { JobPanel } from "../JobPanel";
import { ActionButton, Loading, fmtBytes, fmtDate, toastErr, useFetch } from "../ui";

const KIND: Record<string, string> = { panel: "панель", files: "файлы проекта", volume: "том" };

export function BackupsPage() {
  const list = useFetch<any>(() => api("/backups"), [], 15000);
  const projects = useFetch<any[]>(() => api("/projects"), []);
  const [pid, setPid] = useState("");
  const [stop, setStop] = useState(false);
  const [filter, setFilter] = useState("");
  const [job, setJob] = useState<{ id: number; title: string } | null>(null);
  const run = (title: string) => async (r: Promise<any>) => setJob({ id: (await r).job_id, title });
  const s = list.data?.settings;
  const items = (list.data?.items || []).filter((b: any) => !filter || b.kind === filter);

  return (
    <div className="stack">
      <div className="page-head"><h1>Бэкапы</h1></div>
      <div className="card stack-sm">
        <div className="row wrap">
          <ActionButton onClick={() => run("Бэкап панели")(api("/backups/panel", { method: "POST" }))}>Бэкап панели</ActionButton>
          <ActionButton className="btn primary" confirm="Сделать бэкап панели и всех проектов (файлы + тома)?"
            onClick={() => run("Полный бэкап")(api("/backups/all", { method: "POST" }))}>Полный бэкап</ActionButton>
          <span className="muted">|</span>
          <select value={pid} onChange={(e) => setPid(e.target.value)}>
            <option value="">проект…</option>
            {(projects.data || []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <label className="check" title="docker compose stop на время архивации томов — консистентные данные БД">
            <input type="checkbox" checked={stop} onChange={(e) => setStop(e.target.checked)} />остановить на время бэкапа
          </label>
          <ActionButton disabled={!pid} onClick={() => run("Бэкап проекта")(api(`/backups/project/${pid}`, { body: { stop } }))}>
            Бэкап проекта
          </ActionButton>
        </div>
        {s && (
          <div className="muted small">
            Папка: <span className="mono">{s.dir}</span> · хранится последних: {s.keep} на объект ·
            по расписанию: {s.interval_hours ? `каждые ${s.interval_hours} ч` : "выкл (DM_BACKUP_INTERVAL_HOURS)"}
          </div>
        )}
        <div className="hint">
          Бэкап проекта = архив файлов (compose, .env, код без .git/node_modules) + архив каждого именованного тома.
          Для баз данных включайте «остановить на время бэкапа» или делайте дамп средствами СУБД.
        </div>
      </div>
      {job && <JobPanel jobId={job.id} title={job.title} onClose={() => setJob(null)} onDone={list.reload} height={240} />}
      <div className="row">
        <span className="muted">Тип:</span>
        {[["", "все"], ["panel", "панель"], ["files", "файлы"], ["volume", "тома"]].map(([k, l]) => (
          <button key={k} className={`btn sm ${filter === k ? "primary" : ""}`} onClick={() => setFilter(k)}>{l}</button>
        ))}
      </div>
      <Loading error={list.error} loading={list.loading && !list.data} />
      {list.data && !items.length && <div className="empty">Бэкапов нет</div>}
      {!!items.length && (
        <table className="table">
          <thead><tr><th>Тип</th><th>Объект</th><th>Файл</th><th>Размер</th><th>Статус</th><th>Когда</th><th /></tr></thead>
          <tbody>
            {items.map((b: any) => (
              <tr key={b.id}>
                <td>{KIND[b.kind] || b.kind}</td>
                <td className="mono small">{b.target}</td>
                <td className="mono small">{b.filename}</td>
                <td>{fmtBytes(b.size)}</td>
                <td><span className={`badge ${b.status === "success" ? "green" : b.status === "failed" ? "red" : "yellow"}`}>{b.status}</span></td>
                <td className="small">{fmtDate(b.created_at)}<div className="muted">{b.username}</div></td>
                <td className="actions">
                  {b.status === "success" && (
                    <button className="btn sm" onClick={() => downloadFile(`/backups/${b.id}/download`, b.filename).catch(toastErr)}>⬇</button>
                  )}
                  {b.status === "success" && b.kind !== "panel" && (
                    <ActionButton className="btn sm" confirm={b.kind === "volume"
                      ? `Восстановить том ${b.target} из этого архива? ТЕКУЩИЕ ДАННЫЕ ТОМА БУДУТ ЗАМЕНЕНЫ. Контейнеры проекта будут остановлены на время восстановления.`
                      : `Восстановить файлы проекта из архива? Файлы с теми же именами будут перезаписаны.`}
                      onClick={() => run(`Восстановление ${b.target}`)(api(`/backups/${b.id}/restore`, { method: "POST" }))}>↺ Восстановить</ActionButton>
                  )}
                  <ActionButton className="btn sm danger" confirm={`Удалить ${b.filename}?`} onClick={async () => {
                    await api(`/backups/${b.id}`, { method: "DELETE" });
                    list.reload();
                  }}>🗑</ActionButton>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

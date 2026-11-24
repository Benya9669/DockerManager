import { t, tf } from "../i18n";
import { useState } from "react";
import { api, downloadFile } from "../api";
import { useServer } from "../server";
import { JobPanel } from "../JobPanel";
import { ActionButton, Loading, fmtBytes, fmtDate, toastErr, useFetch } from "../ui";

const KIND: Record<string, string> = { panel: t("панель"), files: t("файлы проекта"), volume: t("том") };

export function BackupsPage() {
  const { servers } = useServer();
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
      <div className="page-head"><h1>{t("Бэкапы")}</h1></div>
      <div className="card stack-sm">
        <div className="row wrap">
          <ActionButton onClick={() => run(t("Бэкап панели"))(api("/backups/panel", { method: "POST" }))}>{t("Бэкап панели")}</ActionButton>
          <ActionButton className="btn primary" confirm={t("Сделать бэкап панели и всех проектов (файлы + тома)?")}
            onClick={() => run(t("Полный бэкап"))(api("/backups/all", { method: "POST" }))}>{t("Полный бэкап")}</ActionButton>
          <span className="muted">|</span>
          <select value={pid} onChange={(e) => setPid(e.target.value)}>
            <option value="">{t("проект…")}</option>
            {(projects.data || []).map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <label className="check" title={t("docker compose stop на время архивации томов — консистентные данные БД")}>
            <input type="checkbox" checked={stop} onChange={(e) => setStop(e.target.checked)} />{t("остановить на время бэкапа")}
          </label>
          <ActionButton disabled={!pid} onClick={() => run(t("Бэкап проекта"))(api(`/backups/project/${pid}`, { body: { stop } }))}>
            {t("Бэкап проекта")}
          </ActionButton>
        </div>
        {s && (
          <div className="muted small">
            {t("Папка:")} <span className="mono">{s.dir}</span> {t("· хранится последних:")} {s.keep} {t("на объект · по расписанию:")} {s.interval_hours ? tf("каждые {0} ч", s.interval_hours) : t("выкл (DM_BACKUP_INTERVAL_HOURS)")}
          </div>
        )}
        <div className="hint">
          {t("Бэкап проекта = архив файлов (compose, .env, код без .git/node_modules) + архив каждого именованного тома.")}
          {t("Для баз данных включайте «остановить на время бэкапа» или делайте дамп средствами СУБД.")}
        </div>
      </div>
      {job && <JobPanel jobId={job.id} title={job.title} onClose={() => setJob(null)} onDone={list.reload} height={240} />}
      <div className="row">
        <span className="muted">{t("Тип:")}</span>
        {[["", t("все")], ["panel", t("панель")], ["files", t("файлы")], ["volume", t("тома")]].map(([k, l]) => (
          <button key={k} className={`btn sm ${filter === k ? "primary" : ""}`} onClick={() => setFilter(k)}>{l}</button>
        ))}
      </div>
      <Loading error={list.error} loading={list.loading && !list.data} />
      {list.data && !items.length && <div className="empty">{t("Бэкапов нет")}</div>}
      {!!items.length && (
        <table className="table">
          <thead><tr><th>{t("Тип")}</th><th>{t("Объект")}</th><th>{t("Файл")}</th><th>{t("Размер")}</th><th>{t("Статус")}</th><th>{t("Когда")}</th><th /></tr></thead>
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
                    <ActionButton className="btn sm" confirm={[projects.data?.find(p => p.id === b.project_id)?.name, projects.data?.find(p => p.id === b.project_id)?.environment, b.kind === "files" ? t("Локальный") : servers.find(s => s.id === b.server_id)?.name || t("Локальный"), b.kind === "volume"
                      ? tf("Восстановить том {0} из этого архива? ТЕКУЩИЕ ДАННЫЕ ТОМА БУДУТ ЗАМЕНЕНЫ. Контейнеры проекта будут остановлены на время восстановления.", b.target)
                      : t("Восстановить файлы проекта из архива? Файлы с теми же именами будут перезаписаны.")].filter(Boolean).join(" · ")}
                      onClick={() => run(tf("Восстановление {0}", b.target))(api(`/backups/${b.id}/restore`, { method: "POST" }))}>{t("↺ Восстановить")}</ActionButton>
                  )}
                  <ActionButton className="btn sm danger" confirm={tf("Удалить {0}?", b.filename)} onClick={async () => {
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

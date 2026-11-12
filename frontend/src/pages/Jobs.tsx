import { t, tf } from "../i18n";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../api";
import { JobPanel } from "../JobPanel";
import { Loading, StateBadge, fmtDate, useFetch } from "../ui";

export function JobsPage() {
  const nav = useNavigate();
  const jobs = useFetch<any[]>(() => api("/jobs?limit=200"), [], 5000);
  return (
    <div>
      <div className="page-head"><h1>{t("Задачи")}</h1></div>
      <Loading error={jobs.error} loading={jobs.loading && !jobs.data} />
      <table className="table">
        <thead><tr><th>#</th><th>{t("Проект")}</th><th>{t("Действие")}</th><th>{t("Статус")}</th><th>{t("Кто")}</th><th>{t("Начало")}</th><th>{t("Длительность")}</th></tr></thead>
        <tbody>
          {(jobs.data || []).map((j) => (
            <tr key={j.id} className="clickable" onClick={() => nav(`/jobs/${j.id}`)}>
              <td>{j.id}</td>
              <td>{j.project_id ? <Link to={`/projects/${j.project_id}`} onClick={(e) => e.stopPropagation()}>{j.project_name}</Link> : <span className="muted">{t("система")}</span>}</td>
              <td className="mono">{j.action}</td>
              <td>{j.status === "running" ? <span className="badge yellow">{t("выполняется")}</span> : <StateBadge state={j.status} />}</td>
              <td>{j.username}</td>
              <td className="small">{fmtDate(j.started_at)}</td>
              <td className="small">{j.finished_at ? tf("{0} с", Math.round((new Date(j.finished_at).getTime() - new Date(j.started_at).getTime()) / 1000)) : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function JobPage() {
  const { id } = useParams();
  const job = useFetch<any>(() => api(`/jobs/${id}`), [id]);
  if (!job.data) return <Loading error={job.error} loading />;
  const j = job.data;
  return (
    <div>
      <div className="page-head">
        <div>
          <div className="muted small"><Link to="/jobs">{t("Задачи")}</Link> /</div>
          <h1>#{j.id} <span className="mono">{j.action}</span></h1>
          <div className="muted small">
            {j.project_id && <><Link to={`/projects/${j.project_id}`}>{j.project_name}</Link> · </>}
            {j.username} · {fmtDate(j.started_at)}
          </div>
        </div>
      </div>
      <JobPanel jobId={j.id} title={j.action} height={600} onDone={job.reload} />
    </div>
  );
}

import { useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { JobPanel } from "../JobPanel";
import { ActionButton, Loading, fmtAgo, fmtBytes, toast, useFetch } from "../ui";

export function ImagesPage() {
  const { can } = useAuth();
  const list = useFetch<any[]>(() => api("/docker/images"), [], 15000);
  const [q, setQ] = useState("");
  const [filter, setFilter] = useState("all");
  const [pull, setPull] = useState("");
  const [job, setJob] = useState<number | null>(null);
  const items = (list.data || [])
    .filter((i) => filter === "all" || (filter === "unused" ? !i.in_use : filter === "dangling" ? i.dangling : i.in_use))
    .filter((i) => !q || `${i.tags.join(" ")} ${i.short_id} ${i.project || ""}`.toLowerCase().includes(q.toLowerCase()));
  const total = items.reduce((s, i) => s + (i.size || 0), 0);

  return (
    <div>
      <div className="page-head">
        <h1>Образы <span className="muted small">{items.length} · {fmtBytes(total)}</span></h1>
        <div className="row">
          <select value={filter} onChange={(e) => setFilter(e.target.value)}>
            <option value="all">все</option><option value="used">используются</option>
            <option value="unused">не используются</option><option value="dangling">dangling (&lt;none&gt;)</option>
          </select>
          <input placeholder="Фильтр…" value={q} onChange={(e) => setQ(e.target.value)} />
          {can("operator") && (
            <form className="row" onSubmit={async (e) => {
              e.preventDefault();
              if (!pull) return;
              const r = await api("/docker/images/pull", { body: { image: pull } });
              setJob(r.job_id);
            }}>
              <input placeholder="nginx:alpine" value={pull} onChange={(e) => setPull(e.target.value)} />
              <button className="btn">⬇ Pull</button>
            </form>
          )}
        </div>
      </div>
      {job && <JobPanel jobId={job} title={`docker pull ${pull}`} onClose={() => setJob(null)} onDone={list.reload} height={200} />}
      <Loading error={list.error} loading={list.loading && !list.data} />
      <table className="table">
        <thead><tr><th>Теги</th><th>ID</th><th>Проект</th><th>Размер</th><th>Создан</th><th>Статус</th><th /></tr></thead>
        <tbody>
          {items.map((i) => (
            <tr key={i.id}>
              <td className="mono small">{i.tags.length ? i.tags.join(", ") : <span className="muted">&lt;none&gt;</span>}</td>
              <td className="mono small">{i.short_id}</td>
              <td>{i.project || <span className="muted">—</span>}</td>
              <td>{fmtBytes(i.size)}</td>
              <td className="small">{fmtAgo(i.created)}</td>
              <td>{i.in_use ? <span className="badge green">используется</span> : <span className="badge gray">не используется</span>}</td>
              <td className="actions">
                {can("admin") && (
                  <ActionButton className="btn sm danger" confirm={`Удалить образ ${i.tags[0] || i.short_id}?`} onClick={async () => {
                    await api(`/docker/images/${encodeURIComponent(i.id)}?force=${i.tags.length > 1 ? "true" : "false"}`, { method: "DELETE" });
                    toast("Образ удалён");
                    list.reload();
                  }}>🗑</ActionButton>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function VolumesPage() {
  const { can } = useAuth();
  const list = useFetch<any[]>(() => api("/docker/volumes"), [], 15000);
  return (
    <div>
      <div className="page-head"><h1>Тома</h1></div>
      <Loading error={list.error} loading={list.loading && !list.data} />
      <table className="table">
        <thead><tr><th>Имя</th><th>Проект</th><th>Драйвер</th><th>Создан</th><th>Статус</th><th /></tr></thead>
        <tbody>
          {(list.data || []).map((v) => (
            <tr key={v.name}>
              <td className="mono small">{v.name}</td>
              <td>{v.project || <span className="muted">—</span>}</td>
              <td>{v.driver}</td>
              <td className="small">{fmtAgo(v.created)}</td>
              <td>{v.in_use ? <span className="badge green">используется</span> : <span className="badge gray">свободен</span>}</td>
              <td className="actions">
                {can("admin") && !v.in_use && (
                  <ActionButton className="btn sm danger" confirm={`Удалить том ${v.name}? ДАННЫЕ БУДУТ ПОТЕРЯНЫ.`} onClick={async () => {
                    await api(`/docker/volumes/${encodeURIComponent(v.name)}`, { method: "DELETE" });
                    list.reload();
                  }}>🗑</ActionButton>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function NetworksPage() {
  const { can } = useAuth();
  const list = useFetch<any[]>(() => api("/docker/networks"), [], 15000);
  return (
    <div>
      <div className="page-head"><h1>Сети</h1></div>
      <Loading error={list.error} loading={list.loading && !list.data} />
      <table className="table">
        <thead><tr><th>Имя</th><th>ID</th><th>Проект</th><th>Драйвер</th><th>Подсети</th><th /></tr></thead>
        <tbody>
          {(list.data || []).map((n) => (
            <tr key={n.id}>
              <td>{n.name}</td>
              <td className="mono small">{n.short_id}</td>
              <td>{n.project || <span className="muted">—</span>}</td>
              <td>{n.driver} <span className="muted small">{n.scope}</span></td>
              <td className="mono small">{n.subnets.join(", ")}</td>
              <td className="actions">
                {can("admin") && !n.builtin && (
                  <ActionButton className="btn sm danger" confirm={`Удалить сеть ${n.name}?`} onClick={async () => {
                    await api(`/docker/networks/${n.id}`, { method: "DELETE" });
                    list.reload();
                  }}>🗑</ActionButton>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, wsUrl } from "../api";
import { useAuth } from "../auth";
import { Editor } from "../Editor";
import { XTerm } from "../XTerm";
import { ActionButton, Loading, Ports, StateBadge, Tabs, fmtBytes, fmtDate, useFetch } from "../ui";

function ContainerActions({ c, onDone }: { c: { id: string; state: string }; onDone: () => void }) {
  const { can } = useAuth();
  if (!can("operator")) return null;
  const act = (a: string) => async () => {
    await api(`/docker/containers/${c.id}/${a}`, { method: "POST" });
    onDone();
  };
  return (
    <>
      {c.state !== "running" && <ActionButton className="btn sm" onClick={act("start")} title="start">▶</ActionButton>}
      {c.state === "running" && <ActionButton className="btn sm" onClick={act("restart")} title="restart">⟳</ActionButton>}
      {c.state === "running" && <ActionButton className="btn sm" onClick={act("stop")} title="stop">⏸</ActionButton>}
      <ActionButton className="btn sm danger" confirm="Удалить контейнер (force)?" onClick={act("remove")} title="remove">🗑</ActionButton>
    </>
  );
}

export function ContainersPage() {
  const list = useFetch<any[]>(() => api("/docker/containers"), [], 5000);
  const [q, setQ] = useState("");
  const [onlyRunning, setOnlyRunning] = useState(false);
  const items = (list.data || [])
    .filter((c) => !onlyRunning || c.state === "running")
    .filter((c) => !q || `${c.name} ${c.image} ${c.project || ""}`.toLowerCase().includes(q.toLowerCase()))
    .sort((a, b) => (a.project || "~").localeCompare(b.project || "~") || a.name.localeCompare(b.name));

  return (
    <div>
      <div className="page-head">
        <h1>Контейнеры</h1>
        <div className="row">
          <label className="check"><input type="checkbox" checked={onlyRunning} onChange={(e) => setOnlyRunning(e.target.checked)} />только запущенные</label>
          <input placeholder="Фильтр…" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
      </div>
      <Loading error={list.error} loading={list.loading && !list.data} />
      <table className="table">
        <thead><tr><th>Имя</th><th>Проект / сервис</th><th>Статус</th><th>Образ</th><th>Порты</th><th /></tr></thead>
        <tbody>
          {items.map((c) => (
            <tr key={c.id}>
              <td><Link to={`/containers/${c.id}`}>{c.name}</Link><div className="muted small mono">{c.short_id}</div></td>
              <td>{c.project ? <>{c.project}<span className="muted"> / {c.service}</span></> : <span className="muted">—</span>}</td>
              <td><StateBadge state={c.state} /><div className="muted small">{c.status}</div></td>
              <td className="small mono">{c.image}</td>
              <td><Ports ports={c.ports} /></td>
              <td className="actions"><ContainerActions c={c} onDone={list.reload} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function ContainerPage() {
  const { id } = useParams();
  const nav = useNavigate();
  const { can } = useAuth();
  const [sp, setSp] = useSearchParams();
  const tab = sp.get("tab") || "logs";
  const info = useFetch<any>(() => api(`/docker/containers/${id}`), [id], 5000);
  const stats = useFetch<any>(() => (info.data?.State?.Running ? api(`/docker/containers/${id}/stats`) : Promise.resolve(null)), [id, info.data?.State?.Running], 5000);
  const [tail, setTail] = useState("500");
  const [ts, setTs] = useState(false);
  const [shell, setShell] = useState("");
  const [shellKey, setShellKey] = useState(0);

  if (!info.data) return <Loading error={info.error} loading />;
  const c = info.data;
  const state = c.State?.Status;
  const labels = c.Config?.Labels || {};

  return (
    <div>
      <div className="page-head">
        <div>
          <div className="muted small"><Link to="/containers">Контейнеры</Link> /</div>
          <h1>{c.Name?.replace(/^\//, "")} <StateBadge state={state} /></h1>
          <div className="muted small mono">{c.Config?.Image} · {c.Id.slice(0, 12)} · создан {fmtDate(c.Created)}</div>
          {labels["com.docker.compose.project"] && <div className="small">Проект: <b>{labels["com.docker.compose.project"]}</b> / {labels["com.docker.compose.service"]}</div>}
        </div>
        <div className="row">
          {stats.data && (
            <div className="stats">
              <span>CPU <b>{stats.data.cpu_percent}%</b></span>
              <span>RAM <b>{fmtBytes(stats.data.mem_usage)}</b> / {fmtBytes(stats.data.mem_limit)}</span>
            </div>
          )}
          <ContainerActions c={{ id: c.Id, state }} onDone={info.reload} />
        </div>
      </div>
      <Tabs
        active={tab}
        onChange={(t) => setSp({ tab: t }, { replace: true })}
        tabs={[["logs", "Логи"], ...(can("operator") ? ([["shell", "Терминал"]] as [string, string][]) : []), ["inspect", "Inspect"], ["env", "Env / mounts"]]}
      />
      <div className="tab-body">
        {tab === "logs" && (
          <>
            <div className="row mb">
              <span className="muted">Последние строки:</span>
              <select value={tail} onChange={(e) => setTail(e.target.value)}>
                {["100", "500", "2000", "10000", "all"].map((t) => <option key={t}>{t}</option>)}
              </select>
              <label className="check"><input type="checkbox" checked={ts} onChange={(e) => setTs(e.target.checked)} />время</label>
            </div>
            <XTerm url={wsUrl(`/docker/containers/${id}/logs`, { tail, timestamps: ts ? "1" : "0" })} mode="stream" height="65vh"
              download={{ path: `/docker/containers/${id}/logs/download?tail=${tail}&timestamps=${ts ? 1 : 0}`, filename: `${c.Name?.replace(/^\//, "")}.log` }} />
          </>
        )}
        {tab === "shell" && (
          state === "running" ? (
            <>
              <div className="row mb">
                <input className="grow mono" placeholder="команда (по умолчанию bash или sh)" value={shell} onChange={(e) => setShell(e.target.value)} />
                <button className="btn" onClick={() => setShellKey((k) => k + 1)}>Переподключить</button>
              </div>
              <XTerm key={shellKey} url={wsUrl(`/docker/containers/${id}/exec`, shell ? { cmd: shell } : {})} mode="exec" height="65vh" />
            </>
          ) : <div className="empty">Контейнер не запущен</div>
        )}
        {tab === "inspect" && <Editor value={JSON.stringify(c, null, 2)} readOnly filename="inspect.json" height="70vh" />}
        {tab === "env" && (
          <div className="stack">
            <h3>Переменные окружения</h3>
            <pre className="small">{(c.Config?.Env || []).join("\n")}</pre>
            <h3>Монтирования</h3>
            <table className="table">
              <thead><tr><th>Тип</th><th>Источник</th><th>Назначение</th><th>RW</th></tr></thead>
              <tbody>
                {(c.Mounts || []).map((m: any, i: number) => (
                  <tr key={i}><td>{m.Type}</td><td className="mono small">{m.Name || m.Source}</td><td className="mono small">{m.Destination}</td><td>{m.RW ? "да" : "нет"}</td></tr>
                ))}
              </tbody>
            </table>
            <h3>Сети</h3>
            <pre className="small">{Object.entries(c.NetworkSettings?.Networks || {}).map(([n, v]: any) => `${n}: ${v.IPAddress || "-"}`).join("\n")}</pre>
            <button className="btn ghost" onClick={() => nav(-1)}>Назад</button>
          </div>
        )}
      </div>
    </div>
  );
}

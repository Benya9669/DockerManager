import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, wsUrl } from "../api";
import { XTerm } from "../XTerm";
import { useAuth } from "../auth";
import { Editor } from "../Editor";
import { JobPanel } from "../JobPanel";
import { SshKeySelect } from "../SshKeySelect";
import {
  ActionButton, Loading, Modal, Ports, StateBadge, Tabs, fmtAgo, fmtBytes, fmtDate, toast, toastErr, useFetch,
} from "../ui";

export function ProjectPage() {
  const { id } = useParams();
  const [sp, setSp] = useSearchParams();
  const { can } = useAuth();
  const proj = useFetch<any>(() => api(`/projects/${id}`), [id], 5000);
  const [tab, setTab] = useState(sp.get("tab") || "overview");
  const [jobId, setJobId] = useState<number | null>(sp.get("job") ? Number(sp.get("job")) : null);
  const [jobTitle, setJobTitle] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);

  const changeTab = (t: string) => {
    setTab(t);
    sp.set("tab", t);
    setSp(sp, { replace: true });
  };

  const runAction = async (action: string, body: any = {}, title?: string) => {
    const r = await api(`/projects/${id}/actions/${action}`, { body });
    setJobTitle(title || action);
    setJobId(r.job_id);
    proj.reload();
  };
  const startJob = (jid: number, title: string) => {
    setJobTitle(title);
    setJobId(jid);
    proj.reload();
  };

  const p = proj.data;
  if (!p) return <Loading error={proj.error} loading />;

  return (
    <div>
      <div className="page-head">
        <div>
          <div className="muted small"><Link to="/">Проекты</Link> /</div>
          <h1>{p.name} <span className="muted small">{p.slug}</span></h1>
          {p.description && <div className="muted">{p.description}</div>}
        </div>
        {can("operator") && <ProjectToolbar p={p} runAction={runAction} />}
      </div>

      <EnvSelector p={p} onChange={proj.reload} />

      {jobId && (
        <JobPanel
          jobId={jobId}
          title={jobTitle}
          onClose={() => setJobId(null)}
          onDone={(s) => {
            proj.reload();
            setRefreshKey((k) => k + 1);
            toast(`${jobTitle || "Задача"}: ${s === "success" ? "успешно" : s}`, s === "success" ? "ok" : "err");
          }}
        />
      )}

      <Tabs
        active={tab}
        onChange={changeTab}
        tabs={[
          ["overview", "Сервисы"],
          ["logs", "Логи"],
          ...(can("operator") ? ([["env", "Переменные (.env)"], ["files", "Файлы"]] as [string, string][]) : []),
          ...(p.source === "git" ? ([["git", "Git"]] as [string, string][]) : []),
          ["jobs", "История"],
          ...(can("admin") ? ([["settings", "Настройки"]] as [string, string][]) : []),
        ]}
      />
      <div className="tab-body">
        {tab === "overview" && <ServicesTab p={p} runAction={runAction} refreshKey={refreshKey} />}
        {tab === "logs" && <ProjectLogs p={p} />}
        {tab === "env" && <EnvTab p={p} onChange={proj.reload} />}
        {tab === "files" && <FilesTab p={p} />}
        {tab === "git" && <GitTab p={p} startJob={startJob} refreshKey={refreshKey} />}
        {tab === "jobs" && <ProjectJobs p={p} open={startJob} refreshKey={refreshKey} />}
        {tab === "settings" && <SettingsTab p={p} onSaved={proj.reload} startJob={startJob} />}
      </div>
    </div>
  );
}

function ProjectToolbar({ p, runAction }: { p: any; runAction: (a: string, body?: any, t?: string) => Promise<void> }) {
  const [noCache, setNoCache] = useState(false);
  const [showConfig, setShowConfig] = useState<string | null>(null);
  const dis = p.busy;
  return (
    <div className="toolbar">
      <ActionButton className="btn primary" disabled={dis} title="git pull → pull образов → build → up -d"
        onClick={() => runAction("deploy", { no_cache: noCache }, "Деплой")}>🚀 Деплой</ActionButton>
      <ActionButton disabled={dis} onClick={() => runAction("up", {}, "Запуск (up -d)")}>▶ Up</ActionButton>
      <div className="btn-group">
        <ActionButton disabled={dis} title="docker compose build --pull" onClick={() => runAction("build", { no_cache: noCache }, "Сборка")}>🔨 Build</ActionButton>
        <ActionButton disabled={dis} title="build + пересоздание контейнеров" onClick={() => runAction("rebuild", { no_cache: noCache }, "Пересборка")}>♻ Rebuild</ActionButton>
        <label className="check" title="--no-cache"><input type="checkbox" checked={noCache} onChange={(e) => setNoCache(e.target.checked)} />без кэша</label>
      </div>
      <ActionButton disabled={dis} onClick={() => runAction("restart", {}, "Перезапуск")}>⟳ Restart</ActionButton>
      <ActionButton disabled={dis} onClick={() => runAction("pull", {}, "Pull образов")}>⬇ Pull</ActionButton>
      <ActionButton disabled={dis} onClick={() => runAction("stop", {}, "Остановка")}>⏸ Stop</ActionButton>
      <ActionButton disabled={dis} className="btn danger" confirm="Остановить и удалить контейнеры проекта (docker compose down)?"
        onClick={() => runAction("down", {}, "Down")}>⏹ Down</ActionButton>
      <ActionButton disabled={dis} title="удалить остановленные контейнеры и старые образы проекта"
        confirm="Удалить остановленные контейнеры проекта и неиспользуемые образы, собранные для него?"
        onClick={() => runAction("cleanup", {}, "Очистка проекта")}>🧹 Очистка</ActionButton>
      <ActionButton className="btn ghost" title="docker compose config" onClick={async () => {
        const r = await api(`/projects/${p.id}/config`);
        setShowConfig((r.ok ? "" : "# ОШИБКА\n") + r.output);
      }}>Проверить конфиг</ActionButton>
      {showConfig !== null && (
        <Modal title="docker compose config" onClose={() => setShowConfig(null)} wide>
          <Editor value={showConfig} readOnly filename="config.yml" />
        </Modal>
      )}
    </div>
  );
}

function EnvSelector({ p, onChange }: { p: any; onChange: () => void }) {
  const { can } = useAuth();
  const files = useFetch<any>(() => api(`/projects/${p.id}/env-files`), [p.id, p.env_file]);
  const list: string[] = files.data?.files || [];
  return (
    <div className="env-bar">
      <span className="muted">Активный env-файл:</span>
      <select
        disabled={!can("operator")}
        value={p.env_file}
        onChange={async (e) => {
          try {
            await api(`/projects/${p.id}/env`, { body: { path: e.target.value } });
            toast(`Env: ${e.target.value || "не используется"}. Примените: Up / Деплой`);
            onChange();
          } catch (err) {
            toastErr(err);
          }
        }}
      >
        <option value="">— не используется —</option>
        {list.map((f) => <option key={f} value={f}>{f}</option>)}
        {p.env_file && !list.includes(p.env_file) && <option value={p.env_file}>{p.env_file} (не найден)</option>}
      </select>
      <span className="muted small">compose: {p.compose_files}</span>
    </div>
  );
}

function ServicesTab({ p, runAction, refreshKey }: { p: any; runAction: any; refreshKey: number }) {
  const { can } = useAuth();
  const s = useFetch<any>(() => api(`/projects/${p.id}/services`), [p.id, refreshKey], 5000);
  if (!s.data) return <Loading error={s.error} loading />;
  const d = s.data;
  return (
    <div>
      {d.config_error && <div className="alert err"><b>Ошибка compose:</b> <pre>{d.config_error}</pre></div>}
      {d.docker_error && <div className="alert err">{d.docker_error}</div>}
      {!d.services.length && !d.config_error && <div className="empty">Сервисов нет</div>}
      {d.services.length > 0 && (
        <table className="table">
          <thead>
            <tr><th>Сервис</th><th>Контейнер</th><th>Статус</th><th>Порты</th><th>Образ</th><th /></tr>
          </thead>
          <tbody>
            {d.services.map((svc: any) => {
              const cs = svc.containers.length ? svc.containers : [null];
              return cs.map((c: any, i: number) => (
                <tr key={svc.name + i}>
                  <td><b>{i === 0 ? svc.name : ""}</b></td>
                  <td>{c ? <Link to={`/containers/${c.id}`}>{c.name}</Link> : <span className="muted">—</span>}</td>
                  <td>
                    <StateBadge state={c?.state} />
                    {c && <div className="muted small">{c.status}</div>}
                  </td>
                  <td>{c ? <Ports ports={c.ports} /> : null}</td>
                  <td className="small mono">{c?.image}</td>
                  <td className="actions">
                    {can("operator") && i === 0 && (
                      <>
                        <ActionButton className="btn sm" disabled={p.busy} title="up -d" onClick={() => runAction("up", { service: svc.name }, `Up ${svc.name}`)}>▶</ActionButton>
                        <ActionButton className="btn sm" disabled={p.busy} title="restart" onClick={() => runAction("restart", { service: svc.name }, `Restart ${svc.name}`)}>⟳</ActionButton>
                        <ActionButton className="btn sm" disabled={p.busy} title="stop" onClick={() => runAction("stop", { service: svc.name }, `Stop ${svc.name}`)}>⏸</ActionButton>
                        <ActionButton className="btn sm" disabled={p.busy} title="build + recreate" onClick={() => runAction("rebuild", { service: svc.name }, `Rebuild ${svc.name}`)}>🔨</ActionButton>
                      </>
                    )}
                    {c && <Link className="btn sm" to={`/containers/${c.id}?tab=logs`}>Логи</Link>}
                    {c && can("operator") && c.state === "running" && <Link className="btn sm" to={`/containers/${c.id}?tab=shell`}>Shell</Link>}
                  </td>
                </tr>
              ));
            })}
          </tbody>
        </table>
      )}
    </div>
  );
}

// ---------- Logs (all services) ----------
function ProjectLogs({ p }: { p: any }) {
  const s = useFetch<any>(() => api(`/projects/${p.id}/services`), [p.id]);
  const names: string[] = (s.data?.services || []).map((x: any) => x.name);
  const [selected, setSelected] = useState<string[]>([]);
  const [tail, setTail] = useState("200");
  const [ts, setTs] = useState(false);
  const [key, setKey] = useState(0);
  const toggle = (n: string) => setSelected((cur) => (cur.includes(n) ? cur.filter((x) => x !== n) : [...cur, n]));

  return (
    <div>
      <div className="row wrap mb">
        <span className="muted">Сервисы:</span>
        <button className={`btn sm ${selected.length === 0 ? "primary" : ""}`} onClick={() => setSelected([])}>все</button>
        {names.map((n) => (
          <button key={n} className={`btn sm ${selected.includes(n) ? "primary" : ""}`} onClick={() => toggle(n)}>{n}</button>
        ))}
        <span className="muted">строк:</span>
        <select value={tail} onChange={(e) => setTail(e.target.value)}>
          {["50", "200", "1000", "5000", "all"].map((t) => <option key={t}>{t}</option>)}
        </select>
        <label className="check"><input type="checkbox" checked={ts} onChange={(e) => setTs(e.target.checked)} />время</label>
        <button className="btn sm" onClick={() => setKey((k) => k + 1)}>Переподключить</button>
      </div>
      <XTerm
        key={key}
        url={wsUrl(`/projects/${p.id}/logs`, { tail, timestamps: ts ? "1" : "0", services: selected.join(",") })}
        mode="stream"
        height="68vh"
      />
    </div>
  );
}

// ---------- Env ----------
function EnvTab({ p, onChange }: { p: any; onChange: () => void }) {
  const files = useFetch<any>(() => api(`/projects/${p.id}/env-files`), [p.id]);
  const [sel, setSel] = useState<string | null>(null);
  const [content, setContent] = useState("");
  const [orig, setOrig] = useState("");
  const list: string[] = files.data?.files || [];

  useEffect(() => {
    if (sel === null && list.length) setSel(p.env_file && list.includes(p.env_file) ? p.env_file : list[0]);
  }, [list.join(",")]);

  useEffect(() => {
    if (!sel) return;
    api(`/projects/${p.id}/files?path=${encodeURIComponent(sel)}`)
      .then((r) => {
        setContent(r.content);
        setOrig(r.content);
      })
      .catch(toastErr);
  }, [sel]);

  const create = async () => {
    const name = prompt("Имя нового env-файла", ".env.production");
    if (!name) return;
    const base = sel ? confirm(`Скопировать содержимое из ${sel}?`) : false;
    await api(`/projects/${p.id}/files`, { method: "PUT", body: { path: name, content: base ? content : "" } });
    await files.reload();
    setSel(name);
  };

  return (
    <div className="split">
      <div className="side-list">
        {list.map((f) => (
          <div key={f} className={`side-item ${sel === f ? "active" : ""}`} onClick={() => setSel(f)}>
            <span>{f}</span>
            {p.env_file === f && <span className="badge green">активен</span>}
          </div>
        ))}
        {!list.length && <div className="muted pad">env-файлов не найдено</div>}
        <ActionButton className="btn full" onClick={create}>+ Новый env-файл</ActionButton>
      </div>
      <div className="grow">
        {sel && (
          <>
            <div className="row between mb">
              <b className="mono">{sel}{content !== orig && " •"}</b>
              <div className="row">
                {p.env_file !== sel && (
                  <ActionButton onClick={async () => {
                    await api(`/projects/${p.id}/env`, { body: { path: sel } });
                    toast(`Активный env: ${sel}`);
                    onChange();
                  }}>Сделать активным</ActionButton>
                )}
                <ActionButton className="btn danger" confirm={`Удалить ${sel}?`} onClick={async () => {
                  await api(`/projects/${p.id}/files?path=${encodeURIComponent(sel)}`, { method: "DELETE" });
                  setSel(null);
                  files.reload();
                  onChange();
                }}>Удалить</ActionButton>
                <ActionButton className="btn primary" disabled={content === orig} onClick={async () => {
                  await api(`/projects/${p.id}/files`, { method: "PUT", body: { path: sel, content } });
                  setOrig(content);
                  toast("Сохранено. Чтобы применить — Up или Деплой");
                }}>Сохранить</ActionButton>
              </div>
            </div>
            <Editor value={content} onChange={setContent} filename={sel} />
          </>
        )}
      </div>
    </div>
  );
}

// ---------- Files ----------
function FilesTab({ p }: { p: any }) {
  const [dir, setDir] = useState("");
  const [file, setFile] = useState<string | null>(null);
  const [content, setContent] = useState("");
  const [orig, setOrig] = useState("");
  const [binary, setBinary] = useState(false);
  const listing = useFetch<any>(() => api(`/projects/${p.id}/files?path=${encodeURIComponent(dir)}`), [p.id, dir]);

  const open = async (path: string) => {
    try {
      const r = await api(`/projects/${p.id}/files?path=${encodeURIComponent(path)}`);
      setFile(path);
      setBinary(r.binary);
      setContent(r.content);
      setOrig(r.content);
    } catch (e) {
      toastErr(e);
    }
  };
  const join = (name: string) => (dir ? `${dir}/${name}` : name);
  const crumbs = dir ? dir.split("/") : [];

  return (
    <div className="split">
      <div className="side-list files">
        <div className="crumbs">
          <a onClick={() => setDir("")}>/</a>
          {crumbs.map((c, i) => (
            <span key={i}> <a onClick={() => setDir(crumbs.slice(0, i + 1).join("/"))}>{c}</a> /</span>
          ))}
        </div>
        <div className="row mb">
          <ActionButton className="btn sm" onClick={async () => {
            const n = prompt("Имя файла");
            if (!n) return;
            await api(`/projects/${p.id}/files`, { method: "PUT", body: { path: join(n), content: "" } });
            listing.reload();
            open(join(n));
          }}>+ Файл</ActionButton>
          <ActionButton className="btn sm" onClick={async () => {
            const n = prompt("Имя папки");
            if (!n) return;
            await api(`/projects/${p.id}/files/mkdir`, { body: { path: join(n) } });
            listing.reload();
          }}>+ Папка</ActionButton>
        </div>
        <Loading error={listing.error} loading={listing.loading && !listing.data} />
        {dir && <div className="side-item" onClick={() => setDir(crumbs.slice(0, -1).join("/"))}>⬆ ..</div>}
        {(listing.data?.entries || []).map((e: any) => (
          <div key={e.path} className={`side-item ${file === e.path ? "active" : ""}`}
            onClick={() => (e.type === "dir" ? setDir(e.path) : open(e.path))}>
            <span>{e.type === "dir" ? "📁" : "📄"} {e.name}</span>
            <span className="muted small">{e.type === "file" ? fmtBytes(e.size) : ""}</span>
          </div>
        ))}
      </div>
      <div className="grow">
        {file ? (
          <>
            <div className="row between mb">
              <b className="mono">{file}{content !== orig && " •"}</b>
              <div className="row">
                <ActionButton className="btn" onClick={async () => {
                  const n = prompt("Новый путь", file);
                  if (!n || n === file) return;
                  await api(`/projects/${p.id}/files/rename`, { body: { path: file, new_path: n } });
                  setFile(n);
                  listing.reload();
                }}>Переименовать</ActionButton>
                <ActionButton className="btn danger" confirm={`Удалить ${file}?`} onClick={async () => {
                  await api(`/projects/${p.id}/files?path=${encodeURIComponent(file)}`, { method: "DELETE" });
                  setFile(null);
                  listing.reload();
                }}>Удалить</ActionButton>
                <ActionButton className="btn primary" disabled={binary || content === orig} onClick={async () => {
                  await api(`/projects/${p.id}/files`, { method: "PUT", body: { path: file, content } });
                  setOrig(content);
                  toast("Сохранено");
                }}>Сохранить</ActionButton>
              </div>
            </div>
            {binary ? <div className="empty">Бинарный файл — редактирование недоступно</div> : <Editor value={content} onChange={setContent} filename={file} />}
          </>
        ) : (
          <div className="empty">Выберите файл слева</div>
        )}
      </div>
    </div>
  );
}

// ---------- Git ----------
function GitTab({ p, startJob, refreshKey }: { p: any; startJob: (id: number, t: string) => void; refreshKey: number }) {
  const { can } = useAuth();
  const st = useFetch<any>(() => api(`/projects/${p.id}/git/status`), [p.id, refreshKey]);
  const isRepo = st.data?.is_repo;
  const br = useFetch<any>(() => (isRepo ? api(`/projects/${p.id}/git/branches`) : Promise.resolve(null)), [p.id, isRepo, refreshKey]);
  const log = useFetch<any[]>(() => (isRepo ? api(`/projects/${p.id}/git/log?n=30`) : Promise.resolve([])), [p.id, isRepo, refreshKey]);
  const [branch, setBranch] = useState("");

  if (!st.data) return <Loading error={st.error} loading />;
  const s = st.data;
  if (!s.is_repo)
    return (
      <div className="empty">
        Репозиторий ещё не склонирован ({p.repo_url}).
        {can("admin") && (
          <div className="mt">
            <ActionButton className="btn primary" onClick={async () => startJob((await api(`/projects/${p.id}/git/clone`, { method: "POST" })).job_id, "git clone")}>
              Клонировать
            </ActionButton>
          </div>
        )}
      </div>
    );

  const branches: string[] = Array.from(new Set([...(br.data?.local || []), ...(br.data?.remote || [])])).sort();
  return (
    <div className="stack">
      <div className="card">
        <div className="row between wrap">
          <div className="stack-sm">
            <div>Ветка: <b>⎇ {s.branch}</b> {s.upstream && <span className="muted">→ {s.upstream}</span>}</div>
            {s.commit?.short && (
              <div className="small">
                <span className="mono">{s.commit.short}</span> {s.commit.subject} <span className="muted">— {s.commit.author}, {fmtAgo(s.commit.date)}</span>
              </div>
            )}
            <div className="row small">
              {s.behind != null && <span className={`chip ${s.behind ? "yellow" : "green"}`}>отстаёт: {s.behind}</span>}
              {s.ahead != null && <span className="chip">впереди: {s.ahead}</span>}
              <span className={`chip ${s.changes.length ? "yellow" : ""}`}>локальных изменений: {s.changes.length}</span>
            </div>
          </div>
          {can("operator") && (
            <div className="row wrap">
              <ActionButton onClick={async () => { st.setData(await api(`/projects/${p.id}/git/fetch`, { method: "POST" })); br.reload(); log.reload(); toast("Fetch выполнен"); }}>Fetch</ActionButton>
              <ActionButton className="btn primary" disabled={p.busy} onClick={async () => startJob((await api(`/projects/${p.id}/git/pull`, { method: "POST" })).job_id, "git pull")}>Pull</ActionButton>
              <select value={branch} onChange={(e) => setBranch(e.target.value)}>
                <option value="">сменить ветку…</option>
                {branches.map((b) => <option key={b} value={b}>{b}</option>)}
              </select>
              <ActionButton disabled={!branch || branch === s.branch || p.busy} onClick={async () =>
                startJob((await api(`/projects/${p.id}/git/checkout`, { body: { branch } })).job_id, `checkout ${branch}`)}>Checkout</ActionButton>
              {can("admin") && (
                <ActionButton className="btn danger" disabled={p.busy}
                  confirm="Сбросить все локальные изменения до состояния удалённой ветки (git reset --hard)? Неотслеживаемые файлы (.env) останутся."
                  onClick={async () => startJob((await api(`/projects/${p.id}/git/reset`, { method: "POST" })).job_id, "git reset --hard")}>Reset --hard</ActionButton>
              )}
            </div>
          )}
        </div>
        {s.changes.length > 0 && <pre className="mt small">{s.changes.join("\n")}</pre>}
      </div>
      <table className="table">
        <thead><tr><th>Коммит</th><th>Сообщение</th><th>Автор</th><th>Дата</th></tr></thead>
        <tbody>
          {(log.data || []).map((c) => (
            <tr key={c.hash}>
              <td className="mono">{c.short}</td><td>{c.subject}</td><td>{c.author}</td><td className="muted small">{fmtDate(c.date)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------- Jobs ----------
function ProjectJobs({ p, open, refreshKey }: { p: any; open: (id: number, t: string) => void; refreshKey: number }) {
  const jobs = useFetch<any[]>(() => api(`/jobs?project_id=${p.id}&limit=50`), [p.id, refreshKey], 10000);
  return (
    <table className="table">
      <thead><tr><th>#</th><th>Действие</th><th>Статус</th><th>Кто</th><th>Начало</th><th>Длительность</th></tr></thead>
      <tbody>
        {(jobs.data || []).map((j) => (
          <tr key={j.id} className="clickable" onClick={() => open(j.id, j.action)}>
            <td>{j.id}</td><td className="mono">{j.action}</td>
            <td>{j.status === "running" ? <span className="badge yellow">выполняется</span> : <StateBadge state={j.status} />}</td>
            <td>{j.username}</td><td className="small">{fmtDate(j.started_at)}</td>
            <td className="small">{j.finished_at ? `${Math.round((new Date(j.finished_at).getTime() - new Date(j.started_at).getTime()) / 1000)} с` : "—"}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

// ---------- Settings ----------
function SettingsTab({ p, onSaved }: { p: any; onSaved: () => void; startJob: (id: number, t: string) => void }) {
  const nav = useNavigate();
  const [f, setF] = useState({
    name: p.name, description: p.description, repo_url: p.repo_url, git_username: p.git_username,
    git_token: "", ssh_key: p.ssh_key || "", compose_files: p.compose_files, webhook_enabled: p.webhook_enabled,
  });
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const webhookUrl = (p.webhook_url.startsWith("/") ? location.origin : "") + p.webhook_url;

  return (
    <div className="stack">
      <form className="card form" onSubmit={async (e) => {
        e.preventDefault();
        try {
          await api(`/projects/${p.id}`, { method: "PATCH", body: f });
          toast("Сохранено");
          setF({ ...f, git_token: "" });
          onSaved();
        } catch (err) {
          toastErr(err);
        }
      }}>
        <h3>Основное</h3>
        <div className="cols">
          <label>Название<input value={f.name} onChange={set("name")} /></label>
          <label>Compose-файлы (через запятую)<input value={f.compose_files} onChange={set("compose_files")} /></label>
        </div>
        <label>Описание<input value={f.description} onChange={set("description")} /></label>
        <div className="muted small">Путь: <span className="mono">{p.path}</span></div>
        {p.source === "git" && (
          <>
            <h3>Git</h3>
            <label>URL репозитория<input value={f.repo_url} onChange={set("repo_url")} /></label>
            <div className="cols">
              <label>Git-пользователь<input value={f.git_username} onChange={set("git_username")} placeholder="oauth2" /></label>
              <label>
                Токен {p.has_token && <span className="badge green">сохранён</span>}
                <input type="password" value={f.git_token} onChange={set("git_token")} placeholder={p.has_token ? "оставьте пустым, чтобы не менять" : ""} autoComplete="new-password" />
              </label>
            </div>
            <label>
              SSH-ключ (для git@… URL)
              <SshKeySelect value={f.ssh_key} onChange={(v) => setF({ ...f, ssh_key: v })} />
            </label>
            {p.has_token && (
              <ActionButton className="btn sm ghost" confirm="Удалить сохранённый токен?" onClick={async () => {
                await api(`/projects/${p.id}`, { method: "PATCH", body: { clear_token: true } });
                onSaved();
              }}>Удалить токен</ActionButton>
            )}
            <h3>Вебхук (авто-деплой при push)</h3>
            <label className="check"><input type="checkbox" checked={f.webhook_enabled} onChange={set("webhook_enabled")} /> Включён</label>
            <div className="hint">
              URL: <span className="mono">{webhookUrl}</span><br />
              Секрет: <span className="mono">{p.webhook_secret}</span><br />
              GitLab: поле «Secret token». GitHub/Gitea: «Secret», тип application/json. Деплой срабатывает только для ветки <b>{p.branch || "любой"}</b>.
            </div>
            <ActionButton className="btn sm ghost" confirm="Сгенерировать новый секрет? Старый перестанет работать." onClick={async () => {
              await api(`/projects/${p.id}`, { method: "PATCH", body: { regenerate_webhook: true } });
              onSaved();
            }}>Новый секрет</ActionButton>
          </>
        )}
        <div className="row end"><button className="btn primary">Сохранить</button></div>
      </form>

      <div className="card danger-zone">
        <h3>Удаление проекта</h3>
        <div className="row wrap">
          <ActionButton className="btn danger" confirm="Удалить проект из менеджера? Контейнеры и файлы останутся." onClick={async () => {
            await api(`/projects/${p.id}`, { method: "DELETE" });
            nav("/");
          }}>Удалить из менеджера</ActionButton>
          <ActionButton className="btn danger" confirm="Выполнить docker compose down и удалить проект? Файлы останутся." onClick={async () => {
            await api(`/projects/${p.id}?compose_down=true`, { method: "DELETE" });
            nav("/");
          }}>Down + удалить</ActionButton>
          {p.managed && (
            <ActionButton className="btn danger" confirm="Выполнить down, удалить проект И ВСЕ ЕГО ФАЙЛЫ на сервере? Это необратимо." onClick={async () => {
              await api(`/projects/${p.id}?compose_down=true&remove_files=true`, { method: "DELETE" });
              nav("/");
            }}>Down + удалить вместе с файлами</ActionButton>
          )}
        </div>
      </div>
    </div>
  );
}

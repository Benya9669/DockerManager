import { t, tf } from "../i18n";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { api, wsUrl } from "../api";
import { XTerm } from "../XTerm";
import { ProjectMonitoring } from "../Monitoring";
import { ServerPicker } from "../server";
import { atLeast, useAuth } from "../auth";
import { DraftEditor, isEnv, useDraft } from "../FileDraft";
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
  const tab = sp.get("tab") || "overview";
  const [jobId, setJobId] = useState<number | null>(sp.get("job") ? Number(sp.get("job")) : null);
  const [jobTitle, setJobTitle] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);

  const changeTab = (t: string) => {
    const next = new URLSearchParams(sp);
    next.set("tab", t);
    setSp(next, { replace: true });
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
          <div className="muted small"><Link to="/">{t("Проекты")}</Link> /</div>
          <h1>{p.name} {p.environment && <span className={`badge ${p.environment === "production" ? "red" : "gray"}`}>{p.environment}</span>} <span className="muted small">{p.slug}</span></h1>
          {p.server_name && <div className="small">{t("🖥 Хост:")} <b>{p.server_name}</b></div>}
          {p.description && <div className="muted">{p.description}</div>}
        </div>
        {atLeast(p.my_role, "operator") && <ProjectToolbar p={p} runAction={runAction} />}
      </div>

      {!!p.pending_config?.length && <details className="card"><summary>{t("Есть неприменённые изменения конфигурации")}</summary>
        <ul>{p.pending_config.map((name:string) => <li key={name}><code>{name}</code></li>)}</ul>
        <ActionButton disabled={p.busy} onClick={async () => {
          const result = await api(`/projects/${p.id}/config`);
          if (!result.ok) throw Error(result.output);
          await runAction("up", {}, t("Применить конфигурацию"));
        }}>{t("Проверить и применить")}</ActionButton></details>}
      <EnvSelector p={p} onChange={proj.reload} />

      {jobId && (
        <JobPanel
          jobId={jobId}
          title={jobTitle}
          onClose={() => setJobId(null)}
          onDone={(s) => {
            proj.reload();
            setRefreshKey((k) => k + 1);
            toast(`${jobTitle || t("Задача")}: ${s === "success" ? t("успешно") : s}`, s === "success" ? "ok" : "err");
          }}
        />
      )}

      <Tabs
        active={tab}
        onChange={changeTab}
        tabs={[
          ["overview", t("Сервисы")],
          ["logs", t("Логи")],
          ["monitoring", t("Мониторинг")],
          ...(atLeast(p.my_role, "operator") ? ([["env", t("Переменные (.env)")], ["files", t("Файлы")]] as [string, string][]) : []),
          ...(p.source === "git" ? ([["git", "Git"]] as [string, string][]) : []),
          ["deploys", t("Деплои")],
          ["jobs", t("История")],
          ...(can("admin") ? ([["settings", t("Настройки")]] as [string, string][]) : []),
        ]}
      />
      <div className="tab-body">
        {tab === "overview" && <ServicesTab p={p} runAction={runAction} refreshKey={refreshKey} />}
        {tab === "logs" && <ProjectLogs p={p} />}
        {tab === "monitoring" && <ProjectMonitoring projectId={p.id} />}
        {tab === "env" && <EnvTab key={p.id} p={p} onChange={proj.reload} />}
        {tab === "files" && <FilesTab key={p.id} p={p} />}
        {tab === "git" && <GitTab p={p} startJob={startJob} refreshKey={refreshKey} />}
        {tab === "deploys" && <DeploymentsTab p={p} open={startJob} refreshKey={refreshKey} />}
        {tab === "jobs" && <ProjectJobs p={p} open={startJob} refreshKey={refreshKey} />}
        {tab === "settings" && <SettingsTab p={p} onSaved={proj.reload} startJob={startJob} />}
      </div>
    </div>
  );
}

function ProjectToolbar({ p, runAction }: { p: any; runAction: (a: string, body?: any, t?: string) => Promise<void> }) {
  const [noCache, setNoCache] = useState(false);
  const [preview, setPreview] = useState(false);
  const [showConfig, setShowConfig] = useState<string | null>(null);
  const dis = p.busy;
  return (
    <div className="toolbar">
      <button className="btn primary" disabled={dis} title={t("предпросмотр изменений → деплой с проверкой здоровья и автооткатом")}
        onClick={() => setPreview(true)}>{t("🚀 Деплой")}</button>
      {preview && (
        <DeployPreview p={p} noCache={noCache} onClose={() => setPreview(false)}
          onDeploy={async () => { setPreview(false); await runAction("deploy", { no_cache: noCache }, t("Деплой")); }} />
      )}
      <ActionButton disabled={dis} onClick={() => runAction("up", {}, t("Запуск (up -d)"))}>▶ Up</ActionButton>
      <div className="btn-group">
        <ActionButton disabled={dis} title="docker compose build --pull" onClick={() => runAction("build", { no_cache: noCache }, t("Сборка"))}>🔨 Build</ActionButton>
        <ActionButton disabled={dis} title={t("build + пересоздание контейнеров")} onClick={() => runAction("rebuild", { no_cache: noCache }, t("Пересборка"))}>♻ Rebuild</ActionButton>
        <label className="check" title="--no-cache"><input type="checkbox" checked={noCache} onChange={(e) => setNoCache(e.target.checked)} />{t("без кэша")}</label>
      </div>
      <ActionButton disabled={dis} onClick={() => runAction("restart", {}, t("Перезапуск"))}>⟳ Restart</ActionButton>
      <ActionButton disabled={dis} onClick={() => runAction("pull", {}, t("Pull образов"))}>⬇ Pull</ActionButton>
      <ActionButton disabled={dis} onClick={() => runAction("stop", {}, t("Остановка"))}>⏸ Stop</ActionButton>
      <ActionButton disabled={dis} className="btn danger" confirm={[p.name, p.environment, p.server_name || t("Локальный"), t("Остановить и удалить контейнеры проекта (docker compose down)?")].filter(Boolean).join(" · ")}
        onClick={() => runAction("down", {}, "Down")}>⏹ Down</ActionButton>
      <ActionButton disabled={dis} title={t("удалить остановленные контейнеры и старые образы проекта")}
        confirm={t("Удалить остановленные контейнеры проекта и неиспользуемые образы, собранные для него?")}
        onClick={() => runAction("cleanup", {}, t("Очистка проекта"))}>{t("🧹 Очистка")}</ActionButton>
      <ActionButton className="btn ghost" title="docker compose config" onClick={async () => {
        const r = await api(`/projects/${p.id}/config`);
        setShowConfig((r.ok ? "" : `# ${t("ОШИБКА")}\n`) + r.output);
      }}>{t("Проверить конфиг")}</ActionButton>
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
      <span className="muted">{t("Активный env-файл:")}</span>
      <select
        disabled={!atLeast(p.my_role, "operator")}
        value={p.env_file}
        onChange={async (e) => {
          try {
            await api(`/projects/${p.id}/env`, { body: { path: e.target.value } });
            toast(tf("Env: {0}. Примените: Up / Деплой", e.target.value || t("не используется")));
            onChange();
          } catch (err) {
            toastErr(err);
          }
        }}
      >
        <option value="">{t("— не используется —")}</option>
        {list.map((f) => <option key={f} value={f}>{f}</option>)}
        {p.env_file && !list.includes(p.env_file) && <option value={p.env_file}>{p.env_file} {t("(не найден)")}</option>}
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
      {d.config_error && <div className="alert err"><b>{t("Ошибка compose:")}</b> <pre>{d.config_error}</pre></div>}
      {d.docker_error && <div className="alert err">{d.docker_error}</div>}
      {!d.services.length && !d.config_error && <div className="empty">{t("Сервисов нет")}</div>}
      {d.services.length > 0 && (
        <table className="table">
          <thead>
            <tr><th>{t("Сервис")}</th><th>{t("Контейнер")}</th><th>{t("Статус")}</th><th>{t("Порты")}</th><th>{t("Образ")}</th><th /></tr>
          </thead>
          <tbody>
            {d.services.map((svc: any) => {
              const cs = svc.containers.length ? svc.containers : [null];
              return cs.map((c: any, i: number) => (
                <tr key={svc.name + i}>
                  <td><b>{i === 0 ? svc.name : ""}</b></td>
                  <td>{c ? <Link to={`/containers/${c.id}${p.server_id ? `?server=${p.server_id}` : ""}`}>{c.name}</Link> : <span className="muted">—</span>}</td>
                  <td>
                    <StateBadge state={c?.state} />
                    {c && <div className="muted small">{c.status}</div>}
                  </td>
                  <td>{c ? <Ports ports={c.ports} /> : null}</td>
                  <td className="small mono">{c?.image}</td>
                  <td className="actions">
                    {atLeast(p.my_role, "operator") && i === 0 && (
                      <>
                        <ActionButton className="btn sm" disabled={p.busy} title="up -d" onClick={() => runAction("up", { service: svc.name }, `Up ${svc.name}`)}>▶</ActionButton>
                        <ActionButton className="btn sm" disabled={p.busy} title="restart" onClick={() => runAction("restart", { service: svc.name }, `Restart ${svc.name}`)}>⟳</ActionButton>
                        <ActionButton className="btn sm" disabled={p.busy} title="stop" onClick={() => runAction("stop", { service: svc.name }, `Stop ${svc.name}`)}>⏸</ActionButton>
                        <ActionButton className="btn sm" disabled={p.busy} title="build + recreate" onClick={() => runAction("rebuild", { service: svc.name }, `Rebuild ${svc.name}`)}>🔨</ActionButton>
                      </>
                    )}
                    {c && <Link className="btn sm" to={`/containers/${c.id}?tab=logs${p.server_id ? `&server=${p.server_id}` : ""}`}>{t("Логи")}</Link>}
                    {c && atLeast(p.my_role, "operator") && c.state === "running" && <Link className="btn sm" to={`/containers/${c.id}?tab=shell${p.server_id ? `&server=${p.server_id}` : ""}`}>Shell</Link>}
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

// ---------- Deploy preview ----------
function DeployPreview({ p, noCache, onClose, onDeploy }: { p: any; noCache: boolean; onClose: () => void; onDeploy: () => Promise<void> }) {
  const pv = useFetch<any>(() => api(`/projects/${p.id}/deploy-preview`), [p.id]);
  const d = pv.data;
  const g = d?.git;
  return (
    <Modal title={tf("Деплой: {0}", p.name)} onClose={onClose} wide>
      <div className="stack">
        <Loading error={pv.error} loading={pv.loading && !d} />
        {d && (
          <>
            {g?.error && <div className="alert err">git: {g.error}</div>}
            {g && !g.error && (
              g.commits.length ? (
                <div className="stack-sm">
                  <b>{t("Придут коммиты (")}{g.commits.length}{t("), изменено файлов:")} {g.files_changed}</b>
                  <table className="table">
                    <tbody>
                      {g.commits.map((c: any) => (
                        <tr key={c.hash}><td className="mono">{c.short}</td><td>{c.subject}</td><td className="muted small">{c.author}, {fmtAgo(c.date)}</td></tr>
                      ))}
                    </tbody>
                  </table>
                  {g.stat && <pre className="small">{g.stat}</pre>}
                  {g.compose_diff && (
                    <>
                      <b>{t("Изменения compose-файлов")}</b>
                      <Editor value={g.compose_diff} readOnly filename="changes.diff" height="30vh" />
                    </>
                  )}
                </div>
              ) : <div className="hint">{t("Новых коммитов нет: будут обновлены образы и пересозданы изменившиеся контейнеры.")}</div>
            )}
            {d.source !== "git" && <div className="hint">{t("Проект без git: деплой = pull образов + build + up.")}</div>}
            {d.local_changes?.length > 0 && (
              <div className="alert err">
                {t("Локальные изменения в репозитории (")}{d.local_changes.length}{t("). Pull может не пройти, если они конфликтуют:")}
                <pre className="small">{d.local_changes.join("\n")}</pre>
              </div>
            )}
            {d.config_ok === false && <div className="alert err"><b>{t("compose config с ошибкой:")}</b><pre className="small">{d.config_error}</pre></div>}
            <div className="hint">
              {t("После деплоя панель ждёт до")} {p.health_timeout ?? 90} {t("с, пока контейнеры станут здоровыми.")}{" "}
              {p.auto_rollback ? t("Если не станут — автоматически откатит к текущей версии.") : t("Автооткат выключен в настройках проекта.")}
              {noCache && t(" Сборка без кэша.")}
            </div>
          </>
        )}
        <div className="row end">
          <button className="btn ghost" onClick={onClose}>{t("Отмена")}</button>
          <ActionButton className="btn primary" disabled={!d} onClick={onDeploy}>{t("🚀 Запустить деплой")}</ActionButton>
        </div>
      </div>
    </Modal>
  );
}

// ---------- Deployments history ----------
function DeploymentsTab({ p, open, refreshKey }: { p: any; open: (id: number, t: string) => void; refreshKey: number }) {
  const { can } = useAuth();
  const list = useFetch<any[]>(() => api(`/projects/${p.id}/deployments`), [p.id, refreshKey], 10000);
  const label: Record<string, [string, string]> = {
    success: ["green", t("успешно")], failed: ["red", t("ошибка")], rolled_back: ["yellow", t("откачен")], running: ["yellow", t("идёт")],
  };
  const latestOk = (list.data || []).find((d) => d.status === "success");
  return (
    <div className="stack">
      <div className="hint">
        {t("Перед каждым деплоем сохраняется снимок: коммит, compose-файлы, активный .env и ID образов. Можно вернуть проект к состоянию после любого успешного деплоя.")}
      </div>
      <Loading error={list.error} loading={list.loading && !list.data} />
      {list.data && !list.data.length && <div className="empty">{t("Деплоев ещё не было")}</div>}
      {!!list.data?.length && (
        <table className="table">
          <thead><tr><th>#</th><th>{t("Тип")}</th><th>{t("Статус")}</th><th>{t("Коммит")}</th><th>{t("Кто")}</th><th>{t("Когда")}</th><th /></tr></thead>
          <tbody>
            {list.data.map((d) => {
              const [cls, text] = label[d.status] || ["gray", d.status];
              return (
                <tr key={d.id}>
                  <td>{d.id}</td>
                  <td>{d.kind === "rollback" ? t("откат") : t("деплой")}{d.diagnostics && <details><summary>{t("Причина сбоя и логи")}</summary><pre className="small">{d.diagnostics}</pre></details>}{d.message && <div className="muted small">{d.message}</div>}</td>
                  <td><span className={`badge ${cls}`}>{text}</span>{latestOk?.id === d.id && <span className="badge green" style={{ marginLeft: 4 }}>{t("текущий")}</span>}</td>
                  <td className="mono small">{d.commit_before ? d.commit_before.slice(0, 8) : "—"}{d.commit_after && d.commit_after !== d.commit_before && ` → ${d.commit_after.slice(0, 8)}`}</td>
                  <td>{d.username}</td>
                  <td className="small">{fmtDate(d.created_at)}</td>
                  <td className="actions">
                    {d.job_id && <button className="btn sm" onClick={() => open(d.job_id, tf("деплой #{0}", d.id))}>{t("Лог")}</button>}
                    {atLeast(p.my_role, "operator") && d.can_rollback && latestOk?.id !== d.id && (
                      <ActionButton className="btn sm" disabled={p.busy} confirm={tf("Вернуть проект к состоянию деплоя #{0}?", d.id)}
                        onClick={async () => open((await api(`/projects/${p.id}/deployments/${d.id}/rollback`, { method: "POST" })).job_id, tf("откат к #{0}", d.id))}>
                        {t("↺ Откатить сюда")}
                      </ActionButton>
                    )}
                  </td>
                </tr>
              );
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
  const [params, setParams] = useSearchParams();
  const cid = params.get("container"), at = params.get("at");
  const context = useFetch<any>(() => cid && at ? api(`/projects/${p.id}/logs/context?${new URLSearchParams({container:cid, at})}`) : Promise.resolve(null), [p.id, cid, at]);
  const [selected, setSelected] = useState<string[]>(() => params.get("service") ? [params.get("service")!] : []);
  const [tail, setTail] = useState("200");
  const [ts, setTs] = useState(true);
  const [key, setKey] = useState(0);
  const toggle = (n: string) => setSelected((cur) => (cur.includes(n) ? cur.filter((x) => x !== n) : [...cur, n]));

  return (
    <div>
      <div className="row wrap mb">
        <span className="muted">{t("Сервисы:")}</span>
        <button className={`btn sm ${selected.length === 0 ? "primary" : ""}`} onClick={() => setSelected([])}>{t("все")}</button>
        {names.map((n) => (
          <button key={n} className={`btn sm ${selected.includes(n) ? "primary" : ""}`} onClick={() => toggle(n)}>{n}</button>
        ))}
        <span className="muted">{t("строк:")}</span>
        <select value={tail} onChange={(e) => setTail(e.target.value)}>
          {["50", "200", "1000", "5000", "all"].map((t) => <option key={t}>{t}</option>)}
        </select>
        <label className="check"><input type="checkbox" checked={ts} onChange={(e) => setTs(e.target.checked)} />{t("время")}</label>
        <button className="btn sm" onClick={() => setKey((k) => k + 1)}>{t("Переподключить")}</button>
      </div>
      {cid && at && <div className="card"><div className="row between"><b>{t("Контекст события")}</b><div>
        <ActionButton onClick={() => navigator.clipboard.writeText(location.href)}>{t("Копировать ссылку")}</ActionButton>
        <button className="btn" onClick={() => {const next = new URLSearchParams(params); next.delete("container"); next.delete("at"); setParams(next);}}>×</button></div></div>
        <Loading loading={context.loading} error={context.error}/>{!context.error && !context.loading && context.data && <pre>{context.data.before.join("\n")}{"\n"}<mark>{context.data.line}</mark>{"\n"}{context.data.after.join("\n")}</pre>}</div>}
      <XTerm
        onContext={line => {
          const match = /^\s*(\S+)\s*\|\s*(\d{4}-\d\d-\d\dT[\d:.]+Z)/.exec(line);
          if (!match) return toast(t("Для контекста включите время и выберите строку лога"), "err");
          const containers = (s.data?.services || []).flatMap((svc:any) => svc.containers || []);
          const c = containers.find((item:any) => item.name === match[1] || item.name === p.slug + "-" + match[1] || item.name === p.slug + "_" + match[1]);
          if (!c) return toast(t("Контейнер больше недоступен"), "err");
          const next = new URLSearchParams(params); next.set("tab","logs"); next.set("service",c.service); next.set("container",c.id); next.set("at",match[2]); setParams(next);
        }}
        key={key}
        url={wsUrl(`/projects/${p.id}/logs`, { tail, timestamps: ts ? "1" : "0", services: selected.join(",") })}
        mode="stream"
        height="68vh"
        download={{
          path: `/projects/${p.id}/logs/download?tail=${tail}&timestamps=${ts ? 1 : 0}&services=${encodeURIComponent(selected.join(","))}`,
          filename: `${p.slug}.log`,
        }}
      />
    </div>
  );
}

// ---------- Env ----------
function EnvTab({ p, onChange }: { p: any; onChange: () => void }) {
  const files = useFetch<any>(() => api(`/projects/${p.id}/env-files`), [p.id]);
  const [sel, setSel] = useState<string | null>(null);
  const draft = useDraft(p.id, sel, true);
  const { content, orig, setContent } = draft;
  const list: string[] = files.data?.files || [];

  useEffect(() => {
    if (sel === null && list.length) setSel(p.env_file && list.includes(p.env_file) ? p.env_file : list[0]);
  }, [list.join(",")]);



  const create = async () => {
    const name = prompt(t("Имя нового env-файла"), ".env.production");
    if (!name) return;
    const base = sel ? confirm(tf("Скопировать содержимое из {0}?", sel)) : false;
    await api(`/projects/${p.id}/files`, { method: "PUT", body: { path: name, revision: "missing", content: base ? content : "" } });
    await files.reload();
    setSel(name);
  };

  return (
    <div className="split">{draft.dialogs}
      <div className="side-list">
        {list.map((f) => (
          <div key={f} className={`side-item ${sel === f ? "active" : ""}`} onClick={() => sel !== f && draft.guard(() => setSel(f))}>
            <span>{f}</span>
            {p.env_file === f && <span className="badge green">{t("активен")}</span>}
          </div>
        ))}
        {!list.length && <div className="muted pad">{t("env-файлов не найдено")}</div>}
        <ActionButton className="btn full" onClick={() => draft.guard(() => { void create().catch(toastErr); })}>{t("+ Новый env-файл")}</ActionButton>
      </div>
      <div className="grow">
        {sel && draft.loaded && (
          <>
            <div className="row between mb">
              <b className="mono">{sel}{content !== orig && " •"}</b>
              <div className="row">
                {p.env_file !== sel && (
                  <ActionButton onClick={async () => {
                    await api(`/projects/${p.id}/env`, { body: { path: sel } });
                    toast(tf("Активный env: {0}", sel));
                    onChange();
                  }}>{t("Сделать активным")}</ActionButton>
                )}
                <ActionButton className="btn danger" confirm={tf("Удалить {0}?", sel)} onClick={async () => {
                  await api(`/projects/${p.id}/files?path=${encodeURIComponent(sel)}`, { method: "DELETE" });
                  setSel(null);
                  files.reload();
                  onChange();
                }}>{t("Удалить")}</ActionButton>
                <ActionButton className="btn primary" disabled={content === orig} onClick={draft.save}>{t("Сохранить")}</ActionButton>
              </div>
            </div>
            <DraftEditor key={sel} env path={sel} value={content} change={setContent} />
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
  const env = !!file && (isEnv(file) || file === p.env_file);
  const draft = useDraft(p.id, file, env);
  const {content, orig, binary, setContent} = draft;
  const listing = useFetch<any>(() => api(`/projects/${p.id}/files?path=${encodeURIComponent(dir)}`), [p.id, dir]);

  const open = (path: string) => { if (file !== path) draft.guard(() => setFile(path)); };
  const join = (name: string) => (dir ? `${dir}/${name}` : name);
  const crumbs = dir ? dir.split("/") : [];

  return (
    <div className="split">
      {draft.dialogs}<div className="side-list files">
        <div className="crumbs">
          <a onClick={() => setDir("")}>/</a>
          {crumbs.map((c, i) => (
            <span key={i}> <a onClick={() => setDir(crumbs.slice(0, i + 1).join("/"))}>{c}</a> /</span>
          ))}
        </div>
        <div className="row mb">
          <ActionButton className="btn sm" onClick={async () => {
            const n = prompt(t("Имя файла"));
            if (!n) return;
            await api(`/projects/${p.id}/files`, { method: "PUT", body: { path: join(n), content: "", revision: "missing" } });
            listing.reload();
            open(join(n));
          }}>{t("+ Файл")}</ActionButton>
          <ActionButton className="btn sm" onClick={async () => {
            const n = prompt(t("Имя папки"));
            if (!n) return;
            await api(`/projects/${p.id}/files/mkdir`, { body: { path: join(n) } });
            listing.reload();
          }}>{t("+ Папка")}</ActionButton>
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
        {file && draft.loaded ? (
          <>
            <div className="row between mb">
              <b className="mono">{file}{content !== orig && " •"}</b>
              <div className="row">
                <ActionButton className="btn" disabled={draft.dirty} onClick={async () => {
                  const n = prompt(t("Новый путь"), file);
                  if (!n || n === file) return;
                  await api(`/projects/${p.id}/files/rename`, { body: { path: file, new_path: n } });
                  setFile(n);
                  listing.reload();
                }}>{t("Переименовать")}</ActionButton>
                <ActionButton className="btn danger" confirm={tf("Удалить {0}?", file)} onClick={async () => {
                  await api(`/projects/${p.id}/files?path=${encodeURIComponent(file)}`, { method: "DELETE" });
                  setFile(null);
                  listing.reload();
                }}>{t("Удалить")}</ActionButton>
                <ActionButton className="btn primary" disabled={binary || content === orig} onClick={draft.save}>{t("Сохранить")}</ActionButton>
              </div>
            </div>
            {binary ? <div className="empty">{t("Бинарный файл — редактирование недоступно")}</div> : <DraftEditor key={file} env={env} path={file} value={content} change={setContent} />}
          </>
        ) : (
          <div className="empty">{t("Выберите файл слева")}</div>
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
        {t("Репозиторий ещё не склонирован (")}{p.repo_url}).
        {can("admin") && (
          <div className="mt">
            <ActionButton className="btn primary" onClick={async () => startJob((await api(`/projects/${p.id}/git/clone`, { method: "POST" })).job_id, "git clone")}>
              {t("Клонировать")}
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
            <div>{t("Ветка:")} <b>⎇ {s.branch}</b> {s.upstream && <span className="muted">→ {s.upstream}</span>}</div>
            {s.commit?.short && (
              <div className="small">
                <span className="mono">{s.commit.short}</span> {s.commit.subject} <span className="muted">— {s.commit.author}, {fmtAgo(s.commit.date)}</span>
              </div>
            )}
            <div className="row small">
              {s.behind != null && <span className={`chip ${s.behind ? "yellow" : "green"}`}>{t("отстаёт:")} {s.behind}</span>}
              {s.ahead != null && <span className="chip">{t("впереди:")} {s.ahead}</span>}
              <span className={`chip ${s.changes.length ? "yellow" : ""}`}>{t("локальных изменений:")} {s.changes.length}</span>
            </div>
          </div>
          {atLeast(p.my_role, "operator") && (
            <div className="row wrap">
              <ActionButton onClick={async () => { st.setData(await api(`/projects/${p.id}/git/fetch`, { method: "POST" })); br.reload(); log.reload(); toast(t("Fetch выполнен")); }}>Fetch</ActionButton>
              <ActionButton className="btn primary" disabled={p.busy} onClick={async () => startJob((await api(`/projects/${p.id}/git/pull`, { method: "POST" })).job_id, "git pull")}>Pull</ActionButton>
              <select value={branch} onChange={(e) => setBranch(e.target.value)}>
                <option value="">{t("сменить ветку…")}</option>
                {branches.map((b) => <option key={b} value={b}>{b}</option>)}
              </select>
              <ActionButton disabled={!branch || branch === s.branch || p.busy} onClick={async () =>
                startJob((await api(`/projects/${p.id}/git/checkout`, { body: { branch } })).job_id, `checkout ${branch}`)}>Checkout</ActionButton>
              {can("admin") && (
                <ActionButton className="btn danger" disabled={p.busy}
                  confirm={t("Сбросить все локальные изменения до состояния удалённой ветки (git reset --hard)? Неотслеживаемые файлы (.env) останутся.")}
                  onClick={async () => startJob((await api(`/projects/${p.id}/git/reset`, { method: "POST" })).job_id, "git reset --hard")}>Reset --hard</ActionButton>
              )}
            </div>
          )}
        </div>
        {s.changes.length > 0 && <pre className="mt small">{s.changes.join("\n")}</pre>}
      </div>
      <table className="table">
        <thead><tr><th>{t("Коммит")}</th><th>{t("Сообщение")}</th><th>{t("Автор")}</th><th>{t("Дата")}</th></tr></thead>
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
      <thead><tr><th>#</th><th>{t("Действие")}</th><th>{t("Статус")}</th><th>{t("Кто")}</th><th>{t("Начало")}</th><th>{t("Длительность")}</th></tr></thead>
      <tbody>
        {(jobs.data || []).map((j) => (
          <tr key={j.id} className="clickable" onClick={() => open(j.id, j.action)}>
            <td>{j.id}</td><td className="mono">{j.action}</td>
            <td>{j.status === "running" ? <span className="badge yellow">{t("выполняется")}</span> : <StateBadge state={j.status} />}</td>
            <td>{j.username}</td><td className="small">{fmtDate(j.started_at)}</td>
            <td className="small">{j.finished_at ? tf("{0} с", Math.round((new Date(j.finished_at).getTime() - new Date(j.started_at).getTime()) / 1000)) : "—"}</td>
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
    name: p.name, environment: p.environment || "", alerts_enabled: !!p.alerts_enabled, description: p.description, repo_url: p.repo_url, git_username: p.git_username,
    git_token: "", ssh_key: p.ssh_key || "", compose_files: p.compose_files, webhook_enabled: p.webhook_enabled,
    auto_rollback: p.auto_rollback ?? true, health_timeout: p.health_timeout ?? 90,
    server_id: (p.server_id ?? null) as number | null, set_server: false,
  });
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.type === "checkbox" ? e.target.checked : e.target.value });
  const webhookUrl = (p.webhook_url.startsWith("/") ? location.origin : "") + p.webhook_url;

  return (
    <div className="stack">
      <form className="card form" onSubmit={async (e) => {
        e.preventDefault();
        try {
          await api(`/projects/${p.id}`, { method: "PATCH", body: f });
          toast(t("Сохранено"));
          setF({ ...f, git_token: "" });
          onSaved();
        } catch (err) {
          toastErr(err);
        }
      }}>
        <h3>{t("Основное")}</h3>
        <div className="cols">
          <label>{t("Название")}<input value={f.name} onChange={set("name")} /></label>
          <label>{t("Compose-файлы (через запятую)")}<input value={f.compose_files} onChange={set("compose_files")} /></label>
        </div>
        <label>{t("Окружение")}<input value={f.environment} maxLength={32} placeholder="production / staging" onChange={set("environment")}/></label>
        <label className="check"><input type="checkbox" checked={f.alerts_enabled} onChange={set("alerts_enabled")}/>{t("Уведомления о сбое и восстановлении")}</label>
        {f.alerts_enabled && !p.alerts_configured && <div className="hint">{t("Задайте DM_ALERT_WEBHOOK или DM_TELEGRAM_TOKEN и DM_TELEGRAM_CHAT_ID в окружении панели.")}</div>}
        <label>{t("Описание")}<input value={f.description} onChange={set("description")} /></label>
        <div className="muted small">{t("Путь:")} <span className="mono">{p.path}</span></div>
        <label>
          {t("Где запускать (Docker-хост)")}
          <ServerPicker value={f.server_id} onChange={(v) => setF({ ...f, server_id: v, set_server: true })} />
        </label>
        {f.set_server && f.server_id !== p.server_id && (
          <div className="alert err">
            {t("Смена хоста не переносит контейнеры и тома: на старом хосте сделайте Down, после сохранения — Деплой на новом.")}
          </div>
        )}
        {p.source === "git" && (
          <>
            <h3>Git</h3>
            <label>{t("URL репозитория")}<input value={f.repo_url} onChange={set("repo_url")} /></label>
            <div className="cols">
              <label>{t("Git-пользователь")}<input value={f.git_username} onChange={set("git_username")} placeholder="oauth2" /></label>
              <label>
                {t("Токен")} {p.has_token && <span className="badge green">{t("сохранён")}</span>}
                <input type="password" value={f.git_token} onChange={set("git_token")} placeholder={p.has_token ? t("оставьте пустым, чтобы не менять") : ""} autoComplete="new-password" />
              </label>
            </div>
            <label>
              {t("SSH-ключ (для git@… URL)")}
              <SshKeySelect value={f.ssh_key} onChange={(v) => setF({ ...f, ssh_key: v })} />
            </label>
            {p.has_token && (
              <ActionButton className="btn sm ghost" confirm={t("Удалить сохранённый токен?")} onClick={async () => {
                await api(`/projects/${p.id}`, { method: "PATCH", body: { clear_token: true } });
                onSaved();
              }}>{t("Удалить токен")}</ActionButton>
            )}
            <h3>{t("Деплой")}</h3>
            <label className="check"><input type="checkbox" checked={f.auto_rollback} onChange={set("auto_rollback")} /> {t("Автооткат, если после деплоя контейнеры не поднялись")}</label>
            <label className="inline">{t("Ждать готовности контейнеров")}
              <input type="number" min={10} max={1800} value={f.health_timeout} onChange={(e) => setF({ ...f, health_timeout: Number(e.target.value) })} style={{ width: 90 }} /> {t("секунд")}
            </label>
            <h3>{t("Вебхук (авто-деплой при push)")}</h3>
            <label className="check"><input type="checkbox" checked={f.webhook_enabled} onChange={set("webhook_enabled")} /> {t("Включён")}</label>
            <div className="hint">
              URL: <span className="mono">{webhookUrl}</span><br />
              {t("Секрет:")} <span className="mono">{p.webhook_secret}</span><br />
              {t("GitLab: поле «Secret token». GitHub/Gitea: «Secret», тип application/json. Деплой срабатывает только для ветки")} <b>{p.branch || t("любой")}</b>.
            </div>
            <ActionButton className="btn sm ghost" confirm={t("Сгенерировать новый секрет? Старый перестанет работать.")} onClick={async () => {
              await api(`/projects/${p.id}`, { method: "PATCH", body: { regenerate_webhook: true } });
              onSaved();
            }}>{t("Новый секрет")}</ActionButton>
          </>
        )}
        <div className="row end"><button className="btn primary">{t("Сохранить")}</button></div>
      </form>

      <div className="card danger-zone">
        <h3>{t("Удаление проекта")}</h3>
        <div className="row wrap">
          <ActionButton className="btn danger" confirm={t("Удалить проект из менеджера? Контейнеры и файлы останутся.")} onClick={async () => {
            await api(`/projects/${p.id}`, { method: "DELETE" });
            nav("/");
          }}>{t("Удалить из менеджера")}</ActionButton>
          <ActionButton className="btn danger" confirm={t("Выполнить docker compose down и удалить проект? Файлы останутся.")} onClick={async () => {
            await api(`/projects/${p.id}?compose_down=true`, { method: "DELETE" });
            nav("/");
          }}>{t("Down + удалить")}</ActionButton>
          {p.managed && (
            <ActionButton className="btn danger" confirm={t("Выполнить down, удалить проект И ВСЕ ЕГО ФАЙЛЫ на сервере? Это необратимо.")} onClick={async () => {
              await api(`/projects/${p.id}?compose_down=true&remove_files=true`, { method: "DELETE" });
              nav("/");
            }}>{t("Down + удалить вместе с файлами")}</ActionButton>
          )}
        </div>
      </div>
    </div>
  );
}

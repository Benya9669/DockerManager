import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { ActionButton, Loading, Modal, toast, toastErr, useFetch } from "../ui";
import { SshKeySelect } from "../SshKeySelect";
import { ServerPicker, useServer } from "../server";

export function ProjectsPage() {
  const { can } = useAuth();
  const { data, error, loading, reload } = useFetch<any[]>(() => api("/projects"), [], 10000);
  const [showNew, setShowNew] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [q, setQ] = useState("");
  const list = (data || []).filter((p) => !q || (p.name + p.slug + p.description).toLowerCase().includes(q.toLowerCase()));

  return (
    <div>
      <div className="page-head">
        <h1>Проекты</h1>
        <div className="row">
          <input placeholder="Поиск…" value={q} onChange={(e) => setQ(e.target.value)} />
          {can("admin") && <button className="btn" onClick={() => setShowImport(true)}>⤓ Импорт запущенных стеков</button>}
          {can("admin") && <button className="btn primary" onClick={() => setShowNew(true)}>+ Новый проект</button>}
        </div>
      </div>
      <Loading error={error} loading={loading && !data} />
      {data && !list.length && <div className="empty">Проектов пока нет.{can("admin") && " Создайте первый — из git-репозитория, существующей папки или с нуля."}</div>}
      <div className="grid">
        {list.map((p) => (
          <Link key={p.id} to={`/projects/${p.id}`} className="card project-card">
            <div className="row between">
              <h3>{p.name}</h3>
              {p.busy && <span className="badge yellow">задача…</span>}
            </div>
            <div className="muted small">{p.slug}</div>
            {p.description && <p className="desc">{p.description}</p>}
            <div className="row wrap small">
              <span className="chip">{p.source === "git" ? `⎇ ${p.branch || "git"}` : "📁 локальный"}</span>
              {p.server_name && <span className="chip">🖥 {p.server_name}</span>}
              {p.env_file && <span className="chip">env: {p.env_file}</span>}
              <span className={`chip ${p.containers_running ? "green" : ""}`}>
                ▶ {p.containers_running}/{p.containers_total}
              </span>
            </div>
          </Link>
        ))}
      </div>
      {showNew && <NewProjectModal onClose={() => setShowNew(false)} onCreated={reload} />}
      {showImport && <ImportModal onClose={() => setShowImport(false)} onImported={reload} />}
    </div>
  );
}

function TemplatePicker({ value, onChange }: { value: string; onChange: (id: string) => void }) {
  const list = useFetch<any[]>(() => api("/projects/templates"), []);
  return (
    <div className="stack-sm">
      <Loading error={list.error} loading={list.loading && !list.data} />
      <div className="template-grid">
        {(list.data || []).map((t) => (
          <button type="button" key={t.id} className={`template ${value === t.id ? "active" : ""}`} onClick={() => onChange(t.id)}>
            <b>{t.name}</b>
            <span className="muted small">{t.description}</span>
            <span className="muted small mono">{t.files.join(", ")}</span>
          </button>
        ))}
      </div>
      {!value && <div className="muted small">Выберите шаблон. Пароли в .env сгенерируются автоматически.</div>}
    </div>
  );
}

function ImportModal({ onClose, onImported }: { onClose: () => void; onImported: () => void }) {
  const list = useFetch<any[]>(() => api("/projects/discover"), []);
  const [showAll, setShowAll] = useState(false);
  const [sshKey, setSshKey] = useState("");
  const items = (list.data || []).filter((s) => showAll || !s.registered);
  const importable = items.filter((s) => !s.registered && s.accessible);

  const doImport = async (slug: string) => {
    const s = items.find((x) => x.slug === slug);
    await api("/projects/import", { body: { slug, ssh_key: s?.git_repo_url ? sshKey : "" } });
    toast(`Импортирован: ${slug}`);
  };

  return (
    <Modal title="Импорт запущенных compose-стеков" onClose={onClose} wide>
      <div className="stack">
        <div className="hint">
          Стеки найдены по меткам контейнеров на хосте. При импорте имя compose-проекта, папка, compose-файлы и env-файл
          берутся такими же, как при исходном запуске, поэтому панель управляет теми же контейнерами и не создаёт дубликаты.
          Контейнеры при импорте не перезапускаются.
        </div>
        <label className="form">
          <span className="muted small">SSH-ключ для импортируемых git-проектов (можно поменять потом в настройках проекта)</span>
          <SshKeySelect value={sshKey} onChange={setSshKey} />
        </label>
        <div className="row between">
          <label className="check"><input type="checkbox" checked={showAll} onChange={(e) => setShowAll(e.target.checked)} />показать уже добавленные</label>
          <ActionButton className="btn primary" disabled={!importable.length} onClick={async () => {
            for (const s of importable) {
              try { await doImport(s.slug); } catch (e) { toastErr(e); }
            }
            list.reload();
            onImported();
          }}>Импортировать все ({importable.length})</ActionButton>
        </div>
        <Loading error={list.error} loading={list.loading && !list.data} />
        {list.data && !items.length && <div className="empty">Новых compose-стеков не найдено</div>}
        {items.length > 0 && (
          <table className="table">
            <thead><tr><th>Проект</th><th>Папка / файлы</th><th>Сервисы</th><th>Git</th><th /></tr></thead>
            <tbody>
              {items.map((s) => (
                <tr key={s.slug}>
                  <td><b>{s.slug}</b><div className="muted small">▶ {s.running}/{s.total}</div></td>
                  <td className="small">
                    <div className="mono">{s.working_dir || "—"}</div>
                    <div className="muted mono">{s.compose_files}{s.env_file && ` · env: ${s.env_file}`}</div>
                    {!s.accessible && <div className="danger-text">папка недоступна панели — смонтируйте её по тому же пути</div>}
                  </td>
                  <td className="small">{s.services.join(", ")}</td>
                  <td className="small">{s.git_repo_url ? <><div className="mono">{s.git_repo_url}</div><div className="muted">⎇ {s.git_branch}</div></> : <span className="muted">—</span>}</td>
                  <td className="actions">
                    {s.registered ? <span className="badge green">уже в панели</span> : (
                      <ActionButton className="btn sm primary" disabled={!s.accessible} onClick={async () => {
                        await doImport(s.slug);
                        list.reload();
                        onImported();
                      }}>Импорт</ActionButton>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </Modal>
  );
}

function NewProjectModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const nav = useNavigate();
  const { servers } = useServer();
  const [f, setF] = useState({
    name: "", slug: "", description: "", source: "git", repo_url: "", branch: "",
    git_username: "", git_token: "", ssh_key: "", path: "", template: "", server_id: null as number | null, compose_files: "docker-compose.yml", env_file: "",
  });
  const [busy, setBusy] = useState(false);
  const set = (k: string) => (e: any) => setF({ ...f, [k]: e.target.value });

  const submit = async (e: any) => {
    e.preventDefault();
    setBusy(true);
    try {
      const body: any = { ...f };
      if (!body.slug) delete body.slug;
      const p = await api("/projects", { body });
      onCreated();
      nav(`/projects/${p.id}` + (p.job_id ? `?job=${p.job_id}` : ""));
    } catch (e) {
      toastErr(e);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal title="Новый проект" onClose={onClose}>
      <form onSubmit={submit} className="form">
        <div className="seg">
          {[["git", "Git-репозиторий"], ["template", "Из шаблона"], ["local", "Папка на сервере"], ["empty", "С нуля"]].map(([k, l]) => (
            <button type="button" key={k} className={`seg-btn ${f.source === k ? "active" : ""}`} onClick={() => setF({ ...f, source: k })}>
              {l}
            </button>
          ))}
        </div>
        <label>Название *<input required value={f.name} onChange={set("name")} /></label>
        <label>
          Slug (имя compose-проекта)
          <input value={f.slug} onChange={set("slug")} placeholder="сгенерируется из названия" pattern="[a-z0-9][a-z0-9_-]*" />
        </label>
        <label>Описание<input value={f.description} onChange={set("description")} /></label>
        {f.source === "git" && (
          <>
            <label>URL репозитория *<input required value={f.repo_url} onChange={set("repo_url")} placeholder="https://gitlab.company.ru/team/app.git или git@…" /></label>
            <div className="cols">
              <label>Ветка<input value={f.branch} onChange={set("branch")} placeholder="по умолчанию" /></label>
              <label>Git-пользователь<input value={f.git_username} onChange={set("git_username")} placeholder="oauth2" /></label>
            </div>
            <label>
              Токен доступа (для HTTPS)
              <input type="password" value={f.git_token} onChange={set("git_token")} placeholder="хранится зашифрованным" autoComplete="new-password" />
            </label>
            <label>
              SSH-ключ (для git@… URL)
              <SshKeySelect value={f.ssh_key} onChange={(v) => setF({ ...f, ssh_key: v })} />
            </label>
          </>
        )}
        {f.source === "template" && <TemplatePicker value={f.template} onChange={(t) => setF({ ...f, template: t })} />}
        {f.source === "local" && (
          <label>Путь к папке на сервере *<input required value={f.path} onChange={set("path")} placeholder="/opt/apps/myapp" /></label>
        )}
        {servers.length > 0 && (
          <label>Где запускать<ServerPicker value={f.server_id} onChange={(v) => setF({ ...f, server_id: v })} /></label>
        )}
        <div className="cols">
          <label>Compose-файлы (через запятую)<input value={f.compose_files} onChange={set("compose_files")} /></label>
          <label>Активный .env<input value={f.env_file} onChange={set("env_file")} placeholder="можно выбрать позже" /></label>
        </div>
        <div className="row end">
          <button type="button" className="btn ghost" onClick={onClose}>Отмена</button>
          <button className="btn primary" disabled={busy}>{busy ? "Создание…" : "Создать"}</button>
        </div>
      </form>
    </Modal>
  );
}

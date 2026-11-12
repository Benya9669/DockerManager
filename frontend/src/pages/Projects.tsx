import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { Loading, Modal, toastErr, useFetch } from "../ui";

export function ProjectsPage() {
  const { can } = useAuth();
  const { data, error, loading, reload } = useFetch<any[]>(() => api("/projects"), [], 10000);
  const [showNew, setShowNew] = useState(false);
  const [q, setQ] = useState("");
  const list = (data || []).filter((p) => !q || (p.name + p.slug + p.description).toLowerCase().includes(q.toLowerCase()));

  return (
    <div>
      <div className="page-head">
        <h1>Проекты</h1>
        <div className="row">
          <input placeholder="Поиск…" value={q} onChange={(e) => setQ(e.target.value)} />
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
              {p.env_file && <span className="chip">env: {p.env_file}</span>}
              <span className={`chip ${p.containers_running ? "green" : ""}`}>
                ▶ {p.containers_running}/{p.containers_total}
              </span>
            </div>
          </Link>
        ))}
      </div>
      {showNew && <NewProjectModal onClose={() => setShowNew(false)} onCreated={reload} />}
    </div>
  );
}

function NewProjectModal({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const nav = useNavigate();
  const [f, setF] = useState({
    name: "", slug: "", description: "", source: "git", repo_url: "", branch: "",
    git_username: "", git_token: "", path: "", compose_files: "docker-compose.yml", env_file: "",
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
          {[["git", "Git-репозиторий"], ["local", "Папка на сервере"], ["empty", "С нуля"]].map(([k, l]) => (
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
            <div className="hint">Для SSH-URL используются ключи из ~/.ssh пользователя, под которым запущен сервер.</div>
          </>
        )}
        {f.source === "local" && (
          <label>Путь к папке на сервере *<input required value={f.path} onChange={set("path")} placeholder="/opt/apps/myapp" /></label>
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

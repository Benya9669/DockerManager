import { useState } from "react";
import { api, setToken } from "../api";
import { useAuth } from "../auth";
import { ActionButton, Loading, Modal, fmtDate, toast, toastErr, useFetch } from "../ui";

const ROLES: [string, string][] = [["viewer", "наблюдатель"], ["operator", "оператор"], ["admin", "администратор"]];

export function UsersPage() {
  const { user } = useAuth();
  const list = useFetch<any[]>(() => api("/users"), []);
  const [show, setShow] = useState(false);
  const [f, setF] = useState({ username: "", password: "", role: "operator" });
  const [accessFor, setAccessFor] = useState<any>(null);

  return (
    <div>
      <div className="page-head">
        <h1>Пользователи</h1>
        <button className="btn primary" onClick={() => setShow(true)}>+ Пользователь</button>
      </div>
      <div className="hint mb">
        <b>Наблюдатель</b> — просмотр проектов, контейнеров и логов. <b>Оператор</b> — деплой, build, env, файлы, git, терминал.
        <b> Администратор</b> — плюс проекты, настройки, очистка, пользователи и аудит.
      </div>
      <Loading error={list.error} loading={list.loading && !list.data} />
      <table className="table">
        <thead><tr><th>Логин</th><th>Роль</th><th>Активен</th><th>Создан</th><th /></tr></thead>
        <tbody>
          {(list.data || []).map((u) => (
            <tr key={u.id}>
              <td><b>{u.username}</b>{u.id === user?.id && <span className="muted"> (вы)</span>}</td>
              <td>
                <select value={u.role} disabled={u.id === user?.id} onChange={async (e) => {
                  try {
                    await api(`/users/${u.id}`, { method: "PATCH", body: { role: e.target.value } });
                    list.reload();
                  } catch (err) { toastErr(err); }
                }}>
                  {ROLES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
                </select>
              </td>
              <td>
                <input type="checkbox" checked={u.is_active} disabled={u.id === user?.id} onChange={async (e) => {
                  try {
                    await api(`/users/${u.id}`, { method: "PATCH", body: { is_active: e.target.checked } });
                    list.reload();
                  } catch (err) { toastErr(err); }
                }} />
              </td>
              <td className="small">{fmtDate(u.created_at)}</td>
              <td className="actions">
                {u.role !== "admin" && <button className="btn sm" onClick={() => setAccessFor(u)}>Доступ к проектам</button>}
                <ActionButton className="btn sm" onClick={async () => {
                  const p = prompt(`Новый пароль для ${u.username} (мин. 8 символов)`);
                  if (!p) return;
                  await api(`/users/${u.id}`, { method: "PATCH", body: { password: p } });
                  toast("Пароль изменён");
                }}>Пароль</ActionButton>
                {u.id !== user?.id && (
                  <ActionButton className="btn sm danger" confirm={`Удалить ${u.username}?`} onClick={async () => {
                    await api(`/users/${u.id}`, { method: "DELETE" });
                    list.reload();
                  }}>🗑</ActionButton>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {accessFor && <AccessModal user={accessFor} onClose={() => setAccessFor(null)} />}
      {show && (
        <Modal title="Новый пользователь" onClose={() => setShow(false)}>
          <form className="form" onSubmit={async (e) => {
            e.preventDefault();
            try {
              await api("/users", { body: f });
              setShow(false);
              setF({ username: "", password: "", role: "operator" });
              list.reload();
            } catch (err) { toastErr(err); }
          }}>
            <label>Логин<input required value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} /></label>
            <label>Пароль (мин. 8)<input required type="password" minLength={8} value={f.password} autoComplete="new-password" onChange={(e) => setF({ ...f, password: e.target.value })} /></label>
            <label>Роль
              <select value={f.role} onChange={(e) => setF({ ...f, role: e.target.value })}>
                {ROLES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select>
            </label>
            <div className="row end"><button className="btn primary">Создать</button></div>
          </form>
        </Modal>
      )}
    </div>
  );
}

const ROLE_RU: Record<string, string> = { viewer: "наблюдатель", operator: "оператор", admin: "администратор" };

function AccessModal({ user, onClose }: { user: any; onClose: () => void }) {
  const acc = useFetch<any>(() => api(`/users/${user.id}/access`), [user.id]);
  const set = async (project_id: number, role: string) => {
    try {
      await api(`/users/${user.id}/access`, { method: "PUT", body: { project_id, role: role || null } });
      acc.reload();
    } catch (e) {
      toastErr(e);
    }
  };
  return (
    <Modal title={`Доступ к проектам: ${user.username}`} onClose={onClose} wide>
      <div className="stack">
        <div className="hint">
          Глобальная роль: <b>{ROLE_RU[user.role]}</b> — действует во всех проектах, где не задано иное.
          Для отдельных проектов можно скрыть проект или дать больше прав (например, оператор только в одном проекте).
        </div>
        <Loading error={acc.error} loading={acc.loading && !acc.data} />
        {acc.data && (
          <table className="table">
            <thead><tr><th>Проект</th><th>Роль в проекте</th></tr></thead>
            <tbody>
              {acc.data.projects.map((p: any) => (
                <tr key={p.project_id}>
                  <td>{p.name} <span className="muted small">{p.slug}</span></td>
                  <td>
                    <select value={p.role || ""} onChange={(e) => set(p.project_id, e.target.value)}>
                      <option value="">по умолчанию ({ROLE_RU[acc.data.global_role]})</option>
                      <option value="none">нет доступа (проект скрыт)</option>
                      <option value="viewer">наблюдатель</option>
                      <option value="operator">оператор</option>
                    </select>
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

export function AuditPage() {
  const list = useFetch<any[]>(() => api("/audit?limit=500"), [], 15000);
  const [q, setQ] = useState("");
  const items = (list.data || []).filter((r) => !q || `${r.username} ${r.ip} ${r.action} ${r.target} ${r.details}`.toLowerCase().includes(q.toLowerCase()));
  return (
    <div>
      <div className="page-head">
        <h1>Аудит</h1>
        <input placeholder="Фильтр…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <Loading error={list.error} loading={list.loading && !list.data} />
      <table className="table">
        <thead><tr><th>Время</th><th>Пользователь</th><th>IP</th><th>Действие</th><th>Объект</th><th>Детали</th></tr></thead>
        <tbody>
          {items.map((r) => (
            <tr key={r.id}>
              <td className="small">{fmtDate(r.ts)}</td><td>{r.username}</td><td className="mono small">{r.ip}</td>
              <td className="mono small">{r.action}</td><td>{r.target}</td>
              <td className="small mono muted">{r.details}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function AccountPage() {
  const { user } = useAuth();
  const [f, setF] = useState({ current_password: "", new_password: "" });
  return (
    <div>
      <div className="page-head"><h1>Аккаунт: {user?.username}</h1></div>
      <form className="card form narrow" onSubmit={async (e) => {
        e.preventDefault();
        try {
          const r = await api("/auth/password", { body: f });
          if (r.token) setToken(r.token); // other sessions are logged out, keep this one
          toast("Пароль изменён, остальные сессии завершены");
          setF({ current_password: "", new_password: "" });
        } catch (err) { toastErr(err); }
      }}>
        <h3>Смена пароля</h3>
        <label>Текущий пароль<input type="password" required value={f.current_password} onChange={(e) => setF({ ...f, current_password: e.target.value })} /></label>
        <label>Новый пароль (мин. 8)<input type="password" required minLength={8} autoComplete="new-password" value={f.new_password} onChange={(e) => setF({ ...f, new_password: e.target.value })} /></label>
        <div className="row end"><button className="btn primary">Сохранить</button></div>
      </form>
    </div>
  );
}

export function RegistriesPage() {
  const list = useFetch<any[]>(() => api("/registries"), []);
  const [f, setF] = useState({ url: "ghcr.io", username: "", password: "", verify: true });
  const [show, setShow] = useState(false);

  return (
    <div>
      <div className="page-head">
        <h1>Реестры образов</h1>
        <button className="btn primary" onClick={() => setShow(true)}>+ Реестр</button>
      </div>
      <div className="hint mb">
        Логины к приватным registry. Используются во всех операциях панели: <b>pull</b>, <b>деплой</b>, <b>up</b>, Pull на странице образов
        и самообновление в режиме image. Пароли хранятся зашифрованными.<br />
        <b>GHCR:</b> адрес <span className="mono">ghcr.io</span>, логин — ваш GitHub-логин, пароль — Personal Access Token (classic) с правом <span className="mono">read:packages</span>.
      </div>
      <Loading error={list.error} loading={list.loading && !list.data} />
      {list.data && !list.data.length && <div className="empty">Реестров нет — используются только публичные образы</div>}
      {!!list.data?.length && (
        <table className="table">
          <thead><tr><th>Реестр</th><th>Логин</th><th>Добавлен</th><th /></tr></thead>
          <tbody>
            {list.data.map((r) => (
              <tr key={r.id}>
                <td className="mono">{r.url}</td>
                <td>{r.username}</td>
                <td className="small">{fmtDate(r.created_at)}</td>
                <td className="actions">
                  <ActionButton className="btn sm" onClick={async () => {
                    const p = prompt(`Новый токен/пароль для ${r.url}`);
                    if (!p) return;
                    await api(`/registries/${r.id}`, { method: "PATCH", body: { password: p } });
                    toast("Обновлено, вход проверен");
                  }}>Сменить токен</ActionButton>
                  <ActionButton className="btn sm danger" confirm={`Удалить логин к ${r.url}?`} onClick={async () => {
                    await api(`/registries/${r.id}`, { method: "DELETE" });
                    list.reload();
                  }}>🗑</ActionButton>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {show && (
        <Modal title="Новый реестр" onClose={() => setShow(false)}>
          <form className="form" onSubmit={async (e) => {
            e.preventDefault();
            try {
              await api("/registries", { body: f });
              toast("Реестр добавлен");
              setShow(false);
              setF({ url: "ghcr.io", username: "", password: "", verify: true });
              list.reload();
            } catch (err) { toastErr(err); }
          }}>
            <label>Адрес реестра<input required value={f.url} onChange={(e) => setF({ ...f, url: e.target.value })} placeholder="ghcr.io, registry.gitlab.com, harbor.company.ru" /></label>
            <label>Логин<input required value={f.username} onChange={(e) => setF({ ...f, username: e.target.value })} /></label>
            <label>Токен / пароль<input required type="password" autoComplete="new-password" value={f.password} onChange={(e) => setF({ ...f, password: e.target.value })} /></label>
            <label className="check"><input type="checkbox" checked={f.verify} onChange={(e) => setF({ ...f, verify: e.target.checked })} />проверить вход (docker login)</label>
            <div className="row end"><button className="btn primary">Добавить</button></div>
          </form>
        </Modal>
      )}
    </div>
  );
}

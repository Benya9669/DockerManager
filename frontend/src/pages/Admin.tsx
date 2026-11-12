import { useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { ActionButton, Loading, Modal, fmtDate, toast, toastErr, useFetch } from "../ui";

const ROLES: [string, string][] = [["viewer", "наблюдатель"], ["operator", "оператор"], ["admin", "администратор"]];

export function UsersPage() {
  const { user } = useAuth();
  const list = useFetch<any[]>(() => api("/users"), []);
  const [show, setShow] = useState(false);
  const [f, setF] = useState({ username: "", password: "", role: "operator" });

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

export function AuditPage() {
  const list = useFetch<any[]>(() => api("/audit?limit=500"), [], 15000);
  const [q, setQ] = useState("");
  const items = (list.data || []).filter((r) => !q || `${r.username} ${r.action} ${r.target} ${r.details}`.toLowerCase().includes(q.toLowerCase()));
  return (
    <div>
      <div className="page-head">
        <h1>Аудит</h1>
        <input placeholder="Фильтр…" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <Loading error={list.error} loading={list.loading && !list.data} />
      <table className="table">
        <thead><tr><th>Время</th><th>Пользователь</th><th>Действие</th><th>Объект</th><th>Детали</th></tr></thead>
        <tbody>
          {items.map((r) => (
            <tr key={r.id}>
              <td className="small">{fmtDate(r.ts)}</td><td>{r.username}</td>
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
          await api("/auth/password", { body: f });
          toast("Пароль изменён");
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

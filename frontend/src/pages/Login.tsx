import { useState } from "react";
import { useAuth } from "../auth";

export function LoginPage() {
  const { login } = useAuth();
  const [username, setU] = useState("");
  const [password, setP] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);

  return (
    <div className="login-wrap">
      <form
        className="card login"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setErr("");
          try {
            await login(username, password);
          } catch (e: any) {
            setErr(e.message);
          } finally {
            setBusy(false);
          }
        }}
      >
        <h2>🐳 Docker Manager</h2>
        <label>Логин<input autoFocus value={username} onChange={(e) => setU(e.target.value)} /></label>
        <label>Пароль<input type="password" value={password} onChange={(e) => setP(e.target.value)} /></label>
        {err && <div className="alert err">{err}</div>}
        <button className="btn primary full" disabled={busy}>{busy ? "Вход…" : "Войти"}</button>
      </form>
    </div>
  );
}

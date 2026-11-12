import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

// ---------- data hook ----------
export function useFetch<T = any>(fn: () => Promise<T>, deps: any[] = [], intervalMs = 0) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  const reload = useCallback(async () => {
    try {
      const d = await fnRef.current();
      setData(d);
      setError(null);
    } catch (e: any) {
      setError(e.message || String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    setLoading(true);
    reload();
    if (!intervalMs) return;
    const t = setInterval(() => {
      if (!document.hidden) reload();
    }, intervalMs);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, error, loading, reload, setData };
}

// ---------- toasts ----------
type Toast = { id: number; text: string; kind: "ok" | "err" };
export function toast(text: string, kind: "ok" | "err" = "ok") {
  window.dispatchEvent(new CustomEvent("dm-toast", { detail: { text, kind } }));
}
export const toastErr = (e: any) => toast(e?.message || String(e), "err");

export function ToastHost() {
  const [items, setItems] = useState<Toast[]>([]);
  useEffect(() => {
    const h = (e: Event) => {
      const { text, kind } = (e as CustomEvent).detail;
      const id = Date.now() + Math.random();
      setItems((x) => [...x, { id, text, kind }]);
      setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), kind === "err" ? 7000 : 3000);
    };
    window.addEventListener("dm-toast", h);
    return () => window.removeEventListener("dm-toast", h);
  }, []);
  return (
    <div className="toasts">
      {items.map((t) => (
        <div key={t.id} className={`toast ${t.kind}`} onClick={() => setItems((x) => x.filter((i) => i.id !== t.id))}>
          {t.text}
        </div>
      ))}
    </div>
  );
}

// ---------- components ----------
export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [onClose]);
  return (
    <div className="modal-bg" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${wide ? "wide" : ""}`}>
        <div className="modal-head">
          <h3>{title}</h3>
          <button className="btn ghost" onClick={onClose}>✕</button>
        </div>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  );
}

export function StateBadge({ state }: { state?: string | null }) {
  const s = state || "none";
  const cls =
    s === "running" || s === "success" ? "green" :
    s === "exited" || s === "failed" || s === "dead" ? "red" :
    s === "paused" || s === "restarting" || s === "running-job" || s === "cancelled" ? "yellow" : "gray";
  const label: Record<string, string> = {
    running: "работает", exited: "остановлен", created: "создан", paused: "пауза", restarting: "перезапуск",
    dead: "мёртв", none: "не создан", success: "успех", failed: "ошибка", cancelled: "отменён",
  };
  return <span className={`badge ${cls}`}>{label[s] || s}</span>;
}

export function Tabs({ tabs, active, onChange }: { tabs: [string, string][]; active: string; onChange: (k: string) => void }) {
  return (
    <div className="tabs">
      {tabs.map(([k, label]) => (
        <button key={k} className={`tab ${active === k ? "active" : ""}`} onClick={() => onChange(k)}>
          {label}
        </button>
      ))}
    </div>
  );
}

export function Loading({ error, loading }: { error?: string | null; loading?: boolean }) {
  if (error) return <div className="alert err">{error}</div>;
  if (loading) return <div className="muted pad">Загрузка…</div>;
  return null;
}

/** Button that runs an async action, shows busy state and reports errors. */
export function ActionButton({
  onClick, children, className = "btn", confirm, title, disabled,
}: { onClick: () => Promise<any> | any; children: ReactNode; className?: string; confirm?: string; title?: string; disabled?: boolean }) {
  const [busy, setBusy] = useState(false);
  return (
    <button
      className={className}
      title={title}
      disabled={busy || disabled}
      onClick={async () => {
        if (confirm && !window.confirm(confirm)) return;
        setBusy(true);
        try {
          await onClick();
        } catch (e) {
          toastErr(e);
        } finally {
          setBusy(false);
        }
      }}
    >
      {busy ? "…" : children}
    </button>
  );
}

// ---------- formatting ----------
export function fmtBytes(n?: number | null) {
  if (!n && n !== 0) return "—";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v < 10 && i > 0 ? 1 : 0)} ${u[i]}`;
}

export function fmtDate(v?: string | number | null) {
  if (!v) return "—";
  const d = typeof v === "number" ? new Date(v * 1000) : new Date(v);
  return d.toLocaleString("ru-RU");
}

export function fmtAgo(v?: string | number | null) {
  if (!v) return "—";
  const d = typeof v === "number" ? new Date(v * 1000) : new Date(v);
  const s = (Date.now() - d.getTime()) / 1000;
  if (s < 60) return "только что";
  if (s < 3600) return `${Math.floor(s / 60)} мин назад`;
  if (s < 86400) return `${Math.floor(s / 3600)} ч назад`;
  return `${Math.floor(s / 86400)} дн назад`;
}

export function Ports({ ports }: { ports: any[] }) {
  const pub = (ports || []).filter((p) => p.public);
  const uniq = Array.from(new Set(pub.map((p) => `${p.public}:${p.private}/${p.type}`)));
  if (!uniq.length) return <span className="muted">—</span>;
  return (
    <span className="ports">
      {uniq.map((p) => {
        const pubPort = p.split(":")[0];
        return (
          <a key={p} href={`${location.protocol}//${location.hostname}:${pubPort}`} target="_blank" rel="noreferrer" className="chip">
            {p}
          </a>
        );
      })}
    </span>
  );
}

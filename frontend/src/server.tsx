import { t } from "./i18n";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api } from "./api";
import { useAuth } from "./auth";

export type ServerInfo = { id: number; name: string; docker_host: string; ssh_key: string; description: string; projects: number };

type Ctx = {
  servers: ServerInfo[];
  /** selected docker host for Containers/Images/Volumes/Networks/System pages; null = local */
  serverId: number | null;
  setServerId: (id: number | null) => void;
  reload: () => void;
};

const ServerCtx = createContext<Ctx>({ servers: [], serverId: null, setServerId: () => {}, reload: () => {} });
const KEY = "dm_server";

export function ServerProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const [servers, setServers] = useState<ServerInfo[]>([]);
  const [serverId, setSel] = useState<number | null>(() => {
    const v = localStorage.getItem(KEY);
    return v ? Number(v) : null;
  });
  const reload = () => {
    if (user) api("/servers").then((r) => setServers(r.servers)).catch(() => {});
  };
  useEffect(reload, [user?.id]);
  useEffect(() => {
    if (serverId != null && servers.length && !servers.some((s) => s.id === serverId)) setServerId(null);
  }, [servers]);
  const setServerId = (id: number | null) => {
    setSel(id);
    if (id == null) localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, String(id));
  };
  return <ServerCtx.Provider value={{ servers, serverId, setServerId, reload }}>{children}</ServerCtx.Provider>;
}

export const useServer = () => useContext(ServerCtx);

/** Append ?server_id= (or &server_id=) for a non-local host. */
export function withServer(path: string, serverId: number | null | undefined): string {
  if (serverId == null) return path;
  return `${path}${path.includes("?") ? "&" : "?"}server_id=${serverId}`;
}

export function ServerSelect() {
  const { servers, serverId, setServerId } = useServer();
  if (!servers.length) return null;
  return (
    <label className="server-select">
      <span className="muted small">{t("Docker-хост")}</span>
      <select value={serverId ?? ""} onChange={(e) => setServerId(e.target.value ? Number(e.target.value) : null)}>
        <option value="">{t("Локальный")}</option>
        {servers.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
      </select>
    </label>
  );
}

/** Select of the docker host a project runs on (null = local). */
export function ServerPicker({ value, onChange }: { value: number | null; onChange: (id: number | null) => void }) {
  const { servers } = useServer();
  return (
    <select value={value ?? ""} onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}>
      <option value="">{t("Локальный (сервер панели)")}</option>
      {servers.map((s) => <option key={s.id} value={s.id}>{s.name} — {s.docker_host}</option>)}
    </select>
  );
}

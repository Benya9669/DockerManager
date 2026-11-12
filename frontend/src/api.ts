const TOKEN_KEY = "dm_token";

export const getToken = () => localStorage.getItem(TOKEN_KEY);
export const setToken = (t: string | null) =>
  t ? localStorage.setItem(TOKEN_KEY, t) : localStorage.removeItem(TOKEN_KEY);

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

function detailToString(d: any): string {
  if (!d) return "";
  if (typeof d === "string") return d;
  if (Array.isArray(d)) return d.map((x) => `${(x.loc || []).slice(1).join(".")}: ${x.msg}`).join("; ");
  return JSON.stringify(d);
}

export async function api<T = any>(path: string, opts: { method?: string; body?: any } = {}): Promise<T> {
  const headers: Record<string, string> = {};
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (opts.body !== undefined) headers["Content-Type"] = "application/json";
  const res = await fetch("/api" + path, {
    method: opts.method || (opts.body !== undefined ? "POST" : "GET"),
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  if (res.status === 401 && path !== "/auth/login") {
    setToken(null);
    if (location.pathname !== "/login") location.href = "/login";
  }
  const text = await res.text();
  let data: any = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    data = text;
  }
  if (!res.ok) throw new ApiError(res.status, detailToString(data?.detail) || res.statusText);
  return data as T;
}

/** Websocket URL without credentials; a one-time ticket is added right before connecting (see openWs). */
export function wsUrl(path: string, params: Record<string, string> = {}): string {
  const u = new URL("/api" + path, location.href);
  u.protocol = u.protocol === "https:" ? "wss:" : "ws:";
  for (const [k, v] of Object.entries(params)) u.searchParams.set(k, v);
  return u.toString();
}

/** Opens a websocket authenticated with a single-use 30s ticket (session token never goes into the URL). */
export async function openWs(url: string): Promise<WebSocket> {
  const { ticket } = await api<{ ticket: string }>("/auth/ws-ticket", { method: "POST" });
  const u = new URL(url);
  u.searchParams.set("ticket", ticket);
  return new WebSocket(u.toString());
}

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { api, getToken, setToken } from "./api";

export type Role = "viewer" | "operator" | "admin";
export type User = { id: number; username: string; role: Role; is_active: boolean };

const LEVEL: Record<Role, number> = { viewer: 0, operator: 1, admin: 2 };

type Ctx = {
  user: User | null;
  ready: boolean;
  login: (u: string, p: string) => Promise<void>;
  logout: () => void;
  can: (role: Role) => boolean;
};

const AuthCtx = createContext<Ctx>(null as any);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!getToken()) {
      setReady(true);
      return;
    }
    api<User>("/auth/me")
      .then(setUser)
      .catch(() => setToken(null))
      .finally(() => setReady(true));
  }, []);

  const login = async (username: string, password: string) => {
    const r = await api<{ token: string; user: User }>("/auth/login", { body: { username, password } });
    setToken(r.token);
    setUser(r.user);
  };
  const logout = () => {
    setToken(null);
    setUser(null);
  };
  const can = (role: Role) => !!user && LEVEL[user.role] >= LEVEL[role];

  return <AuthCtx.Provider value={{ user, ready, login, logout, can }}>{children}</AuthCtx.Provider>;
}

export const useAuth = () => useContext(AuthCtx);

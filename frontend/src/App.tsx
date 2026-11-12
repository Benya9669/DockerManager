import { Navigate, NavLink, Route, Routes } from "react-router-dom";
import { useAuth } from "./auth";
import { ToastHost } from "./ui";
import { LoginPage } from "./pages/Login";
import { ProjectsPage } from "./pages/Projects";
import { ProjectPage } from "./pages/Project";
import { ContainersPage, ContainerPage } from "./pages/Containers";
import { ImagesPage, NetworksPage, VolumesPage } from "./pages/Resources";
import { JobPage, JobsPage } from "./pages/Jobs";
import { CleanupPage } from "./pages/Cleanup";
import { AccountPage, AuditPage, RegistriesPage, UsersPage } from "./pages/Admin";
import { api } from "./api";
import { BackupsPage } from "./pages/Backups";
import { useFetch } from "./ui";

const ROLE_RU = { admin: "администратор", operator: "оператор", viewer: "наблюдатель" } as const;

export function App() {
  const { user, ready, logout, can } = useAuth();
  const ver = useFetch<any>(() => (user ? api("/version") : Promise.resolve(null)), [user?.id]);
  if (!ready) return null;
  if (!user)
    return (
      <>
        <Routes>
          <Route path="*" element={<LoginPage />} />
        </Routes>
        <ToastHost />
      </>
    );

  const nav: [string, string, boolean][] = [
    ["/", "📦 Проекты", true],
    ["/containers", "🧩 Контейнеры", true],
    ["/images", "💿 Образы", true],
    ["/volumes", "🗄 Тома", true],
    ["/networks", "🔗 Сети", true],
    ["/jobs", "⚙️ Задачи", true],
    ["/system", "🧹 Система и очистка", true],
    ["/backups", "💾 Бэкапы", can("admin")],
    ["/registries", "🔐 Реестры", can("admin")],
    ["/users", "👥 Пользователи", can("admin")],
    ["/audit", "📜 Аудит", can("admin")],
  ];

  return (
    <div className="layout">
      <aside className="sidebar">
        <div className="brand">🐳 Docker Manager</div>
        <nav>
          {nav.filter((n) => n[2]).map(([to, label]) => (
            <NavLink key={to} to={to} end={to === "/"} className={({ isActive }) => `nav ${isActive ? "active" : ""}`}>
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <NavLink to="/account" className="nav">
            👤 {user.username}
            <div className="muted small">{ROLE_RU[user.role]}</div>
          </NavLink>
          <button className="btn ghost full" onClick={logout}>Выйти</button>
          {ver.data && (
            <div className="muted small center" title={ver.data.git_sha}>
              v{ver.data.version}{ver.data.git_sha && ` · ${ver.data.git_sha.slice(0, 7)}`}
            </div>
          )}
        </div>
      </aside>
      <main className="content">
        <Routes>
          <Route path="/" element={<ProjectsPage />} />
          <Route path="/projects/:id" element={<ProjectPage />} />
          <Route path="/containers" element={<ContainersPage />} />
          <Route path="/containers/:id" element={<ContainerPage />} />
          <Route path="/images" element={<ImagesPage />} />
          <Route path="/volumes" element={<VolumesPage />} />
          <Route path="/networks" element={<NetworksPage />} />
          <Route path="/jobs" element={<JobsPage />} />
          <Route path="/jobs/:id" element={<JobPage />} />
          <Route path="/system" element={<CleanupPage />} />
          <Route path="/registries" element={<RegistriesPage />} />
          <Route path="/backups" element={<BackupsPage />} />
          <Route path="/users" element={<UsersPage />} />
          <Route path="/audit" element={<AuditPage />} />
          <Route path="/account" element={<AccountPage />} />
          <Route path="/login" element={<Navigate to="/" />} />
          <Route path="*" element={<div className="pad">Страница не найдена</div>} />
        </Routes>
      </main>
      <ToastHost />
    </div>
  );
}

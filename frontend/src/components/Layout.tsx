import { useEffect, useRef, useState, type FormEvent } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth";
import { useTheme } from "../theme";
import { AttentionList, useAttention } from "./DashboardParts";
import {
  Bell,
  Camera,
  ClipboardList,
  Contact,
  DatabaseBackup,
  FileText,
  History,
  LayoutDashboard,
  LogOut,
  Menu,
  Moon,
  Printer,
  RefreshCw,
  Search,
  Sun,
  UploadCloud,
  Users,
  X,
} from "./icons";

export function Layout() {
  const { user, logout, refresh } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const [bellOpen, setBellOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [theme, toggleTheme] = useTheme();
  const attention = useAttention();
  const bell = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setMenuOpen(false);
    setBellOpen(false);
  }, [location.pathname]);
  useEffect(() => {
    if (!bellOpen) return;
    const close = (e: MouseEvent) => bell.current?.contains(e.target as Node) || setBellOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [bellOpen]);
  if (!user) return null;

  const isSales = user.role === "sales";
  const isAdmin = user.role === "admin";
  const listPath = isAdmin ? "/admin/orders" : isSales ? "/orders" : "/queue";
  const panelName = isAdmin ? "Admin" : isSales ? "Sales" : "Printing";
  const displayName = user.full_name || user.username;
  const nextTheme = theme === "dark" ? "light" : "dark";
  const links = isAdmin
    ? [
        { to: "/", label: "Admin Dashboard", icon: LayoutDashboard, end: true },
        { to: "/upload", label: "Upload PO", icon: UploadCloud },
        { to: "/admin/orders", label: "All Orders", icon: ClipboardList },
        { to: "/admin/photos", label: "Photo Reviews", icon: Camera },
        { to: "/admin/users", label: "Users", icon: Users },
        { to: "/admin/contacts", label: "Executive Contacts", icon: Contact },
        { to: "/admin/activity", label: "Activity Log", icon: History },
        { to: "/admin/settings", label: "Settings & Backup", icon: DatabaseBackup },
      ]
    : isSales
    ? [
        { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
        { to: "/upload", label: "Upload PO", icon: UploadCloud },
        { to: "/orders", label: "Sales Orders", icon: ClipboardList },
      ]
    : [
        { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
        { to: "/queue", label: "Printing Queue", icon: Printer },
      ];

  const onSearch = (e: FormEvent) => {
    e.preventDefault();
    const q = query.trim();
    navigate(q ? `${listPath}?q=${encodeURIComponent(q)}` : listPath);
  };

  return (
    <div className="shell">
      <aside className={`sidebar ${menuOpen ? "open" : ""}`}>
        <div className="brand">
          <div className="brand-mark"><FileText size={22} /></div>
          <div>
            <div className="brand-name">OrderFlow</div>
            <div className="brand-panel">{panelName} Panel</div>
          </div>
          <button className="icon-btn sidebar-close" onClick={() => setMenuOpen(false)} aria-label="Close menu">
            <X size={18} />
          </button>
        </div>
        <nav aria-label="Main">
          {links.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} className={({ isActive }) => `nav-link ${isActive ? "active" : ""}`}>
              <Icon size={20} aria-hidden />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="user-chip">
            <div className="avatar">{displayName.slice(0, 1).toUpperCase()}</div>
            <div className="user-meta">
              <div className="user-name">{displayName}</div>
              <div className="user-role">{panelName}</div>
            </div>
          </div>
        </div>
      </aside>
      {menuOpen && <div className="scrim" onClick={() => setMenuOpen(false)} />}

      <div className="main">
        <header className="topbar">
          <button className="icon-btn menu-btn" onClick={() => setMenuOpen(true)} aria-label="Open menu">
            <Menu size={20} />
          </button>
          <form className="search" onSubmit={onSearch} role="search">
            <Search size={16} aria-hidden />
            <input
              type="search"
              placeholder={isSales || isAdmin ? "Search order no, PO, customer, SKU…" : "Search order no, PO or customer…"}
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              aria-label="Search orders"
            />
          </form>
          <div className="topbar-actions">
            <button className="top-btn" onClick={toggleTheme} aria-label={`Switch to ${nextTheme} mode`} title={`Switch to ${nextTheme} mode`}>
              {theme === "dark" ? <Sun size={21} /> : <Moon size={21} />}
            </button>
            <div className="bell" ref={bell}>
              <button className="top-btn" onClick={() => setBellOpen((o) => !o)} aria-expanded={bellOpen}
                aria-label={attention?.count ? `Notifications, ${attention.count} waiting` : "Notifications"}>
                <Bell size={21} />
                {!!attention?.count && <span className="bell-count">{attention.count}</span>}
              </button>
              {bellOpen && (
                <div className="bell-panel">
                  <h2>Needs your action</h2>
                  <AttentionList items={attention?.items ?? []} role={user.role} onPick={() => setBellOpen(false)} />
                </div>
              )}
            </div>
            <button className="top-btn" onClick={refresh} title="Refresh data" aria-label="Refresh data">
              <RefreshCw size={19} />
            </button>
            <button
              className="user-pill"
              onClick={async () => {
                await logout();
                navigate("/login", { replace: true }); // do not carry this user's page over to the next user
              }}
              title="Sign out"
              aria-label="Sign out"
            >
              <span className="avatar">{displayName.slice(0, 1).toUpperCase()}</span>
              <span className="hide-sm">{user.username}</span>
              <LogOut size={16} />
            </button>
          </div>
        </header>
        <main className="content">
          <Outlet />
        </main>
      </div>
    </div>
  );
}

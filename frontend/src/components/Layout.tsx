import {
  ClipboardList,
  Contact,
  DatabaseBackup,
  History,
  LayoutDashboard,
  LogOut,
  Menu,
  Printer,
  RefreshCw,
  Search,
  Upload,
  Users,
  X,
} from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { NavLink, Outlet, useLocation, useNavigate } from "react-router-dom";
import { useAuth } from "../auth";

export function Layout() {
  const { user, logout, refresh } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const [menuOpen, setMenuOpen] = useState(false);
  const [query, setQuery] = useState("");

  useEffect(() => setMenuOpen(false), [location.pathname]);
  if (!user) return null;

  const isSales = user.role === "sales";
  const isAdmin = user.role === "admin";
  const listPath = isAdmin ? "/admin/orders" : isSales ? "/orders" : "/queue";
  const panelName = isAdmin ? "Admin" : isSales ? "Sales" : "Printing";
  const links = isAdmin
    ? [
        { to: "/", label: "Admin Dashboard", icon: LayoutDashboard, end: true },
        { to: "/admin/orders", label: "All Orders", icon: ClipboardList },
        { to: "/upload", label: "Upload PO", icon: Upload },
        { to: "/admin/users", label: "Users", icon: Users },
        { to: "/admin/contacts", label: "Executive Contacts", icon: Contact },
        { to: "/admin/activity", label: "Activity Log", icon: History },
        { to: "/admin/settings", label: "Settings & Backup", icon: DatabaseBackup },
      ]
    : isSales
    ? [
        { to: "/", label: "Dashboard", icon: LayoutDashboard, end: true },
        { to: "/orders", label: "Sales Orders", icon: ClipboardList },
        { to: "/upload", label: "Upload PO", icon: Upload },
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
          <div className="brand-mark">OF</div>
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
              <Icon size={18} aria-hidden />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="sidebar-foot">
          <div className="user-chip">
            <div className="avatar">{(user.full_name || user.username).slice(0, 1).toUpperCase()}</div>
            <div className="user-meta">
              <div className="user-name">{user.full_name || user.username}</div>
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
            <button className="btn btn-ghost" onClick={refresh} title="Refresh data">
              <RefreshCw size={16} />
              <span className="hide-sm">Refresh</span>
            </button>
            <span className="topbar-user hide-sm">{user.username}</span>
            <button
              className="btn btn-ghost"
              onClick={async () => {
                await logout();
                navigate("/login", { replace: true }); // do not carry this user's page over to the next user
              }}
              title="Sign out"
            >
              <LogOut size={16} />
              <span className="hide-sm">Sign out</span>
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

import { LogIn } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../auth";
import { Alert, ErrorAlert } from "../components/ui";
import type { Role } from "../types";

const SALES_ONLY = /^\/(orders\/?(\?.*)?$|upload)/;
const PRINTING_ONLY = /^\/queue/;
const ADMIN_ONLY = /^\/admin(\/|$)/;

/** Only return to a deep link the signed-in role can actually use (e.g. after session expiry). */
function canReturnTo(path: string, role: Role): boolean {
  if (path.startsWith("/login")) return false;
  if (role !== "admin" && ADMIN_ONLY.test(path)) return false;
  if (role === "admin" && (/^\/orders\/?(\?.*)?$/.test(path) || PRINTING_ONLY.test(path))) return false;
  if (role === "printing" && SALES_ONLY.test(path)) return false;
  if (role === "sales" && PRINTING_ONLY.test(path)) return false;
  return true;
}

export function LoginPage() {
  const { user, login, notice, clearNotice } = useAuth();
  const location = useLocation();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  if (user) {
    const from = (location.state as { from?: string } | null)?.from;
    return <Navigate to={from && canReturnTo(from, user.role) ? from : "/"} replace />;
  }

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    clearNotice();
    try {
      await login(username, password);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="login-page">
      <div className="login-card">
        <div className="login-brand">
          <div className="brand-mark lg">OF</div>
          <div>
            <h1>OrderFlow</h1>
            <p className="muted">Order Management Portal · Sales &amp; Printing</p>
          </div>
        </div>
        {notice && (
          <Alert tone={notice.includes("signed out") ? "info" : "warning"} onClose={clearNotice}>
            {notice}
          </Alert>
        )}
        <ErrorAlert error={error} />
        <form onSubmit={submit} className="form-stack">
          <div className="field">
            <label htmlFor="username">Username</label>
            <input
              id="username"
              autoComplete="username"
              autoFocus
              required
              value={username}
              onChange={(e) => setUsername(e.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="password">Password</label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
          </div>
          <button className="btn btn-primary btn-block" disabled={busy}>
            <LogIn size={16} /> {busy ? "Signing in…" : "Sign in"}
          </button>
        </form>
        <p className="muted small login-hint">
          Your panel (Sales or Printing) is set by your account. On a shared computer, sign out before someone else uses it.
        </p>
      </div>
    </div>
  );
}

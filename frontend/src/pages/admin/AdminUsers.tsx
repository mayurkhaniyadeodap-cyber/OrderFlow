import { KeyRound, Pencil, Power, UserPlus } from "../../components/icons";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { useToast } from "../../components/Toast";
import { ErrorAlert, Modal, PasswordInput, Section, Spinner } from "../../components/ui";
import { fmtDateTime } from "../../format";
import type { AdminUser, Role } from "../../types";

const ROLE_LABEL: Record<Role, string> = { admin: "Admin", sales: "Sales", printing: "Printing" };
// Same rule as the server: stored lower-case with single spaces ("Dhruv  Bhojani " -> "dhruv bhojani").
const USERNAME_RE = /^[a-z0-9][a-z0-9._ -]{2,31}$/;
export const normalizeUsername = (value: string) => value.trim().split(/\s+/).join(" ").toLowerCase();

/** Same rule as the server (the server re-checks everything). */
export function passwordProblem(password: string, repeat: string): string | null {
  if (password.length < 8) return "Password must be at least 8 characters.";
  if (/^[a-z]+$/i.test(password) || /^\d+$/.test(password)) return "Password must mix letters with numbers or symbols.";
  if (password !== repeat) return "Passwords do not match.";
  return null;
}

type Dialog = { kind: "create" } | { kind: "edit"; user: AdminUser } | { kind: "password"; user: AdminUser } | null;

export function AdminUsersPage() {
  const { user: me, refreshKey } = useAuth();
  const toast = useToast();
  const [users, setUsers] = useState<AdminUser[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [dialog, setDialog] = useState<Dialog>(null);

  const load = useCallback(() => {
    setError(null);
    api.get<{ items: AdminUser[] }>("/api/admin/users").then((d) => setUsers(d.items)).catch(setError);
  }, []);
  useEffect(load, [load, refreshKey]);

  const toggleActive = async (u: AdminUser) => {
    const verb = u.is_active ? "Deactivate" : "Activate";
    if (!window.confirm(`${verb} ${u.username}?${u.is_active ? " They will be signed out and cannot sign in." : ""}`)) return;
    try {
      await api.patch(`/api/admin/users/${u.id}`, { is_active: !u.is_active });
      toast(`${u.username} ${u.is_active ? "deactivated" : "activated"}`);
      load();
    } catch (err) {
      toast((err as Error).message, "error");
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Users</h1>
          <p className="muted">Create accounts, assign roles, activate or deactivate, and reset passwords. Changes to role, status or password sign the user out.</p>
        </div>
        <button className="btn btn-primary" onClick={() => setDialog({ kind: "create" })}>
          <UserPlus size={16} /> New user
        </button>
      </div>
      <ErrorAlert error={error} />
      {!users && !error && <Spinner />}
      {users && (
        <Section title={`${users.length} account${users.length === 1 ? "" : "s"}`}>
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Username</th>
                  <th>Name</th>
                  <th>Role</th>
                  <th>Status</th>
                  <th>Last sign-in</th>
                  <th aria-label="Actions" />
                </tr>
              </thead>
              <tbody>
                {users.map((u) => {
                  const self = u.id === me?.id;
                  return (
                    <tr key={u.id} className={u.is_active ? "" : "row-inactive"}>
                      <td data-label="Username"><strong>{u.username}</strong>{self && <span className="muted small"> (you)</span>}</td>
                      <td data-label="Name">{u.full_name ?? <span className="muted">—</span>}</td>
                      <td data-label="Role"><span className={`role-tag role-${u.role}`}>{ROLE_LABEL[u.role]}</span></td>
                      <td data-label="Status">
                        <span className={`pill ${u.is_active ? "pill-print-done" : "pill-draft"}`}>{u.is_active ? "Active" : "Inactive"}</span>
                      </td>
                      <td data-label="Last sign-in">{u.last_login_at ? fmtDateTime(u.last_login_at) : <span className="muted">Never</span>}</td>
                      <td className="row-action">
                        <div className="row-buttons">
                          <button className="btn btn-sm btn-secondary" onClick={() => setDialog({ kind: "edit", user: u })} aria-label={`Edit ${u.username}`}>
                            <Pencil size={14} /> Edit
                          </button>
                          <button className="btn btn-sm btn-secondary" onClick={() => setDialog({ kind: "password", user: u })} aria-label={`Reset password for ${u.username}`}>
                            <KeyRound size={14} /> Reset password
                          </button>
                          <button
                            className={`btn btn-sm ${u.is_active ? "btn-ghost danger" : "btn-secondary"}`}
                            onClick={() => toggleActive(u)}
                            disabled={self}
                            title={self ? "You cannot deactivate your own account" : undefined}
                            aria-label={`${u.is_active ? "Deactivate" : "Activate"} ${u.username}`}
                          >
                            <Power size={14} /> {u.is_active ? "Deactivate" : "Activate"}
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Section>
      )}
      {dialog?.kind === "create" && <CreateUserDialog onClose={() => setDialog(null)} onDone={() => { setDialog(null); load(); }} />}
      {dialog?.kind === "edit" && (
        <EditUserDialog user={dialog.user} self={dialog.user.id === me?.id} onClose={() => setDialog(null)} onDone={() => { setDialog(null); load(); }} />
      )}
      {dialog?.kind === "password" && <ResetPasswordDialog user={dialog.user} onClose={() => setDialog(null)} onDone={() => setDialog(null)} />}
    </div>
  );
}

function CreateUserDialog({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [form, setForm] = useState({ username: "", full_name: "", role: "sales" as Role, password: "", repeat: "" });
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const username = normalizeUsername(form.username);
    const problem = !USERNAME_RE.test(username)
      ? "Username: 3-32 characters, letters, numbers, spaces, dot, underscore or hyphen."
      : passwordProblem(form.password, form.repeat);
    if (problem) {
      setError({ message: problem });
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.post("/api/admin/users", { username, full_name: form.full_name.trim() || null, role: form.role, password: form.password });
      toast(`User ${username} created`);
      onDone();
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  };

  return (
    <Modal
      title="New user"
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" form="create-user" disabled={busy}>{busy ? "Creating…" : "Create user"}</button>
        </>
      }
    >
      <form id="create-user" className="form-stack" onSubmit={submit}>
        <ErrorAlert error={error} />
        <div className="field">
          <label htmlFor="u-username">Username</label>
          <input id="u-username" autoComplete="off" value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} required />
        </div>
        <div className="field">
          <label htmlFor="u-name">Full name (optional)</label>
          <input id="u-name" value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
        </div>
        <div className="field">
          <label htmlFor="u-role">Role</label>
          <select id="u-role" value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
            <option value="sales">Sales</option>
            <option value="printing">Printing</option>
            <option value="admin">Admin</option>
          </select>
        </div>
        <PasswordFields value={form} onChange={(p) => setForm({ ...form, ...p })} />
      </form>
    </Modal>
  );
}

function EditUserDialog({ user, self, onClose, onDone }: { user: AdminUser; self: boolean; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [fullName, setFullName] = useState(user.full_name ?? "");
  const [role, setRole] = useState<Role>(user.role);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      const body: Record<string, unknown> = { full_name: fullName.trim() || null };
      if (role !== user.role) body.role = role;
      await api.patch(`/api/admin/users/${user.id}`, body);
      toast(`${user.username} updated`);
      onDone();
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  };

  return (
    <Modal
      title={`Edit ${user.username}`}
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" form="edit-user" disabled={busy}>{busy ? "Saving…" : "Save"}</button>
        </>
      }
    >
      <form id="edit-user" className="form-stack" onSubmit={submit}>
        <ErrorAlert error={error} />
        <div className="field">
          <label htmlFor="e-name">Full name</label>
          <input id="e-name" value={fullName} onChange={(e) => setFullName(e.target.value)} />
        </div>
        <div className="field">
          <label htmlFor="e-role">Role</label>
          <select id="e-role" value={role} disabled={self} onChange={(e) => setRole(e.target.value as Role)}>
            <option value="sales">Sales</option>
            <option value="printing">Printing</option>
            <option value="admin">Admin</option>
          </select>
          {self ? (
            <div className="field-hint">You cannot change your own role.</div>
          ) : (
            role !== user.role && <div className="field-hint">Changing the role signs {user.username} out.</div>
          )}
        </div>
      </form>
    </Modal>
  );
}

function ResetPasswordDialog({ user, onClose, onDone }: { user: AdminUser; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [form, setForm] = useState({ password: "", repeat: "" });
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const problem = passwordProblem(form.password, form.repeat);
    if (problem) {
      setError({ message: problem });
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.post(`/api/admin/users/${user.id}/reset-password`, { new_password: form.password });
      toast(`Password reset for ${user.username}`);
      onDone();
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  };

  return (
    <Modal
      title={`Reset password — ${user.username}`}
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" form="reset-password" disabled={busy}>{busy ? "Saving…" : "Reset password"}</button>
        </>
      }
    >
      <form id="reset-password" className="form-stack" onSubmit={submit}>
        <ErrorAlert error={error} />
        <p className="muted small">Give the new password to {user.username} privately. They will be signed out of every device.</p>
        <PasswordFields value={form} onChange={(p) => setForm({ ...form, ...p })} />
      </form>
    </Modal>
  );
}

function PasswordFields({ value, onChange }: {
  value: { password: string; repeat: string };
  onChange: (v: { password?: string; repeat?: string }) => void;
}) {
  return (
    <>
      <div className="field">
        <label htmlFor="p-new">Password</label>
        <PasswordInput id="p-new" autoComplete="new-password" value={value.password} onChange={(e) => onChange({ password: e.target.value })} required />
        <div className="field-hint">At least 8 characters, mixing letters with numbers or symbols.</div>
      </div>
      <div className="field">
        <label htmlFor="p-repeat">Repeat password</label>
        <PasswordInput id="p-repeat" autoComplete="new-password" value={value.repeat} onChange={(e) => onChange({ repeat: e.target.value })} required />
      </div>
    </>
  );
}

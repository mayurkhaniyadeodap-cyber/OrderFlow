import { DatabaseBackup, Download, Save, Settings } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, downloadFile } from "../../api";
import { useAuth } from "../../auth";
import { useToast } from "../../components/Toast";
import { Alert, EmptyState, ErrorAlert, KV, Section, Spinner } from "../../components/ui";
import { fmtDateTime } from "../../format";
import type { BackupInfo, EditableSettings } from "../../types";

interface SettingsResponse {
  editable: EditableSettings;
  read_only: { timezone: string; order_number_prefix: string; secret_key_configured: boolean };
}

const size = (bytes: number) => (bytes >= 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`);

export function AdminSettingsPage() {
  const { refreshKey } = useAuth();
  const toast = useToast();
  const [data, setData] = useState<SettingsResponse | null>(null);
  const [form, setForm] = useState({ max_upload_mb: "15", token_expire_minutes: "480" });
  const [error, setError] = useState<unknown>(null);
  const [saving, setSaving] = useState(false);
  const [backupList, setBackupList] = useState<BackupInfo[] | null>(null);
  const [includeUploads, setIncludeUploads] = useState(true);
  const [backingUp, setBackingUp] = useState(false);
  const [backupError, setBackupError] = useState<unknown>(null);

  const apply = (d: SettingsResponse) => {
    setData(d);
    setForm({
      max_upload_mb: String(d.editable.max_upload_mb),
      token_expire_minutes: String(d.editable.token_expire_minutes),
    });
  };
  const loadBackups = useCallback(() => {
    api.get<{ items: BackupInfo[] }>("/api/admin/backups").then((d) => setBackupList(d.items)).catch(setBackupError);
  }, []);
  useEffect(() => {
    api.get<SettingsResponse>("/api/admin/settings").then(apply).catch(setError);
    loadBackups();
  }, [refreshKey, loadBackups]);

  const save = async (e: FormEvent) => {
    e.preventDefault();
    setSaving(true);
    setError(null);
    try {
      apply(await api.put<SettingsResponse>("/api/admin/settings", {
        max_upload_mb: Number(form.max_upload_mb),
        token_expire_minutes: Number(form.token_expire_minutes),
      }));
      toast("Settings saved");
    } catch (err) {
      setError(err);
    } finally {
      setSaving(false);
    }
  };

  const backup = async () => {
    setBackingUp(true);
    setBackupError(null);
    try {
      const info = await api.post<BackupInfo>("/api/admin/backups", { include_uploads: includeUploads });
      toast(`Backup ${info.name} created`);
      loadBackups();
    } catch (err) {
      setBackupError(err);
    } finally {
      setBackingUp(false);
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Settings &amp; Backup</h1>
          <p className="muted">Operational settings that are safe to change while the portal runs, and database backups.</p>
        </div>
      </div>

      <div className="grid-2">
        <Section title="Settings" icon={<Settings size={18} />}>
          {!data && !error && <Spinner />}
          <ErrorAlert error={error} />
          {data && (
            <form className="form-stack" onSubmit={save}>
              <div className="form-grid">
                <div className="field">
                  <label htmlFor="s-upload">Max upload size (MB, 1–50)</label>
                  <input id="s-upload" type="number" min={1} max={50} value={form.max_upload_mb} onChange={(e) => setForm({ ...form, max_upload_mb: e.target.value })} />
                </div>
                <div className="field">
                  <label htmlFor="s-session">Session length (minutes, 15–1440)</label>
                  <input id="s-session" type="number" min={15} max={1440} value={form.token_expire_minutes} onChange={(e) => setForm({ ...form, token_expire_minutes: e.target.value })} />
                </div>
              </div>
              <div className="form-actions">
                <button className="btn btn-primary" disabled={saving}><Save size={16} /> {saving ? "Saving…" : "Save settings"}</button>
              </div>
              <div className="kv-grid read-only-settings">
                <KV label="Time zone">{data.read_only.timezone}</KV>
                <KV label="Order number prefix">{data.read_only.order_number_prefix}</KV>
                <KV label="Secret key">{data.read_only.secret_key_configured ? "Configured" : "Temporary (set SECRET_KEY in backend\\.env)"}</KV>
              </div>
              <p className="muted small">Secrets, file locations, time zone and the order-number prefix are changed only in backend\.env.</p>
            </form>
          )}
        </Section>

        <Section title="Database backup" icon={<DatabaseBackup size={18} />}>
          <p className="muted small">
            A backup is a ZIP with a consistent copy of the database and (optionally) all uploaded PDFs, logos and photos. It is safe to run while
            people are working. Backups are stored in <code>backend\backups</code>; copy them to another drive regularly.
          </p>
          <label className="checkbox">
            <input type="checkbox" checked={includeUploads} onChange={(e) => setIncludeUploads(e.target.checked)} />
            Include uploaded files
          </label>
          <div className="form-actions">
            <button className="btn btn-primary" onClick={backup} disabled={backingUp}>
              <DatabaseBackup size={16} /> {backingUp ? "Creating backup…" : "Create backup now"}
            </button>
          </div>
          <ErrorAlert error={backupError} />
          {backupList && backupList.length === 0 && <EmptyState title="No backups yet" />}
          {backupList && backupList.length > 0 && (
            <ul className="backup-list">
              {backupList.map((b) => (
                <li key={b.name}>
                  <div>
                    <div className="mono small">{b.name}</div>
                    <div className="muted small">{fmtDateTime(b.created_at)} · {size(b.size_bytes)}</div>
                  </div>
                  <button className="btn btn-sm btn-secondary" onClick={() => downloadFile(`/api/admin/backups/${encodeURIComponent(b.name)}`, b.name).catch((e) => toast(e.message, "error"))}>
                    <Download size={14} /> Download
                  </button>
                </li>
              ))}
            </ul>
          )}
          <Alert tone="info" title="Restoring a backup">
            Restoring is done by hand so it cannot happen by accident: stop the backend, keep a copy of the current files, unzip the backup and put
            <code> order_portal.db</code> and the <code>uploads</code> folder into <code>backend\</code>, then start the backend again.
          </Alert>
        </Section>
      </div>
    </div>
  );
}

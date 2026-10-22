import { AlertCircle, AlertTriangle, CheckCircle2, Eye, EyeOff, Info, Loader2, X } from "lucide-react";
import { useEffect, useRef, useState, type InputHTMLAttributes, type ReactNode } from "react";
import type { OrderStatus, PhotoStatus, PrintingStatus } from "../types";

export function StatusPill({ status }: { status: OrderStatus | PrintingStatus | null | undefined }) {
  if (!status) return <span className="muted">—</span>;
  const cls = status.toLowerCase().replace(/\s+/g, "-");
  return <span className={`pill pill-${cls}`}>{status}</span>;
}

const PHOTO_LABELS: Record<PhotoStatus, string> = { Pending: "Waiting for confirmation", Confirmed: "Confirmed", Rejected: "Rejected" };

/** Print preview review state of one product: no preview yet, waiting for Sales, confirmed or rejected. */
export function PhotoPill({ status }: { status: PhotoStatus | null | undefined }) {
  if (!status) return <span className="pill pill-photo-missing">No preview yet</span>;
  return <span className={`pill pill-photo-${status.toLowerCase()}`}>{PHOTO_LABELS[status]}</span>;
}

export function Spinner({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="spinner" role="status">
      <Loader2 className="spin" size={18} aria-hidden />
      <span>{label}</span>
    </div>
  );
}

type Tone = "error" | "warning" | "info" | "success";
const ICONS = { error: AlertCircle, warning: AlertTriangle, info: Info, success: CheckCircle2 };

export function Alert({
  tone = "error",
  title,
  children,
  onClose,
}: {
  tone?: Tone;
  title?: ReactNode;
  children?: ReactNode;
  onClose?: () => void;
}) {
  const Icon = ICONS[tone];
  return (
    <div className={`alert alert-${tone}`} role={tone === "error" ? "alert" : "status"}>
      <Icon size={18} aria-hidden className="alert-icon" />
      <div className="alert-body">
        {title && <strong>{title}</strong>}
        {children && <div>{children}</div>}
      </div>
      {onClose && (
        <button className="icon-btn" onClick={onClose} aria-label="Dismiss">
          <X size={16} />
        </button>
      )}
    </div>
  );
}

/** Shows an ApiError (message + bullet list of server validation errors). */
export function ErrorAlert({ error, onClose }: { error: unknown; onClose?: () => void }) {
  if (!error) return null;
  const err = error as { message?: string; errors?: string[] };
  return (
    <Alert tone="error" title={err.message ?? "Something went wrong."} onClose={onClose}>
      {err.errors && err.errors.length > 0 && (
        <ul className="bullets">
          {err.errors.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}
    </Alert>
  );
}

export function EmptyState({ icon, title, children }: { icon?: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      {icon && <div className="empty-icon">{icon}</div>}
      <h3>{title}</h3>
      {children && <div className="muted">{children}</div>}
    </div>
  );
}

export function StatCard({ label, value, icon, tone }: { label: string; value: number | string; icon: ReactNode; tone: string }) {
  return (
    <div className={`stat stat-${tone}`}>
      <div className="stat-icon">{icon}</div>
      <div>
        <div className="stat-value">{value}</div>
        <div className="stat-label">{label}</div>
      </div>
    </div>
  );
}

export function Modal({
  title,
  children,
  footer,
  onClose,
  wide,
}: {
  title: string;
  children: ReactNode;
  footer?: ReactNode;
  onClose: () => void;
  wide?: boolean;
}) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    document.addEventListener("keydown", onKey);
    ref.current?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${wide ? "modal-wide" : ""}`} role="dialog" aria-modal="true" aria-label={title} tabIndex={-1} ref={ref}>
        <div className="modal-head">
          <h2>{title}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Close">
            <X size={18} />
          </button>
        </div>
        <div className="modal-body">{children}</div>
        {footer && <div className="modal-foot">{footer}</div>}
      </div>
    </div>
  );
}

export function Section({ title, icon, actions, children, className = "" }: {
  title: ReactNode;
  icon?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`card ${className}`}>
      <div className="card-head">
        <h2>
          {icon}
          {title}
        </h2>
        {actions && <div className="card-actions">{actions}</div>}
      </div>
      <div className="card-body">{children}</div>
    </section>
  );
}

/** Read-only label/value pair. */
export function KV({ label, children, wide }: { label: string; children: ReactNode; wide?: boolean }) {
  const empty = children === null || children === undefined || children === "";
  return (
    <div className={`kv ${wide ? "kv-wide" : ""}`}>
      <div className="kv-label">{label}</div>
      <div className="kv-value">{empty ? <span className="muted">—</span> : children}</div>
    </div>
  );
}

/** Password input with an eye button to show/hide what was typed (hidden by default). */
export function PasswordInput(props: Omit<InputHTMLAttributes<HTMLInputElement>, "type">) {
  const [visible, setVisible] = useState(false);
  const label = visible ? "Hide password" : "Show password";
  return (
    <div className="password-input">
      <input {...props} type={visible ? "text" : "password"} />
      <button type="button" className="password-toggle" onClick={() => setVisible((v) => !v)}
              aria-label={label} title={label} aria-pressed={visible} aria-controls={props.id}>
        {visible ? <EyeOff size={16} aria-hidden="true" /> : <Eye size={16} aria-hidden="true" />}
      </button>
    </div>
  );
}

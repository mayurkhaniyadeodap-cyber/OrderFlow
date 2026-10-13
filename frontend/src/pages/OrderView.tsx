import { Camera, CheckCircle2, FileText, Globe2, Lock, Package, PlayCircle, Printer, Trash2, Truck, User as UserIcon } from "lucide-react";
import { useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api, openFile } from "../api";
import { useAuth } from "../auth";
import { DeleteOrderDialog, RestoreOrderButton } from "../components/DeleteOrder";
import { Discussion } from "../components/Discussion";
import { AttachmentList } from "../components/Files";
import { useToast } from "../components/Toast";
import { Alert, ErrorAlert, KV, Modal, Section, StatusPill } from "../components/ui";
import { fmtDateTime, fmtMoney, fmtNumber, fmtSourceDate } from "../format";
import type { OrderDetail, PrintingStatus } from "../types";
import { META_LABELS } from "./orderForm";

const FLOW: PrintingStatus[] = ["New", "Processing", "Print Done"];

/** Read-only order view: Live orders for both roles (and archived drafts for Sales). */
export function OrderView({ order, setOrder }: { order: OrderDetail; setOrder: (o: OrderDetail) => void }) {
  const { user } = useAuth();
  const toast = useToast();
  const [confirmStatus, setConfirmStatus] = useState<PrintingStatus | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const photoInput = useRef<HTMLInputElement>(null);
  const [deleting, setDeleting] = useState(false);
  const printing = user?.role === "printing";
  const next = order.permissions.next_printing_statuses[0];

  const changeStatus = async (status: PrintingStatus) => {
    setBusy(true);
    setError(null);
    try {
      setOrder(await api.post<OrderDetail>(`/api/orders/${order.id}/printing-status`, { status }));
      toast(`Printing status set to ${status}`);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
      setConfirmStatus(null);
    }
  };

  const uploadPhoto = async (file: File) => {
    const data = new FormData();
    data.append("file", file);
    try {
      setOrder(await api.upload<OrderDetail>(`/api/orders/${order.id}/photos`, data));
      toast("Photo uploaded");
    } catch (err) {
      toast((err as Error).message, "error");
    }
  };

  const meta = Object.entries(order.source_meta).filter(([, v]) => v !== null && v !== "");
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="eyebrow">
            <StatusPill status={order.status} /> <StatusPill status={order.printing_status} />
            {order.status === "Live" && (
              <span className="locked-tag">
                <Lock size={12} /> Details locked
              </span>
            )}
          </div>
          <h1>{order.internal_order_no ?? `Draft #${order.id}`}</h1>
          <p className="muted">
            {order.customer_name ?? "—"} · Live {fmtDateTime(order.live_at)}
            {order.published_by && <> by {order.published_by}</>}
          </p>
        </div>
        <div className="head-actions">
          {order.has_source_pdf && (
            <button className="btn btn-secondary" onClick={() => openFile(`/api/orders/${order.id}/source-pdf`).catch((e) => toast(e.message, "error"))}>
              <FileText size={16} /> Source PDF
            </button>
          )}
          {order.permissions.can_restore && <RestoreOrderButton order={order} onRestored={setOrder} />}
          {order.permissions.can_delete && (
            <button className="btn btn-ghost danger" onClick={() => setDeleting(true)}>
              <Trash2 size={16} /> Delete order
            </button>
          )}
          <Link className="btn btn-secondary" to={`/orders/${order.id}/print`}>
            <Printer size={16} /> Print order
          </Link>
          {printing && next && (
            <button className={`btn ${next === "Print Done" ? "btn-success" : "btn-primary"}`} disabled={busy} onClick={() => setConfirmStatus(next)}>
              {next === "Print Done" ? <CheckCircle2 size={16} /> : <PlayCircle size={16} />}
              {next === "Processing" ? "Start processing" : "Mark Print Done"}
            </button>
          )}
        </div>
      </div>

      <ErrorAlert error={error} onClose={() => setError(null)} />
      {order.is_archived && (
        <Alert tone="warning" title="This order is deleted (archived)">
          It is hidden from lists{order.status === "Live" ? " and the Printing queue" : ""}. Its details and history are kept
          {order.permissions.can_restore ? "; use Restore order to bring it back." : " and an Admin can restore it."}
        </Alert>
      )}

      {order.status === "Live" && (
        <div className="progress" aria-label="Printing progress">
          {FLOW.map((step, i) => {
            const idx = FLOW.indexOf(order.printing_status ?? "New");
            const when = step === "New" ? order.live_at : step === "Processing" ? order.processing_at : order.print_done_at;
            return (
              <div key={step} className={`step ${i < idx ? "done" : i === idx ? "current" : ""}`}>
                <div className="step-dot">{i < idx || (i === idx && step === "Print Done") ? <CheckCircle2 size={16} /> : i + 1}</div>
                <div>
                  <div className="step-name">{step}</div>
                  <div className="muted small">{when ? fmtDateTime(when) : "—"}</div>
                </div>
              </div>
            );
          })}
          {order.printing_status === "Print Done" && (
            <div className="step-lock">
              <Lock size={14} /> Print Done is final
            </div>
          )}
        </div>
      )}

      <div className="grid-2">
        <Section title="Customer & PO" icon={<UserIcon size={18} />}>
          <div className="kv-grid">
            <KV label="Customer">{order.customer_name}</KV>
            <KV label="Source PO no.">{order.po_number}</KV>
            <KV label="Source status">{order.source_status}</KV>
            <KV label="Source order date">{order.source_order_date ? fmtSourceDate(order.source_order_date) : null}</KV>
            <KV label="Contact">{order.contact}</KV>
            <KV label="Email">{order.email}</KV>
            <KV label="GSTIN">{order.gstin}</KV>
            <KV label="Executive">{order.executive}</KV>
            <KV label="Billing address" wide>
              <span className="pre">{order.billing_address}</span>
            </KV>
          </div>
        </Section>
        <Section title="Shipping" icon={<Truck size={18} />}>
          <div className="kv-grid">
            <KV label="Ship-to name">{order.shipping_name}</KV>
            <KV label="Shipping address" wide>
              <span className="pre">{order.shipping_address}</span>
            </KV>
            {meta.map(([k, v]) => (
              <KV key={k} label={META_LABELS[k] ?? k} wide={k === "seller"}>
                {typeof v === "object" ? JSON.stringify(v) : String(v)}
              </KV>
            ))}
          </div>
        </Section>
      </div>

      <Section title={`Products (${order.items.length})`} icon={<Package size={18} />}>
        <div className="table-wrap">
          <table className="table items-table">
            <thead>
              <tr>
                <th>#</th>
                <th>SKU / product</th>
                <th className="num">Qty</th>
                <th>Location</th>
                <th>Customization</th>
                <th>Notes</th>
                {!printing && <th className="num">Rate</th>}
                {!printing && <th className="num">Value</th>}
              </tr>
            </thead>
            <tbody>
              {order.items.map((it, i) => (
                <tr key={it.id ?? i}>
                  <td data-label="#">{i + 1}</td>
                  <td data-label="SKU / product">
                    <div className="cell-main mono">{it.sku}</div>
                    <div className="muted small">{it.product_name}</div>
                    <div className="muted small">
                      {[it.weight && `Wt ${it.weight}`, it.hsn && `HSN ${it.hsn}`, it.tax].filter(Boolean).join(" · ")}
                    </div>
                  </td>
                  <td data-label="Qty" className="num strong">{it.quantity}</td>
                  <td data-label="Location">{it.location ?? <span className="muted">—</span>}</td>
                  <td data-label="Customization">
                    {it.customization_text && <div><b>Text:</b> {it.customization_text}</div>}
                    {it.customization_names.length > 0 && (
                      <details>
                        <summary><b>{it.customization_names.length} individual names</b></summary>
                        <ol className="names-list">{it.customization_names.map((n, k) => <li key={k}>{n}</li>)}</ol>
                      </details>
                    )}
                    {it.logo_reference && <div><b>Logo:</b> {it.logo_reference}</div>}
                    <AttachmentList files={it.attachments ?? []} />
                    {!it.customization_text && !it.customization_names.length && !it.logo_reference && !(it.attachments ?? []).length && <span className="muted">—</span>}
                  </td>
                  <td data-label="Notes">{it.notes ?? <span className="muted">—</span>}</td>
                  {!printing && <td data-label="Rate" className="num">{fmtNumber(it.rate)}</td>}
                  {!printing && <td data-label="Value" className="num">{fmtNumber(it.value)}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {!printing && (
          <div className="totals">
            <KV label="Subtotal">{fmtMoney(order.subtotal)}</KV>
            {order.packaging_charges !== null && <KV label="Packaging">{fmtMoney(order.packaging_charges)}</KV>}
            {order.processing_charges !== null && <KV label="Processing">{fmtMoney(order.processing_charges)}</KV>}
            {order.additional_charges !== null && <KV label="Additional">{fmtMoney(order.additional_charges)}</KV>}
            {order.tax !== null && <KV label="Tax">{fmtMoney(order.tax)}</KV>}
            <KV label="Total"><strong>{fmtMoney(order.total)}</strong></KV>
          </div>
        )}
      </Section>

      <Section title="Global customization" icon={<Globe2 size={18} />}>
        <div className="kv-grid">
          <KV label="Name / text for whole order" wide>{order.global_customization && <span className="pre">{order.global_customization}</span>}</KV>
          <KV label="Global names" wide>{order.global_names.length ? order.global_names.join(", ") : null}</KV>
          <KV label="Logo / artwork reference">{order.global_logo_reference}</KV>
          <KV label="Global notes" wide>{order.global_notes && <span className="pre">{order.global_notes}</span>}</KV>
        </div>
        <AttachmentList files={order.global_attachments} />
      </Section>

      {order.status === "Live" && (
        <Section
          title={`Post-print photos (${order.photos.length})`}
          icon={<Camera size={18} />}
          actions={
            order.permissions.can_upload_photos ? (
              <>
                <button className="btn btn-sm btn-secondary" onClick={() => photoInput.current?.click()}>
                  <Camera size={14} /> Upload photo
                </button>
                <input
                  ref={photoInput}
                  type="file"
                  hidden
                  accept="image/png,image/jpeg,image/gif,image/webp"
                  onChange={(e) => {
                    const f = e.target.files?.[0];
                    if (f) uploadPhoto(f);
                    e.target.value = "";
                  }}
                />
              </>
            ) : undefined
          }
          className="no-print"
        >
          {order.photos.length === 0 ? (
            <p className="muted">
              {order.printing_status === "Print Done"
                ? printing
                  ? "Upload photos of the finished print for the record."
                  : "No photos uploaded yet."
                : "Photos can be uploaded by Printing after the order is marked Print Done."}
            </p>
          ) : (
            <AttachmentList files={order.photos} />
          )}
        </Section>
      )}

      <Discussion order={order} onChange={setOrder} />

      {deleting && <DeleteOrderDialog order={order} onClose={() => setDeleting(false)} onDeleted={(o) => { setDeleting(false); setOrder(o); }} />}

      {confirmStatus && (
        <Modal
          title={confirmStatus === "Print Done" ? "Mark as Print Done?" : "Start processing?"}
          onClose={() => setConfirmStatus(null)}
          footer={
            <>
              <button className="btn btn-ghost" onClick={() => setConfirmStatus(null)}>Cancel</button>
              <button className={`btn ${confirmStatus === "Print Done" ? "btn-success" : "btn-primary"}`} disabled={busy} onClick={() => changeStatus(confirmStatus)}>
                {confirmStatus === "Print Done" ? "Yes, Print Done" : "Start processing"}
              </button>
            </>
          }
        >
          {confirmStatus === "Print Done" ? (
            <Alert tone="warning" title="This is final">
              Print Done cannot be undone or changed afterwards. Confirm that every product and customization for {order.internal_order_no} is printed.
            </Alert>
          ) : (
            <p>Move {order.internal_order_no} from New to Processing. Status can only move forward.</p>
          )}
        </Modal>
      )}
    </div>
  );
}

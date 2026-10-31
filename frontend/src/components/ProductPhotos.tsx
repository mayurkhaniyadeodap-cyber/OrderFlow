import { Camera, CheckCircle2, XCircle } from "./icons";
import { useRef, useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import { fmtDateTime } from "../format";
import type { OrderDetail, OrderItem } from "../types";
import { AttachmentList } from "./Files";
import { useToast } from "./Toast";
import { Alert, ErrorAlert, Modal, PhotoPill, Section } from "./ui";

/** Products whose print preview Sales has not confirmed yet (Print Done is blocked until this is empty). */
export function unconfirmedPreviews(order: OrderDetail): OrderItem[] {
  return order.items.filter((it) => it.photo_status !== "Confirmed");
}

/**
 * Print preview photos, one block per product row. Printing uploads a preview of each product (New/Processing);
 * Sales (or Admin) confirms it or rejects it with a reason. Print Done needs every product confirmed.
 */
export function ProductPhotos({ order, setOrder, locked }: {
  order: OrderDetail;
  setOrder: (o: OrderDetail) => void;
  /** Reason the upload / review buttons are unavailable for now (e.g. unsaved edits in the editor). */
  locked?: string;
}) {
  const { user } = useAuth();
  const toast = useToast();
  const [reviewing, setReviewing] = useState<{ item: OrderItem; action: "confirm" | "reject" } | null>(null);
  const printing = user?.role === "printing";
  const unlinked = order.photos.filter((p) => !p.item_id);
  const count = (status: OrderItem["photo_status"]) => order.items.filter((it) => (it.photo_status ?? null) === status).length;
  const waiting = unconfirmedPreviews(order).length;

  const upload = async (item: OrderItem, file: File) => {
    const data = new FormData();
    data.append("file", file);
    data.append("item_id", String(item.id));
    try {
      setOrder(await api.upload<OrderDetail>(`/api/orders/${order.id}/photos`, data));
      toast(`Preview uploaded for ${item.sku ?? "the product"}`);
    } catch (err) {
      toast((err as Error).message, "error");
    }
  };

  return (
    <Section title="Print preview photos (product-wise)" icon={<Camera size={18} />} className="no-print">
      {order.printing_status !== "Print Done" && waiting > 0 && (
        <Alert tone="info" title={`${waiting} of ${order.items.length} product preview${order.items.length === 1 ? "" : "s"} not confirmed yet`}>
          {printing
            ? "Upload a preview photo of each product. Sales must confirm every product before you can mark Print Done."
            : "Printing uploads a preview photo of each product. Check each one and press Confirm preview or Reject."}
        </Alert>
      )}
      {locked && <Alert tone="warning">{locked}</Alert>}
      <div className="photo-summary" aria-label="Preview summary">
        <span className="pill pill-photo-confirmed">{count("Confirmed")} confirmed</span>
        <span className="pill pill-photo-pending">{count("Pending")} waiting</span>
        <span className="pill pill-photo-rejected">{count("Rejected")} rejected</span>
        <span className="pill pill-photo-missing">{count(null)} no preview yet</span>
        {order.status === "Live" && !order.permissions.can_edit && order.printing_status !== "Print Done" && (
          <span className="muted small">Updates automatically, no need to refresh.</span>
        )}
      </div>
      <div className="photo-items">
        {order.items.map((item, i) => (
          <ProductPhotoRow
            key={item.id ?? i}
            index={i}
            item={item}
            canUpload={!locked && order.permissions.can_upload_photos && item.photo_status !== "Confirmed"}
            canReview={!locked && order.permissions.can_review_photos && item.photo_status === "Pending" && (item.photos ?? []).length > 0}
            printing={printing}
            onUpload={(f) => upload(item, f)}
            onReview={(action) => setReviewing({ item, action })}
          />
        ))}
      </div>
      {unlinked.length > 0 && (
        <div className="photo-item" style={{ marginTop: 10 }}>
          <strong>Other photos (not linked to a product)</strong>
          <AttachmentList files={unlinked} />
        </div>
      )}
      {reviewing && (
        <PhotoReviewDialog
          order={order}
          item={reviewing.item}
          action={reviewing.action}
          onClose={() => setReviewing(null)}
          onDone={(o) => {
            setReviewing(null);
            setOrder(o);
          }}
        />
      )}
    </Section>
  );
}

function ProductPhotoRow({ index, item, canUpload, canReview, printing, onUpload, onReview }: {
  index: number;
  item: OrderItem;
  canUpload: boolean;
  canReview: boolean;
  printing: boolean;
  onUpload: (f: File) => void;
  onReview: (action: "confirm" | "reject") => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const photos = item.photos ?? [];
  const by = item.photo_reviewed_by ? ` by ${item.photo_reviewed_by} · ${fmtDateTime(item.photo_reviewed_at ?? null)}` : "";
  const name = item.sku ?? `row ${index + 1}`;
  return (
    <div className="photo-item">
      <div className="photo-item-head">
        <span className="item-no">{index + 1}</span>
        <strong className="item-title mono">
          {item.sku ?? "—"} <span className="muted small">× {item.quantity ?? "—"}</span>
        </strong>
        <PhotoPill status={item.photo_status} />
        <div className="photo-item-actions">
          {canReview && (
            <>
              <button className="btn btn-sm btn-ghost danger" onClick={() => onReview("reject")} aria-label={`Reject preview of ${name}`}>
                <XCircle size={14} /> Reject
              </button>
              <button className="btn btn-sm btn-success" onClick={() => onReview("confirm")} aria-label={`Confirm preview of ${name}`}>
                <CheckCircle2 size={14} /> Confirm preview
              </button>
            </>
          )}
          {canUpload && (
            <>
              <button className="btn btn-sm btn-secondary" onClick={() => input.current?.click()} aria-label={`Upload preview for ${name}`}>
                <Camera size={14} /> {item.photo_status === "Rejected" ? "Upload new preview" : "Upload preview"}
              </button>
              <input
                ref={input}
                type="file"
                hidden
                accept="image/png,image/jpeg,image/gif,image/webp"
                onChange={(e) => {
                  const f = e.target.files?.[0];
                  if (f) onUpload(f);
                  e.target.value = "";
                }}
              />
            </>
          )}
        </div>
      </div>
      {item.photo_status === "Confirmed" && (
        <div className="photo-review-note">
          <CheckCircle2 size={13} /> Preview confirmed{by}
          {item.photo_review_note && <> · {item.photo_review_note}</>}
        </div>
      )}
      {item.photo_status === "Rejected" && (
        <div className="photo-review-note rejected">
          <XCircle size={13} /> Preview rejected{by}: <span className="pre">{item.photo_review_note}</span>
          {printing && <div>Fix it and upload a new preview.</div>}
        </div>
      )}
      {item.photo_status === "Pending" && !canReview && (
        <div className="photo-review-note muted">Waiting for Sales to confirm.</div>
      )}
      {photos.length > 0 && <AttachmentList files={photos} />}
    </div>
  );
}

function PhotoReviewDialog({ order, item, action, onClose, onDone }: {
  order: OrderDetail;
  item: OrderItem;
  action: "confirm" | "reject";
  onClose: () => void;
  onDone: (o: OrderDetail) => void;
}) {
  const toast = useToast();
  const [note, setNote] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);
  const reject = action === "reject";
  const name = item.sku ?? "this product";

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const saved = await api.post<OrderDetail>(`/api/orders/${order.id}/items/${item.id}/photo-review`, {
        version: order.version, action, note: note.trim() || null,
      });
      toast(reject ? `Preview of ${name} rejected; Printing will upload a new one` : `Preview of ${name} confirmed`);
      onDone(saved);
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  };

  return (
    <Modal
      title={reject ? `Reject the preview of ${name}?` : `Confirm the preview of ${name}?`}
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className={`btn ${reject ? "btn-danger" : "btn-success"}`} disabled={busy || (reject && !note.trim())} onClick={submit}>
            {reject ? <XCircle size={16} /> : <CheckCircle2 size={16} />} {busy ? "Saving…" : reject ? "Reject preview" : "Yes, confirm"}
          </button>
        </>
      }
    >
      <ErrorAlert error={error} />
      <p>
        {reject
          ? `Printing will see your reason and upload a new preview of ${name} (${order.internal_order_no}).`
          : `Confirm that the preview of ${name} (quantity ${item.quantity ?? "—"}) is correct and can be printed. This cannot be undone.`}
      </p>
      <div className="field">
        <label htmlFor="photo-note">{reject ? "Reason (required)" : "Note (optional)"}</label>
        <textarea id="photo-note" rows={3} maxLength={5000} value={note} onChange={(e) => setNote(e.target.value)}
          placeholder={reject ? "e.g. Logo is too small, please make it bigger and send a new preview" : ""} />
      </div>
    </Modal>
  );
}

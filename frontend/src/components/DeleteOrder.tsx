import { ArchiveRestore, Trash2 } from "lucide-react";
import { useState } from "react";
import { api } from "../api";
import type { OrderDetail } from "../types";
import { useToast } from "./Toast";
import { Alert, ErrorAlert, Modal } from "./ui";

/** Confirmation for deleting an order. Orders are archived (kept with history), never permanently removed. */
export function DeleteOrderDialog({ order, onClose, onDeleted }: {
  order: OrderDetail;
  onClose: () => void;
  onDeleted: (o: OrderDetail) => void;
}) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const label = order.internal_order_no ?? `Draft #${order.id}`;
  const live = order.status === "Live";

  const remove = async () => {
    setBusy(true);
    setError(null);
    try {
      const deleted = await api.post<OrderDetail>(`/api/orders/${order.id}/archive`, { version: order.version });
      toast(`${label} deleted`);
      onDeleted(deleted);
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  };

  return (
    <Modal
      title={`Delete ${label}?`}
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-danger" onClick={remove} disabled={busy}>
            <Trash2 size={16} /> {busy ? "Deleting…" : "Delete order"}
          </button>
        </>
      }
    >
      <ErrorAlert error={error} />
      {live && (
        <Alert tone="warning" title="This order is Live">
          It will be removed from the Printing queue{order.printing_status !== "New" ? ` (printing status: ${order.printing_status})` : ""}.
        </Alert>
      )}
      <p>
        The order is archived, not erased: its details, files and history are kept and an Admin can restore it. The deletion is recorded in
        the activity log.
      </p>
    </Modal>
  );
}

/** Admin: restore a deleted (archived) order. */
export function RestoreOrderButton({ order, onRestored }: { order: OrderDetail; onRestored: (o: OrderDetail) => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const restore = async () => {
    setBusy(true);
    try {
      onRestored(await api.post<OrderDetail>(`/api/orders/${order.id}/restore`, { version: order.version }));
      toast("Order restored");
    } catch (err) {
      toast((err as Error).message, "error");
    } finally {
      setBusy(false);
    }
  };
  return (
    <button className="btn btn-primary" onClick={restore} disabled={busy}>
      <ArchiveRestore size={16} /> {busy ? "Restoring…" : "Restore order"}
    </button>
  );
}

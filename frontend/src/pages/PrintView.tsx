import { ArrowLeft, Printer } from "../components/icons";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { ErrorAlert, Spinner } from "../components/ui";
import { fmtDateTime } from "../format";
import type { OrderDetail } from "../types";

/** Print-friendly order sheet: no navigation, minimal ink, all customization visible. */
export function PrintView() {
  const { id } = useParams();
  const { user } = useAuth();
  const [order, setOrder] = useState<OrderDetail | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    api.get<OrderDetail>(`/api/orders/${id}`).then(setOrder).catch(setError);
  }, [id]);

  if (error) return <div className="print-page"><ErrorAlert error={error} /></div>;
  if (!order) return <div className="print-page"><Spinner /></div>;

  return (
    <div className="print-page">
      <div className="print-toolbar no-print">
        <Link to={`/orders/${order.id}`} className="btn btn-ghost">
          <ArrowLeft size={16} /> Back to order
        </Link>
        <button className="btn btn-primary" onClick={() => window.print()}>
          <Printer size={16} /> Print
        </button>
      </div>
      <article className="sheet">
        <header className="sheet-head">
          <div>
            <div className="sheet-title">{order.internal_order_no ?? "DRAFT — NOT LIVE"}</div>
            <div>Source PO: <b>{order.po_number ?? "—"}</b></div>
          </div>
          <div className="sheet-right">
            <div>Live date: <b>{fmtDateTime(order.live_at)}</b></div>
            <div>Printing status: <b>{order.printing_status ?? "—"}</b></div>
          </div>
        </header>
        <section className="sheet-grid">
          <div>
            <h3>Customer</h3>
            <div>{order.customer_name}</div>
            <div>{order.contact} {order.email && `· ${order.email}`}</div>
          </div>
          <div>
            <h3>Ship to</h3>
            <div>{order.shipping_name}</div>
            <div className="pre">{order.shipping_address}</div>
          </div>
        </section>
        <table className="sheet-table">
          <thead>
            <tr>
              <th>#</th>
              <th>SKU / product</th>
              <th>Qty</th>
              <th>Location</th>
              <th>Customization</th>
              <th>Notes</th>
            </tr>
          </thead>
          <tbody>
            {order.items.map((it, i) => (
              <tr key={it.id ?? i}>
                <td>{i + 1}</td>
                <td>
                  <b>{it.sku}</b>
                  <div className="small">{it.product_name}</div>
                </td>
                <td className="qty">{it.quantity}</td>
                <td>{it.location ?? ""}</td>
                <td>
                  {it.customization_text && <div><b>Text:</b> {it.customization_text}</div>}
                  {it.customization_names.length > 0 && (
                    <div>
                      <b>Names ({it.customization_names.length}):</b>
                      <ol className="names-print">{it.customization_names.map((n, k) => <li key={k}>{n}</li>)}</ol>
                    </div>
                  )}
                  {it.logo_reference && <div><b>Logo:</b> {it.logo_reference}</div>}
                  {(it.attachments ?? []).length > 0 && <div><b>Artwork files:</b> {(it.attachments ?? []).map((a) => a.filename).join(", ")}</div>}
                </td>
                <td>{it.notes ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <section className="sheet-global">
          <h3>Global customization</h3>
          <div className="pre">{order.global_customization || "—"}</div>
          {order.global_names.length > 0 && <div><b>Names:</b> {order.global_names.join(", ")}</div>}
          {order.global_logo_reference && <div><b>Logo:</b> {order.global_logo_reference}</div>}
          {order.global_attachments.length > 0 && <div><b>Artwork files:</b> {order.global_attachments.map((a) => a.filename).join(", ")}</div>}
          <h3>Global notes</h3>
          <div className="pre">{order.global_notes || "—"}</div>
        </section>
        {order.comments.length > 0 && (
          <section className="sheet-global">
            <h3>Comments</h3>
            {order.comments.map((c) => (
              <div key={c.id} className="small">
                <b>{c.actor}</b> ({fmtDateTime(c.created_at)}): {c.text}
              </div>
            ))}
          </section>
        )}
        <footer className="sheet-foot small">
          Printed {fmtDateTime(new Date().toISOString())} by {user?.username} · OrderFlow
        </footer>
      </article>
    </div>
  );
}

import { AlertTriangle, Camera, ChevronRight, Sparkles } from "lucide-react";
import { Link } from "react-router-dom";
import { fmtDateTime, fmtMoney } from "../format";
import type { OrderSummary, Role } from "../types";
import { StatusPill } from "./ui";

export function OrdersTable({ orders, role }: { orders: OrderSummary[]; role: Role }) {
  const sales = role !== "printing"; // Sales and Admin see status and totals
  return (
    <div className="table-wrap">
      <table className="table">
        <thead>
          <tr>
            <th>Order no.</th>
            <th>Source PO</th>
            <th>Customer</th>
            <th>{sales ? "Updated / Live" : "Live date"}</th>
            {sales && <th>Status</th>}
            <th>Printing</th>
            <th className="num">Items / Qty</th>
            {sales && <th className="num">Total</th>}
            <th aria-label="Open" />
          </tr>
        </thead>
        <tbody>
          {orders.map((o) => (
            <tr key={o.id}>
              <td data-label="Order no.">
                <Link to={`/orders/${o.id}`} className="strong-link">
                  {o.internal_order_no ?? <span className="muted">Draft #{o.id}</span>}
                </Link>
              </td>
              <td data-label="Source PO" className="nowrap">{o.po_number ?? <span className="muted">—</span>}</td>
              <td data-label="Customer">
                <div className="cell-main">{o.customer_name ?? <span className="muted">Not set</span>}</div>
                {sales && o.status === "Draft" && (
                  <div className="cell-flags">
                    {o.warning_count > 0 && (
                      <span className="flag flag-warn" title="Extraction warnings to review">
                        <AlertTriangle size={12} /> {o.warning_count} to review
                      </span>
                    )}
                    {!o.has_customization && (
                      <span className="flag flag-muted" title="Customization is required before publishing">
                        <Sparkles size={12} /> No customization
                      </span>
                    )}
                  </div>
                )}
                {sales && o.photo_status === "Pending" && (
                  <div className="cell-flags">
                    <span className="flag flag-warn" title="Printing uploaded a print preview: confirm or reject it">
                      <Camera size={12} /> Preview to confirm
                    </span>
                  </div>
                )}
                {!sales && o.photo_status === "Rejected" && (
                  <div className="cell-flags">
                    <span className="flag flag-warn" title="Sales rejected a print preview: upload a new one">
                      <Camera size={12} /> Preview rejected
                    </span>
                  </div>
                )}
              </td>
              <td data-label={sales ? "Updated / Live" : "Live date"}>
                {o.live_at ? <span className="nowrap">{fmtDateTime(o.live_at)}</span> : <span className="muted">{fmtDateTime(o.updated_at)}</span>}
              </td>
              {sales && (
                <td data-label="Status">
                  <StatusPill status={o.status} />
                </td>
              )}
              <td data-label="Printing">
                <StatusPill status={o.printing_status} />
              </td>
              <td data-label="Items / Qty" className="num">
                {o.item_count} / {o.total_quantity}
              </td>
              {sales && (
                <td data-label="Total" className="num">
                  {fmtMoney(o.total)}
                </td>
              )}
              <td className="row-action">
                <Link to={`/orders/${o.id}`} className="btn btn-sm btn-secondary" aria-label={`Open order ${o.internal_order_no ?? o.id}`}>
                  {sales && o.status === "Draft" ? "Review" : "View"} <ChevronRight size={14} />
                </Link>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

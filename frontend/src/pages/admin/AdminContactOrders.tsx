import { ArrowLeft, ClipboardList, Inbox } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError } from "../../api";
import { useAuth } from "../../auth";
import { EmptyState, ErrorAlert, Section, Spinner, StatusPill } from "../../components/ui";
import { fmtDateTime, fmtSourceDate } from "../../format";
import type { OrderSummary, SalesContactRow } from "../../types";

type LinkedOrder = OrderSummary & { source_order_date: string | null; executive: string | null };

/** Orders linked to one executive / sales contact (matched ignoring case and extra spaces). Read-only. */
export function AdminContactOrdersPage() {
  const { id } = useParams();
  const { refreshKey } = useAuth();
  const [data, setData] = useState<{ contact: SalesContactRow; total: number; items: LinkedOrder[] } | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    setError(null);
    api.get<typeof data>(`/api/admin/contacts/${id}/orders`).then(setData).catch(setError);
  }, [id, refreshKey]);

  const back = (
    <Link to="/admin/contacts" className="btn btn-secondary">
      <ArrowLeft size={16} /> Back to Executive Contacts
    </Link>
  );

  if (error instanceof ApiError && error.status === 404) {
    return (
      <div className="page">
        <EmptyState title="Contact not found">It may have been deleted. {back}</EmptyState>
      </div>
    );
  }

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <div className="eyebrow">Executive contact</div>
          <h1>{data?.contact.name ?? "Contact"}</h1>
          {data && (
            <p className="muted">
              {data.total} linked order{data.total === 1 ? "" : "s"} · matched by name, ignoring capitalization and extra spaces · deleted orders not
              included
            </p>
          )}
        </div>
        {back}
      </div>
      <ErrorAlert error={error} />
      {!data && !error && <Spinner />}
      {data && (
        <Section title={`${data.total} order${data.total === 1 ? "" : "s"}`} icon={<ClipboardList size={18} />}>
          {data.items.length === 0 ? (
            <EmptyState icon={<Inbox size={28} />} title="No orders for this contact yet">
              Orders appear here when a PO with this executive is uploaded or the name is chosen on an order.
            </EmptyState>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Order no.</th>
                    <th>Customer</th>
                    <th>PO number</th>
                    <th>Status</th>
                    <th>Printing</th>
                    <th>Order date</th>
                    <th>Uploaded</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((o) => (
                    <tr key={o.id}>
                      <td data-label="Order no.">
                        <Link to={`/orders/${o.id}`} className="strong-link">
                          {o.internal_order_no ?? `Draft #${o.id}`}
                        </Link>
                      </td>
                      <td data-label="Customer">{o.customer_name ?? <span className="muted">—</span>}</td>
                      <td data-label="PO number" className="nowrap">{o.po_number ?? <span className="muted">—</span>}</td>
                      <td data-label="Status"><StatusPill status={o.status} /></td>
                      <td data-label="Printing"><StatusPill status={o.printing_status} /></td>
                      <td data-label="Order date" className="nowrap">{fmtSourceDate(o.source_order_date)}</td>
                      <td data-label="Uploaded" className="nowrap">{fmtDateTime(o.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Section>
      )}
    </div>
  );
}

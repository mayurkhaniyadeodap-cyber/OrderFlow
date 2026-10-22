import { Camera, Inbox, Search } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { EmptyState, ErrorAlert, PhotoPill, Section, Spinner, StatusPill } from "../../components/ui";
import { fmtDateTime } from "../../format";
import type { PhotoReviewRow } from "../../types";

type Filter = "" | "Pending" | "Confirmed" | "Rejected" | "Missing";
type Counts = Record<Exclude<Filter, "">, number>;

const FILTERS: { value: Filter; label: string }[] = [
  { value: "", label: "All" },
  { value: "Pending", label: "Waiting" },
  { value: "Confirmed", label: "Confirmed" },
  { value: "Rejected", label: "Rejected" },
  { value: "Missing", label: "No preview yet" },
];

/** Admin: print preview status of every product on Live orders (confirmed / rejected / waiting / missing). */
export function AdminPhotosPage() {
  const { refreshKey } = useAuth();
  const [filter, setFilter] = useState<Filter>("");
  const [q, setQ] = useState("");
  const [data, setData] = useState<{ counts: Counts; total: number; items: PhotoReviewRow[] } | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    setError(null);
    const params = new URLSearchParams();
    if (filter) params.set("status", filter);
    if (q.trim()) params.set("q", q.trim());
    const t = setTimeout(() => {
      api.get<typeof data>(`/api/admin/photo-reviews?${params}`).then(setData).catch(setError);
    }, 250);
    return () => clearTimeout(t);
  }, [filter, q, refreshKey]);

  const total = data ? Object.values(data.counts).reduce((a, b) => a + b, 0) : 0;
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Photo Reviews</h1>
          <p className="muted">
            Product-wise print previews of Live orders: Printing uploads a preview of each product, Sales confirms or rejects it. Shows
            which product's preview was confirmed or rejected, by whom, when and why.
          </p>
        </div>
      </div>

      <div className="photo-summary">
        {data && (
          <>
            <span className="pill pill-photo-confirmed">{data.counts.Confirmed} confirmed</span>
            <span className="pill pill-photo-pending">{data.counts.Pending} waiting</span>
            <span className="pill pill-photo-rejected">{data.counts.Rejected} rejected</span>
            <span className="pill pill-photo-missing">{data.counts.Missing} no preview yet</span>
          </>
        )}
      </div>

      <Section
        title={data ? `${data.total} product${data.total === 1 ? "" : "s"}` : "Products"}
        icon={<Camera size={18} />}
        actions={
          <div className="tabs" role="tablist" aria-label="Photo status">
            {FILTERS.map((f) => (
              <button key={f.value} role="tab" aria-selected={filter === f.value} className={filter === f.value ? "active" : ""} onClick={() => setFilter(f.value)}>
                {f.label}
                {data && f.value && <span className="muted small">{data.counts[f.value]}</span>}
                {data && !f.value && <span className="muted small">{total}</span>}
              </button>
            ))}
          </div>
        }
      >
        <div className="field" style={{ maxWidth: 360, marginBottom: 12 }}>
          <label htmlFor="photo-q"><Search size={12} /> Search</label>
          <input id="photo-q" placeholder="Order no., PO, customer, executive or SKU" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <ErrorAlert error={error} />
        {!data && !error && <Spinner />}
        {data && data.items.length === 0 && (
          <EmptyState icon={<Inbox size={28} />} title="No products here">
            Products appear once their order is published Live.
          </EmptyState>
        )}
        {data && data.items.length > 0 && (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th>Order no.</th>
                  <th>Customer / executive</th>
                  <th>Product</th>
                  <th className="num">Qty</th>
                  <th>Preview status</th>
                  <th>Reviewed</th>
                  <th>Reason / note</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((r) => (
                  <tr key={r.item_id}>
                    <td data-label="Order no.">
                      <Link to={`/orders/${r.order_id}`} className="strong-link">{r.internal_order_no ?? `#${r.order_id}`}</Link>
                      <div><StatusPill status={r.printing_status} /></div>
                    </td>
                    <td data-label="Customer / executive">
                      <div className="cell-main">{r.customer_name ?? "—"}</div>
                      <div className="muted small">{r.executive ?? "—"}{r.sales_user ? ` · uploaded by ${r.sales_user}` : ""}</div>
                    </td>
                    <td data-label="Product">
                      <div className="mono">{r.sku ?? "—"}</div>
                      <div className="muted small">Row {r.position + 1} · {r.photo_count} preview{r.photo_count === 1 ? "" : "s"}</div>
                    </td>
                    <td data-label="Qty" className="num">{r.quantity ?? "—"}</td>
                    <td data-label="Preview status"><PhotoPill status={r.photo_status} /></td>
                    <td data-label="Reviewed">
                      {r.photo_reviewed_by ? (
                        <>
                          {r.photo_reviewed_by}
                          <div className="muted small">{fmtDateTime(r.photo_reviewed_at)}</div>
                        </>
                      ) : (
                        <span className="muted">{r.last_photo_at ? `Preview uploaded ${fmtDateTime(r.last_photo_at)}` : "—"}</span>
                      )}
                    </td>
                    <td data-label="Reason / note">{r.photo_review_note ?? <span className="muted">—</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </div>
  );
}

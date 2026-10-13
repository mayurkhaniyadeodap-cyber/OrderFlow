import { Inbox, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { OrdersTable } from "../../components/OrdersTable";
import { EmptyState, ErrorAlert, Section, Spinner } from "../../components/ui";
import type { OrderSummary } from "../../types";

const PAGE = 50;

/** All orders (drafts, Live and discarded drafts) with search and filters. Read-only. */
export function AdminOrdersPage() {
  const { refreshKey } = useAuth();
  const [params, setParams] = useSearchParams();
  const [data, setData] = useState<{ total: number; items: OrderSummary[] } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);
  const get = (k: string) => params.get(k) ?? "";
  const offset = Number(get("offset")) || 0;
  const [qText, setQText] = useState(get("q"));
  useEffect(() => setQText(params.get("q") ?? ""), [params]);

  const query = useMemo(() => {
    const p = new URLSearchParams(params);
    p.set("limit", String(PAGE));
    p.set("offset", String(offset));
    return p.toString();
  }, [params, offset]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .get<{ total: number; items: OrderSummary[] }>(`/api/admin/orders?${query}`)
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(e))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [query, refreshKey]);

  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    next.delete("offset");
    setParams(next, { replace: true });
  };
  const filtered = ["q", "status", "printing_status", "date_from", "date_to"].some((k) => params.get(k));

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>All Orders</h1>
          <p className="muted">Every order in the portal. Admin view is read-only; Sales and Printing keep their workflows.</p>
        </div>
      </div>
      <Section title="Filters" className="filters-card">
        <form
          className="filters admin-order-filters"
          onSubmit={(e) => {
            e.preventDefault();
            set("q", qText.trim());
          }}
        >
          <div className="field">
            <label htmlFor="o-q">Search</label>
            <input id="o-q" type="search" placeholder="Order no, PO, customer, SKU…" value={qText} onChange={(e) => setQText(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="o-status">Status</label>
            <select id="o-status" value={get("status")} onChange={(e) => set("status", e.target.value)}>
              <option value="">Draft and Live</option>
              <option>Draft</option>
              <option>Live</option>
              <option value="Archived">Deleted (archived)</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="o-printing">Printing status</label>
            <select id="o-printing" value={get("printing_status")} onChange={(e) => set("printing_status", e.target.value)}>
              <option value="">All</option>
              <option>New</option>
              <option>Processing</option>
              <option>Print Done</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="o-field">Date</label>
            <select id="o-field" value={get("date_field") || "created"} onChange={(e) => set("date_field", e.target.value)}>
              <option value="created">Uploaded</option>
              <option value="live">Published Live</option>
              <option value="updated">Last updated</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="o-from">From</label>
            <input id="o-from" type="date" value={get("date_from")} onChange={(e) => set("date_from", e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="o-to">To</label>
            <input id="o-to" type="date" value={get("date_to")} onChange={(e) => set("date_to", e.target.value)} />
          </div>
          <div className="filter-actions">
            <button className="btn btn-secondary">Apply</button>
            {filtered && (
              <button type="button" className="btn btn-ghost" onClick={() => setParams(new URLSearchParams(), { replace: true })}>
                <X size={14} /> Clear
              </button>
            )}
          </div>
        </form>
      </Section>
      <ErrorAlert error={error} />
      {!data && loading && <Spinner />}
      {data && (
        <Section title={`${data.total} order${data.total === 1 ? "" : "s"}`} actions={loading ? <Spinner label="Updating…" /> : undefined}>
          {data.items.length === 0 ? (
            <EmptyState icon={<Inbox size={28} />} title={filtered ? "No orders match these filters" : "No orders yet"} />
          ) : (
            <>
              <OrdersTable orders={data.items} role="admin" />
              {data.total > PAGE && (
                <div className="pager">
                  <button className="btn btn-sm btn-secondary" disabled={offset === 0} onClick={() => set("offset", String(Math.max(0, offset - PAGE)))}>Previous</button>
                  <span className="muted small">{offset + 1}–{Math.min(offset + PAGE, data.total)} of {data.total}</span>
                  <button className="btn btn-sm btn-secondary" disabled={offset + PAGE >= data.total}
                    onClick={() => { const n = new URLSearchParams(params); n.set("offset", String(offset + PAGE)); setParams(n, { replace: true }); }}>
                    Next
                  </button>
                </div>
              )}
            </>
          )}
        </Section>
      )}
    </div>
  );
}

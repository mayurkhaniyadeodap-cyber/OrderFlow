import { Inbox, Upload, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { OrdersTable } from "../components/OrdersTable";
import { EmptyState, ErrorAlert, Section, Spinner } from "../components/ui";
import type { OrderSummary } from "../types";

const PAGE = 50;

/** Sales Orders list (all statuses) and Printing Queue (Live only, oldest first). */
export function OrdersListPage({ mode }: { mode: "sales" | "printing" }) {
  const { refreshKey } = useAuth();
  const [params, setParams] = useSearchParams();
  const [data, setData] = useState<{ total: number; items: OrderSummary[] } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);

  const q = params.get("q") ?? "";
  const status = params.get("status") ?? "";
  const printing = params.get("printing_status") ?? "";
  const sort = params.get("sort") ?? (mode === "printing" ? "live_oldest" : "updated");
  const offset = Number(params.get("offset") ?? 0) || 0;
  const [searchText, setSearchText] = useState(q);
  useEffect(() => setSearchText(q), [q]);

  const query = useMemo(() => {
    const p = new URLSearchParams();
    if (q) p.set("q", q);
    if (status) p.set("status", status);
    if (printing) p.set("printing_status", printing);
    p.set("sort", sort);
    p.set("limit", String(PAGE));
    p.set("offset", String(offset));
    return p.toString();
  }, [q, status, printing, sort, offset]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    api
      .get<{ total: number; items: OrderSummary[] }>(`/api/orders?${query}`)
      .then((d) => !cancelled && setData(d))
      .catch((e) => !cancelled && setError(e))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, [query, refreshKey]);

  const update = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    next.delete("offset");
    setParams(next, { replace: true });
  };
  const filtersActive = Boolean(q || status || printing);

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>{mode === "sales" ? "Sales Orders" : "Printing Queue"}</h1>
          <p className="muted">
            {mode === "sales"
              ? "Drafts awaiting review and published Live orders."
              : "Live orders only, oldest Live date first so older jobs are not missed."}
          </p>
        </div>
        {mode === "sales" && (
          <Link to="/upload" className="btn btn-primary">
            <Upload size={16} /> Upload PO
          </Link>
        )}
      </div>

      <Section title="Filters" className="filters-card">
        <form
          className="filters"
          onSubmit={(e) => {
            e.preventDefault();
            const next = new URLSearchParams(params);
            searchText.trim() ? next.set("q", searchText.trim()) : next.delete("q");
            next.delete("offset");
            setParams(next, { replace: true });
          }}
        >
          <div className="field">
            <label htmlFor="f-q">Search</label>
            <input id="f-q" type="search" placeholder="Order no, PO no, customer…" value={searchText} onChange={(e) => setSearchText(e.target.value)} />
          </div>
          {mode === "sales" && (
            <div className="field">
              <label htmlFor="f-status">Order status</label>
              <select id="f-status" value={status} onChange={(e) => update("status", e.target.value)}>
                <option value="">All</option>
                <option>Draft</option>
                <option>Live</option>
              </select>
            </div>
          )}
          <div className="field">
            <label htmlFor="f-printing">Printing status</label>
            <select id="f-printing" value={printing} onChange={(e) => update("printing_status", e.target.value)}>
              <option value="">All</option>
              <option>New</option>
              <option>Processing</option>
              <option>Print Done</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="f-sort">Sort</label>
            <select id="f-sort" value={sort} onChange={(e) => update("sort", e.target.value)}>
              {mode === "sales" && <option value="updated">Recently updated</option>}
              {mode === "sales" && <option value="created">Recently uploaded</option>}
              <option value="live_oldest">Live date — oldest first</option>
              <option value="live_newest">Live date — newest first</option>
            </select>
          </div>
          <div className="filter-actions">
            <button className="btn btn-secondary">Apply</button>
            {filtersActive && (
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
        <Section
          title={`${data.total} order${data.total === 1 ? "" : "s"}`}
          actions={loading ? <Spinner label="Updating…" /> : undefined}
        >
          {data.items.length === 0 ? (
            <EmptyState icon={<Inbox size={28} />} title={filtersActive ? "No orders match these filters" : "No orders yet"}>
              {mode === "sales" ? "Upload a PO PDF to create a draft." : "Orders appear here as soon as Sales publishes them Live."}
            </EmptyState>
          ) : (
            <>
              <OrdersTable orders={data.items} role={mode} />
              {data.total > PAGE && (
                <div className="pager">
                  <button className="btn btn-sm btn-secondary" disabled={offset === 0} onClick={() => update("offset", String(Math.max(0, offset - PAGE)))}>
                    Previous
                  </button>
                  <span className="muted small">
                    {offset + 1}–{Math.min(offset + PAGE, data.total)} of {data.total}
                  </span>
                  <button
                    className="btn btn-sm btn-secondary"
                    disabled={offset + PAGE >= data.total}
                    onClick={() => {
                      const next = new URLSearchParams(params);
                      next.set("offset", String(offset + PAGE));
                      setParams(next, { replace: true });
                    }}
                  >
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

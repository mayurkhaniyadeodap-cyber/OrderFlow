import { History, X } from "../../components/icons";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { EmptyState, ErrorAlert, Section, Spinner } from "../../components/ui";
import { fmtDateTime } from "../../format";
import type { ActivityEntry } from "../../types";

const PAGE = 50;

export function ActivityTable({ items }: { items: ActivityEntry[] }) {
  if (items.length === 0) return <EmptyState icon={<History size={28} />} title="No activity found" />;
  return (
    <div className="table-wrap">
      <table className="table activity-table">
        <thead>
          <tr>
            <th>When</th>
            <th>Who</th>
            <th>Action</th>
            <th>Order / target</th>
            <th>Details</th>
          </tr>
        </thead>
        <tbody>
          {items.map((a) => (
            <tr key={a.id}>
              <td data-label="When" className="nowrap">{fmtDateTime(a.created_at)}</td>
              <td data-label="Who">
                <strong>{a.actor}</strong>
                {a.actor_role && <span className={`role-tag role-${a.actor_role}`}>{a.actor_role}</span>}
              </td>
              <td data-label="Action">
                <span className={`act act-${a.source}`}>{a.label}</span>
              </td>
              <td data-label="Order / target">
                {a.order_id ? (
                  <Link to={`/orders/${a.order_id}`} className="strong-link">{a.target}</Link>
                ) : (
                  a.target ?? <span className="muted">—</span>
                )}
                {a.order_customer && <div className="muted small">{a.order_customer}</div>}
              </td>
              <td data-label="Details" className="details-cell">{a.details ?? <span className="muted">—</span>}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function AdminActivityPage() {
  const { refreshKey } = useAuth();
  const [params, setParams] = useSearchParams();
  const [data, setData] = useState<{ total: number; items: ActivityEntry[]; actions: { value: string; label: string; source: string }[] } | null>(null);
  const [error, setError] = useState<unknown>(null);
  const get = (k: string) => params.get(k) ?? "";
  const offset = Number(get("offset")) || 0;
  const [qText, setQText] = useState(get("q"));
  const [actorText, setActorText] = useState(get("actor"));

  const query = useMemo(() => {
    const p = new URLSearchParams(params);
    p.set("limit", String(PAGE));
    p.set("offset", String(offset));
    return p.toString();
  }, [params, offset]);

  useEffect(() => {
    setError(null);
    api.get<typeof data>(`/api/admin/activity?${query}`).then(setData).catch(setError);
  }, [query, refreshKey]);

  const set = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    next.delete("offset");
    setParams(next, { replace: true });
  };
  const filtered = ["q", "actor", "action", "source", "date_from", "date_to"].some((k) => params.get(k));

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Activity Log</h1>
          <p className="muted">Who created, edited, saved, published and processed orders, plus sign-ins and admin changes.</p>
        </div>
      </div>
      <Section title="Filters" className="filters-card">
        <form
          className="filters"
          onSubmit={(e) => {
            e.preventDefault();
            const next = new URLSearchParams(params);
            qText.trim() ? next.set("q", qText.trim()) : next.delete("q");
            actorText.trim() ? next.set("actor", actorText.trim()) : next.delete("actor");
            next.delete("offset");
            setParams(next, { replace: true });
          }}
        >
          <div className="field">
            <label htmlFor="a-q">Search</label>
            <input id="a-q" type="search" placeholder="Order no, PO, customer, details…" value={qText} onChange={(e) => setQText(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="a-actor">User</label>
            <input id="a-actor" placeholder="username" value={actorText} onChange={(e) => setActorText(e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="a-action">Action</label>
            <select id="a-action" value={get("action")} onChange={(e) => set("action", e.target.value)}>
              <option value="">All actions</option>
              {data?.actions.map((a) => (
                <option key={a.value} value={a.value}>{a.label}</option>
              ))}
            </select>
          </div>
          <div className="field">
            <label htmlFor="a-source">Type</label>
            <select id="a-source" value={get("source")} onChange={(e) => set("source", e.target.value)}>
              <option value="">Orders and admin</option>
              <option value="order">Order activity</option>
              <option value="admin">Sign-ins and admin changes</option>
            </select>
          </div>
          <div className="field">
            <label htmlFor="a-from">From</label>
            <input id="a-from" type="date" value={get("date_from")} onChange={(e) => set("date_from", e.target.value)} />
          </div>
          <div className="field">
            <label htmlFor="a-to">To</label>
            <input id="a-to" type="date" value={get("date_to")} onChange={(e) => set("date_to", e.target.value)} />
          </div>
          <div className="filter-actions">
            <button className="btn btn-secondary">Apply</button>
            {filtered && (
              <button type="button" className="btn btn-ghost" onClick={() => { setQText(""); setActorText(""); setParams(new URLSearchParams(), { replace: true }); }}>
                <X size={14} /> Clear
              </button>
            )}
          </div>
        </form>
      </Section>
      <ErrorAlert error={error} />
      {!data && !error && <Spinner />}
      {data && (
        <Section title={`${data.total} entr${data.total === 1 ? "y" : "ies"}`}>
          <ActivityTable items={data.items} />
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
        </Section>
      )}
    </div>
  );
}

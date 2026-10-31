import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { fmtDateTime, fmtMoney } from "../format";
import type { OrderDetail, OrderSummary, Role } from "../types";
import { AlertTriangle, Camera, ChevronRight, Columns, FilePen, Kanban, Table } from "./icons";
import { OrdersTable } from "./OrdersTable";
import { KV, Spinner, StatusPill } from "./ui";

export type OrdersView = "table" | "board" | "split";

const KEY = "orderflow.ordersView";
const VIEWS: { key: OrdersView; label: string; icon: typeof Table }[] = [
  { key: "table", label: "Table", icon: Table },
  { key: "board", label: "Board", icon: Kanban },
  { key: "split", label: "Split", icon: Columns },
];

function storedView(): OrdersView {
  try {
    const v = localStorage.getItem(KEY);
    return v === "board" || v === "split" ? v : "table";
  } catch {
    return "table";
  }
}

export function useOrdersView(): [OrdersView, (v: OrdersView) => void] {
  const [view, setView] = useState<OrdersView>(storedView);
  return [view, (v) => {
    setView(v);
    try {
      localStorage.setItem(KEY, v);
    } catch {
      /* not remembered */
    }
  }];
}

export function ViewSwitch({ view, onChange }: { view: OrdersView; onChange: (v: OrdersView) => void }) {
  return (
    <div className="view-switch" role="group" aria-label="Orders layout">
      {VIEWS.map(({ key, label, icon: Icon }) => (
        <button key={key} type="button" className={view === key ? "active" : ""} aria-pressed={view === key} onClick={() => onChange(key)}>
          <Icon size={16} aria-hidden /> {label}
        </button>
      ))}
    </div>
  );
}

/** One-click filters above the lists. They set the same URL parameters as the dropdowns below them. */
export function QuickFilters({ status, printing, showDrafts, onPick }: {
  status: string;
  printing: string;
  showDrafts: boolean;
  onPick: (status: string, printing: string) => void;
}) {
  const pills = [
    { label: "All", status: "", printing: "" },
    ...(showDrafts ? [{ label: "Drafts", status: "Draft", printing: "" }, { label: "Live", status: "Live", printing: "" }] : []),
    { label: "New", status: "", printing: "New" },
    { label: "Processing", status: "", printing: "Processing" },
    { label: "Print Done", status: "", printing: "Print Done" },
  ];
  return (
    <div className="quick-filters" role="group" aria-label="Quick filters">
      {pills.map((p) => {
        const active = p.status === status && p.printing === printing;
        return (
          <button key={p.label} type="button" className={active ? "active" : ""} aria-pressed={active} onClick={() => onPick(p.status, p.printing)}>
            {p.label}
          </button>
        );
      })}
    </div>
  );
}

function label(o: OrderSummary) {
  return o.internal_order_no ?? `Draft #${o.id}`;
}

function Flags({ o, sales }: { o: OrderSummary; sales: boolean }) {
  return (
    <>
      {sales && o.status === "Draft" && o.warning_count > 0 && <span className="flag flag-warn"><AlertTriangle size={12} /> {o.warning_count} to review</span>}
      {sales && o.status === "Draft" && !o.has_customization && <span className="flag flag-muted"><FilePen size={12} /> No customization</span>}
      {sales && o.photo_status === "Pending" && <span className="flag flag-warn"><Camera size={12} /> Preview to confirm</span>}
      {o.photo_status === "Rejected" && <span className="flag flag-bad"><Camera size={12} /> Preview rejected</span>}
    </>
  );
}

function BoardCard({ o, sales }: { o: OrderSummary; sales: boolean }) {
  return (
    <Link to={`/orders/${o.id}`} className="board-card">
      <span className="board-top"><b>{label(o)}</b><span>{o.po_number ?? "—"}</span></span>
      <span className="board-name">{o.customer_name ?? "Not set"}</span>
      <span className="board-meta">
        <span>{o.item_count} item{o.item_count === 1 ? "" : "s"} · {o.total_quantity} qty</span>
        {sales && <b>{fmtMoney(o.total)}</b>}
      </span>
      <span className="cell-flags"><Flags o={o} sales={sales} /></span>
    </Link>
  );
}

function OrdersBoard({ orders, role }: { orders: OrderSummary[]; role: Role }) {
  const sales = role !== "printing";
  const columns: { title: string; color: string; match: (o: OrderSummary) => boolean }[] = [
    ...(sales ? [{ title: "Drafts", color: "var(--chart-4)", match: (o: OrderSummary) => o.status === "Draft" }] : []),
    { title: "New", color: "var(--chart-2)", match: (o) => o.status === "Live" && o.printing_status === "New" },
    { title: "Processing", color: "var(--chart-1)", match: (o) => o.printing_status === "Processing" },
    { title: "Print Done", color: "var(--chart-3)", match: (o) => o.printing_status === "Print Done" },
  ];
  return (
    <div className="board">
      {columns.map((c) => {
        const list = orders.filter(c.match);
        return (
          <section className="board-col" key={c.title} aria-label={c.title}>
            <h2><i style={{ background: c.color }} />{c.title}<span>{list.length}</span></h2>
            {list.map((o) => <BoardCard key={o.id} o={o} sales={sales} />)}
            {list.length === 0 && <p className="muted small">No orders</p>}
          </section>
        );
      })}
    </div>
  );
}

function SplitDetail({ order, role }: { order: OrderSummary; role: Role }) {
  const sales = role !== "printing";
  const [detail, setDetail] = useState<OrderDetail | null>(null);
  useEffect(() => {
    let cancelled = false;
    setDetail(null);
    Promise.resolve(api.get<OrderDetail>(`/api/orders/${order.id}`))
      .then((d) => !cancelled && setDetail(d))
      .catch(() => undefined); // the summary below is still useful
    return () => {
      cancelled = true;
    };
  }, [order.id]);
  return (
    <div className="split-detail">
      <div className="page-head">
        <div>
          <h2>{label(order)}</h2>
          <p className="muted">{order.customer_name ?? "Not set"} · {order.po_number ?? "—"}</p>
        </div>
        <Link to={`/orders/${order.id}`} className="btn btn-primary">
          {sales && order.status === "Draft" ? "Review draft" : "Open order"} <ChevronRight size={14} />
        </Link>
      </div>
      <div className="eyebrow"><StatusPill status={order.status} /> <StatusPill status={order.printing_status} /><Flags o={order} sales={sales} /></div>
      <div className="kv-grid">
        <KV label="Items / Qty">{order.item_count} / {order.total_quantity}</KV>
        {sales && <KV label="Total">{fmtMoney(order.total)}</KV>}
        <KV label="Live date">{order.live_at ? fmtDateTime(order.live_at) : null}</KV>
        <KV label="Updated">{fmtDateTime(order.updated_at)}</KV>
      </div>
      {!detail ? <Spinner /> : (
        <div className="table-wrap flat">
          <table className="table">
            <thead><tr><th>SKU / product</th><th className="num">Qty</th><th>Customization</th></tr></thead>
            <tbody>
              {detail.items.map((it, i) => (
                <tr key={it.id ?? i}>
                  <td data-label="SKU / product"><div className="cell-main mono">{it.sku}</div><div className="muted small">{it.product_name}</div></td>
                  <td data-label="Qty" className="num">{it.quantity}</td>
                  <td data-label="Customization">{it.customization_text || (it.customization_names.length ? `${it.customization_names.length} individual names` : <span className="muted">—</span>)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function OrdersSplit({ orders, role }: { orders: OrderSummary[]; role: Role }) {
  const sales = role !== "printing";
  const [picked, setPicked] = useState<number | null>(null);
  const order = orders.find((o) => o.id === picked) ?? orders[0];
  return (
    <section className="card split">
      <div className="split-list">
        {orders.map((o) => (
          <button key={o.id} type="button" className={`split-row ${o.id === order.id ? "active" : ""}`} aria-pressed={o.id === order.id} onClick={() => setPicked(o.id)}>
            <span className="split-a"><span>{label(o)}</span>{sales && <span>{fmtMoney(o.total)}</span>}</span>
            <span className="split-b"><span>{o.customer_name ?? "Not set"}</span><span>{o.printing_status ?? o.status}</span></span>
            <span className="cell-flags"><Flags o={o} sales={sales} /></span>
          </button>
        ))}
      </div>
      <SplitDetail key={order.id} order={order} role={role} />
    </section>
  );
}

/** One list of orders in the layout the user picked. Every layout opens the same order page. */
export function OrdersContent({ view, orders, role }: { view: OrdersView; orders: OrderSummary[]; role: Role }) {
  if (view === "board") return <OrdersBoard orders={orders} role={role} />;
  if (view === "split") return <OrdersSplit orders={orders} role={role} />;
  return <OrdersTable orders={orders} role={role} />;
}

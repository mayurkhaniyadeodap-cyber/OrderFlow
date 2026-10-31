import { ArrowLeft } from "../components/icons";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError } from "../api";
import { useAuth } from "../auth";
import { EmptyState, ErrorAlert, Spinner } from "../components/ui";
import type { OrderDetail } from "../types";
import { OrderEditor } from "./OrderEditor";
import { OrderView } from "./OrderView";

const AUTO_REFRESH_MS = 10_000;

/** Loads an order and shows the Draft editor (Sales) or the read-only view (Live / Printing). */
export function OrderPage() {
  const { id } = useParams();
  const { user, refreshKey } = useAuth();
  const [order, setOrder] = useState<OrderDetail | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    api
      .get<OrderDetail>(`/api/orders/${id}`)
      .then((o) => !cancelled && setOrder(o))
      .catch((e) => !cancelled && setError(e));
    return () => {
      cancelled = true;
    };
  }, [id, refreshKey]);

  // Live orders shown read-only update themselves, so a preview photo uploaded by Printing appears for Sales,
  // and Sales' confirm / reject appears for Printing, without pressing Refresh. Editors are never refreshed
  // in the background (that would replace unsaved typing).
  const autoRefresh = Boolean(order && order.status === "Live" && !order.permissions.can_edit && !order.is_archived);
  useEffect(() => {
    if (!autoRefresh) return;
    let cancelled = false;
    const reload = () => {
      if (document.hidden) return;
      api
        .get<OrderDetail>(`/api/orders/${id}`)
        .then((o) => !cancelled && setOrder(o))
        .catch(() => undefined); // keep showing the last loaded order; the next try may succeed
    };
    const timer = window.setInterval(reload, AUTO_REFRESH_MS);
    window.addEventListener("focus", reload);
    document.addEventListener("visibilitychange", reload);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
      window.removeEventListener("focus", reload);
      document.removeEventListener("visibilitychange", reload);
    };
  }, [autoRefresh, id]);

  const back = user?.role === "admin" ? "/admin/orders" : user?.role === "printing" ? "/queue" : "/orders";
  if (error instanceof ApiError && error.status === 404) {
    return (
      <div className="page">
        <EmptyState title="Order not found">
          It may not exist, or it is not available to your panel. <Link to={back}>Back to the list</Link>
        </EmptyState>
      </div>
    );
  }
  if (error) return <div className="page"><ErrorAlert error={error} /></div>;
  if (!order || String(order.id) !== id) return <div className="page"><Spinner /></div>;

  return (
    <>
      <div className="back-link no-print">
        <Link to={back}>
          <ArrowLeft size={14} /> {user?.role === "admin" ? "All orders" : user?.role === "printing" ? "Printing queue" : "Sales orders"}
        </Link>
      </div>
      {order.permissions.can_edit ? <OrderEditor order={order} setOrder={setOrder} /> : <OrderView order={order} setOrder={setOrder} />}
    </>
  );
}

import { ArrowLeft } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError } from "../api";
import { useAuth } from "../auth";
import { EmptyState, ErrorAlert, Spinner } from "../components/ui";
import type { OrderDetail } from "../types";
import { OrderEditor } from "./OrderEditor";
import { OrderView } from "./OrderView";

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

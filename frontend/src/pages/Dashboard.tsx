import { CheckCircle2, ClipboardList, FilePen, Inbox, Loader, Printer, Radio, Upload } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { OrdersTable } from "../components/OrdersTable";
import { EmptyState, ErrorAlert, Section, Spinner, StatCard } from "../components/ui";
import type { DashboardData } from "../types";

export function DashboardPage() {
  const { user, refreshKey } = useAuth();
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    setError(null);
    api.get<DashboardData>("/api/dashboard").then(setData).catch(setError);
  }, [refreshKey]);

  const sales = user?.role === "sales";
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>{sales ? "Sales Dashboard" : "Printing Dashboard"}</h1>
          <p className="muted">Welcome back, {user?.full_name || user?.username}.</p>
        </div>
        {sales ? (
          <Link to="/upload" className="btn btn-primary">
            <Upload size={16} /> Upload PO
          </Link>
        ) : (
          <Link to="/queue" className="btn btn-primary">
            <Printer size={16} /> Open printing queue
          </Link>
        )}
      </div>
      <ErrorAlert error={error} />
      {!data && !error && <Spinner />}
      {data && (
        <>
          <div className="stats">
            <StatCard label={sales ? "Total orders" : "Live orders"} value={data.counts.total} icon={<ClipboardList size={20} />} tone="slate" />
            {sales && <StatCard label="Drafts" value={data.counts.draft ?? 0} icon={<FilePen size={20} />} tone="gray" />}
            {sales && <StatCard label="Live" value={data.counts.live} icon={<Radio size={20} />} tone="blue" />}
            <StatCard label="Awaiting printing (New)" value={data.counts.awaiting_printing} icon={<Inbox size={20} />} tone="amber" />
            <StatCard label="Processing" value={data.counts.processing} icon={<Loader size={20} />} tone="violet" />
            <StatCard label="Print Done" value={data.counts.print_done} icon={<CheckCircle2 size={20} />} tone="green" />
          </div>
          <Section
            title={sales ? "Recently updated orders" : "Oldest open printing jobs"}
            actions={
              <Link to={sales ? "/orders" : "/queue"} className="btn btn-sm btn-ghost">
                View all
              </Link>
            }
          >
            {data.recent.length === 0 ? (
              <EmptyState icon={<Inbox size={28} />} title={sales ? "No orders yet" : "Nothing waiting to print"}>
                {sales ? "Upload a PO PDF to create your first draft." : "Live orders appear here automatically."}
              </EmptyState>
            ) : (
              <OrdersTable orders={data.recent} role={data.role} />
            )}
          </Section>
        </>
      )}
    </div>
  );
}

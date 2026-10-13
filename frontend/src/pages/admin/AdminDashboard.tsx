import { Archive, CheckCircle2, ClipboardList, FilePen, History, Inbox, Loader, Radio, Users } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { OrdersTable } from "../../components/OrdersTable";
import { EmptyState, ErrorAlert, Section, Spinner, StatCard } from "../../components/ui";
import type { AdminDashboardData } from "../../types";
import { ActivityTable } from "./AdminActivity";

export function AdminDashboardPage() {
  const { user, refreshKey } = useAuth();
  const [data, setData] = useState<AdminDashboardData | null>(null);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    setError(null);
    api.get<AdminDashboardData>("/api/admin/dashboard").then(setData).catch(setError);
  }, [refreshKey]);

  const peak = data ? Math.max(1, ...data.trend.map((d) => Math.max(d.created, d.published))) : 1;
  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Admin Dashboard</h1>
          <p className="muted">Signed in as {user?.full_name || user?.username}. Order statistics, users and recent activity.</p>
        </div>
        <Link to="/admin/orders" className="btn btn-primary">
          <ClipboardList size={16} /> All orders
        </Link>
      </div>
      <ErrorAlert error={error} />
      {!data && !error && <Spinner />}
      {data && (
        <>
          <div className="stats">
            <StatCard label="Total orders" value={data.orders.total} icon={<ClipboardList size={20} />} tone="slate" />
            <StatCard label="Drafts" value={data.orders.draft} icon={<FilePen size={20} />} tone="gray" />
            <StatCard label="Live" value={data.orders.live} icon={<Radio size={20} />} tone="blue" />
            <StatCard label="Awaiting printing" value={data.orders.new} icon={<Inbox size={20} />} tone="amber" />
            <StatCard label="Processing" value={data.orders.processing} icon={<Loader size={20} />} tone="violet" />
            <StatCard label="Print Done" value={data.orders.print_done} icon={<CheckCircle2 size={20} />} tone="green" />
            <StatCard label="Deleted orders" value={data.orders.archived} icon={<Archive size={20} />} tone="gray" />
          </div>

          <div className="grid-2">
            <Section title="Last 14 days" icon={<History size={18} />}>
              <div className="trend" role="img" aria-label="Orders created and published per day over the last 14 days">
                {data.trend.map((d) => (
                  <div className="trend-day" key={d.date} title={`${d.date}: ${d.created} created, ${d.published} published`}>
                    <div className="trend-bars">
                      <span className="bar bar-created" style={{ height: `${(d.created / peak) * 100}%` }} />
                      <span className="bar bar-published" style={{ height: `${(d.published / peak) * 100}%` }} />
                    </div>
                    <span className="trend-label">{d.date.slice(8)}</span>
                  </div>
                ))}
              </div>
              <div className="trend-legend small">
                <span><i className="dot dot-created" /> Uploaded (created)</span>
                <span><i className="dot dot-published" /> Published Live</span>
              </div>
            </Section>

            <Section title="Users" icon={<Users size={18} />} actions={<Link to="/admin/users" className="btn btn-sm btn-ghost">Manage</Link>}>
              <table className="mini-table">
                <thead>
                  <tr><th>Role</th><th className="num">Active</th><th className="num">Inactive</th></tr>
                </thead>
                <tbody>
                  {(["admin", "sales", "printing"] as const).map((r) => (
                    <tr key={r}>
                      <td className="cap">{r}</td>
                      <td className="num">{data.users[r]?.active ?? 0}</td>
                      <td className="num muted">{data.users[r]?.inactive ?? 0}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Section>
          </div>

          <Section title="Oldest open printing jobs">
            {data.oldest_open.length === 0 ? (
              <EmptyState icon={<Inbox size={28} />} title="Nothing waiting to print" />
            ) : (
              <OrdersTable orders={data.oldest_open} role="admin" />
            )}
          </Section>

          <Section title="Recent activity" icon={<History size={18} />}
            actions={<Link to="/admin/activity" className="btn btn-sm btn-ghost">Full activity log</Link>}>
            <ActivityTable items={data.recent_activity} />
          </Section>
        </>
      )}
    </div>
  );
}

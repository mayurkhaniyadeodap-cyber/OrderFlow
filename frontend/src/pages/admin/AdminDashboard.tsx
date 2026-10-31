import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { HBars, SERIES } from "../../components/charts";
import { ActivityFeed, greeting, Hero, PipelineCard, QuickAction, StageCard, TrendCard, useInsights } from "../../components/DashboardParts";
import { Archive, Camera, CheckCircle2, ClipboardList, Contact, FilePen, History, Inbox, Printer, Radio, Settings, UploadCloud, Users } from "../../components/icons";
import { OrdersTable } from "../../components/OrdersTable";
import { EmptyState, ErrorAlert, Section, Spinner, StatCard } from "../../components/ui";
import type { AdminDashboardData } from "../../types";

export function AdminDashboardPage() {
  const { user, refreshKey } = useAuth();
  const [data, setData] = useState<AdminDashboardData | null>(null);
  const [error, setError] = useState<unknown>(null);
  const insights = useInsights();

  useEffect(() => {
    setError(null);
    api.get<AdminDashboardData>("/api/admin/dashboard").then(setData).catch(setError);
  }, [refreshKey]);

  return (
    <div className="page">
      <Hero title="Admin Dashboard" greeting={`${greeting()}, ${user?.full_name || user?.username}!`} sub="Order statistics, users and recent activity across all panels.">
        <Link to="/admin/orders" className="btn btn-primary"><ClipboardList size={16} /> All orders</Link>
        <Link to="/admin/activity" className="btn btn-secondary">Activity log</Link>
      </Hero>
      <div className="quick-grid">
        <QuickAction to="/upload" title="Upload PO" text="Create a draft for a Sales user" icon={<UploadCloud size={24} />} tone="tone-pro" />
        <QuickAction to="/admin/photos" title="Photo Reviews" text="Print previews by status" icon={<Camera size={24} />} tone="tone-new" />
        <QuickAction to="/admin/users" title="Users" text="Accounts and passwords" icon={<Users size={24} />} tone="tone-tot" />
        <QuickAction to="/admin/settings" title="Settings & Backup" text="Limits and backups" icon={<Settings size={24} />} tone="tone-del" />
      </div>
      <ErrorAlert error={error} />
      {!data && !error && <Spinner />}
      {data && (
        <>
          <div className="stats">
            <StatCard label="Total orders" value={data.orders.total} icon={<ClipboardList size={23} />} tone="tot" />
            <StatCard label="Drafts" value={data.orders.draft} icon={<FilePen size={23} />} tone="dra" />
            <StatCard label="Live" value={data.orders.live} icon={<Radio size={23} />} tone="liv" />
            <StatCard label="Awaiting printing" value={data.orders.new} icon={<Inbox size={23} />} tone="new" />
            <StatCard label="Processing" value={data.orders.processing} icon={<Printer size={23} />} tone="pro" />
            <StatCard label="Print Done" value={data.orders.print_done} icon={<CheckCircle2 size={23} />} tone="don" />
            <StatCard label="Deleted orders" value={data.orders.archived} icon={<Archive size={23} />} tone="del" />
          </div>

          <div className="grid-side">
            <TrendCard title="Orders trend" insights={insights} series={(d) => [
              { name: "Uploaded", values: d.trend.map((r) => r.created), color: SERIES.blue },
              { name: "Published", values: d.trend.map((r) => r.published), color: SERIES.green },
            ]} />
            <Section title="Recent activity" icon={<History size={18} />} className="flush"
              actions={<Link to="/admin/activity" className="btn btn-sm btn-ghost">Full activity log</Link>}>
              <ActivityFeed items={data.recent_activity} />
            </Section>
          </div>

          <div className="grid-3">
            <PipelineCard data={insights.data} />
            <StageCard counts={{ live: data.orders.live, awaiting: data.orders.new, processing: data.orders.processing, done: data.orders.print_done }} />
            <Section title="Orders by executive" icon={<Contact size={18} />}>
              <HBars color={SERIES.green} rows={(insights.data?.executives ?? []).map((e) => ({ label: e.name, value: e.orders }))} />
            </Section>
          </div>

          <div className="grid-side">
            <Section title="Oldest open printing jobs" icon={<Printer size={18} />}>
              {data.oldest_open.length === 0 ? (
                <EmptyState icon={<Inbox size={28} />} title="Nothing waiting to print" />
              ) : (
                <OrdersTable orders={data.oldest_open} role="admin" compact />
              )}
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
        </>
      )}
    </div>
  );
}

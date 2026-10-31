import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { HBars, SERIES } from "../components/charts";
import { AttentionCard, greeting, Hero, QuickAction, StageCard, TrendCard, useAttention, useInsights } from "../components/DashboardParts";
import { Camera, CheckCircle2, ClipboardList, FilePen, Hourglass, Inbox, Printer, Radio, Ranking, SealCheck, UploadCloud } from "../components/icons";
import { OrdersTable } from "../components/OrdersTable";
import { EmptyState, ErrorAlert, Section, Spinner, StatCard } from "../components/ui";
import { fmtMoney } from "../format";
import type { DashboardData } from "../types";

export function DashboardPage() {
  const { user, refreshKey } = useAuth();
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<unknown>(null);
  const insights = useInsights();
  const attention = useAttention();

  useEffect(() => {
    setError(null);
    api.get<DashboardData>("/api/dashboard").then(setData).catch(setError);
  }, [refreshKey]);

  const sales = user?.role === "sales";
  const waiting = attention?.count ?? 0;
  const stages = data && { live: data.counts.live, awaiting: data.counts.awaiting_printing, processing: data.counts.processing, done: data.counts.print_done };
  return (
    <div className="page">
      <Hero
        title={sales ? "Sales Dashboard" : "Printing Dashboard"}
        greeting={`${greeting()}, ${user?.full_name || user?.username}!`}
        sub={sales
          ? `${waiting} order${waiting === 1 ? "" : "s"} waiting on you.`
          : `${(data?.counts.awaiting_printing ?? 0) + (data?.counts.processing ?? 0)} open printing jobs, oldest first.`}
      >
        {sales ? (
          <>
            <Link to="/upload" className="btn btn-primary"><UploadCloud size={16} /> Upload PO</Link>
            <Link to="/orders" className="btn btn-secondary">View orders</Link>
          </>
        ) : (
          <Link to="/queue" className="btn btn-primary"><Printer size={16} /> Open printing queue</Link>
        )}
      </Hero>
      <div className="quick-grid">
        {sales ? (
          <>
            <QuickAction to="/upload" title="Upload PO" text="Turn a PDF into a draft order" icon={<UploadCloud size={24} />} tone="tone-pro" />
            <QuickAction to="/orders" title="Sales Orders" text="View and manage your orders" icon={<ClipboardList size={24} />} tone="tone-liv" />
            <QuickAction to="/orders?status=Draft" title="Drafts to review" text="Fix details and publish" icon={<FilePen size={24} />} tone="tone-dra" />
            <QuickAction to="/orders?printing_status=Processing" title="Print previews" text="Confirm or reject previews" icon={<Camera size={24} />} tone="tone-new" />
          </>
        ) : (
          <>
            <QuickAction to="/queue" title="Printing Queue" text="Live orders, oldest first" icon={<Printer size={24} />} tone="tone-pro" />
            <QuickAction to="/queue?printing_status=New" title="Awaiting printing" text="Jobs not started yet" icon={<Inbox size={24} />} tone="tone-new" />
            <QuickAction to="/queue?printing_status=Processing" title="In processing" text="Jobs on the floor now" icon={<Hourglass size={24} />} tone="tone-liv" />
            <QuickAction to="/queue?printing_status=Print+Done" title="Print Done" text="Finished jobs" icon={<SealCheck size={24} />} tone="tone-don" />
          </>
        )}
      </div>
      <ErrorAlert error={error} />
      {!data && !error && <Spinner />}
      {data && stages && (
        <>
          <div className="stats">
            <StatCard label={sales ? "Total orders" : "Live orders"} value={data.counts.total} icon={<ClipboardList size={23} />} tone="tot" />
            {sales && <StatCard label="Drafts" value={data.counts.draft ?? 0} icon={<FilePen size={23} />} tone="dra" />}
            {sales && <StatCard label="Live" value={data.counts.live} icon={<Radio size={23} />} tone="liv" />}
            <StatCard label="Awaiting printing (New)" value={data.counts.awaiting_printing} icon={<Inbox size={23} />} tone="new" />
            <StatCard label="Processing" value={data.counts.processing} icon={<Printer size={23} />} tone="pro" />
            <StatCard label="Print Done" value={data.counts.print_done} icon={<CheckCircle2 size={23} />} tone="don" />
          </div>
          <div className="grid-side">
            {sales ? (
              <TrendCard title="Your orders trend" insights={insights} series={(d) => [
                { name: "Uploaded", values: d.trend.map((r) => r.created), color: SERIES.blue },
                { name: "Published", values: d.trend.map((r) => r.published), color: SERIES.green },
              ]} />
            ) : (
              <TrendCard title="Jobs finished per day" insights={insights} series={(d) => [
                { name: "Print Done", values: d.trend.map((r) => r.finished), color: SERIES.green },
              ]} />
            )}
            <AttentionCard data={attention} role={data.role} />
          </div>
          <div className="grid-3">
            {sales ? (
              <>
                <StageCard counts={stages} />
                <Section title="Top customers" icon={<Ranking size={18} />}>
                  <HBars rows={(insights.data?.top_customers ?? []).map((c) => ({ label: c.name, value: c.total, text: fmtMoney(c.total) }))} />
                </Section>
              </>
            ) : (
              <>
                <StageCard counts={stages} />
                <Section title="Open jobs by age" icon={<Hourglass size={18} />}>
                  <HBars color={SERIES.amber} empty="No open jobs right now."
                    rows={(insights.data?.job_ages ?? []).map((a) => ({ label: a.label, value: a.count }))} />
                </Section>
              </>
            )}
          </div>
          <Section
            title={sales ? "Recently updated orders" : "Oldest open printing jobs"}
            icon={<ClipboardList size={18} />}
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

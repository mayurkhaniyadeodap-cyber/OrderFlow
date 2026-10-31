import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import { fmtDay, timeAgo } from "../format";
import type { ActivityEntry, AttentionData, Insights, OrderSummary, Role } from "../types";
import { Donut, Pipeline, SERIES, TrendBars, type Series } from "./charts";
import { ArrowRight, AlertTriangle, Calendar, Camera, ChartLineUp, Check, ChevronRight, FilePdf, FilePen, FlowArrow, Funnel, History, Inbox, Printer, Radio, Users } from "./icons";
import { Section, Wave } from "./ui";

const RANGES = [7, 14, 30];

export function greeting(now = new Date()): string {
  const hour = now.getHours();
  return hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
}

/** Chart data for a dashboard. Charts are extras: if they fail, the counts and tables above them still work. */
export function useInsights() {
  const { refreshKey } = useAuth();
  const [days, setDays] = useState(14);
  const [data, setData] = useState<Insights | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let cancelled = false;
    setFailed(false);
    Promise.resolve(api.get<Insights>(`/api/dashboard/insights?days=${days}`))
      .then((d) => !cancelled && setData(d))
      .catch(() => !cancelled && setFailed(true));
    return () => {
      cancelled = true;
    };
  }, [days, refreshKey]);
  return { days, setDays, data, failed };
}

/** The orders waiting on this user, for the notification bell and the dashboard list. */
export function useAttention() {
  const { user, refreshKey } = useAuth();
  const [data, setData] = useState<AttentionData | null>(null);
  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    Promise.resolve(api.get<AttentionData>("/api/dashboard/attention"))
      .then((d) => !cancelled && setData(d))
      .catch(() => !cancelled && setData(null)); // no bell count is better than an error on every page
    return () => {
      cancelled = true;
    };
  }, [user, refreshKey]);
  return data;
}

function attentionNote(o: OrderSummary, role: Role): { text: string; tone: string; icon: ReactNode } {
  if (role === "printing") {
    return o.photo_status === "Rejected"
      ? { text: "Preview rejected: upload a new one", tone: "tone-bad", icon: <Camera size={18} /> }
      : { text: "Waiting to start", tone: "tone-new", icon: <Inbox size={18} /> };
  }
  if (o.status === "Draft") {
    const text = o.warning_count > 0 ? `${o.warning_count} to review` : !o.has_customization ? "Customization needed before publishing" : "Ready to publish";
    return { text, tone: "tone-dra", icon: <FilePen size={18} /> };
  }
  return { text: "Print preview to confirm", tone: "tone-new", icon: <Camera size={18} /> };
}

export function AttentionList({ items, role, onPick }: { items: OrderSummary[]; role: Role; onPick?: () => void }) {
  if (!items.length) return <p className="attention-empty muted">Nothing is waiting on you.</p>;
  return (
    <div className="attention">
      {items.map((o) => {
        const note = attentionNote(o, role);
        return (
          <Link key={o.id} to={`/orders/${o.id}`} className={note.tone} onClick={onPick}>
            <span className="round-icon">{note.icon}</span>
            <span className="attention-text">
              <b>{o.internal_order_no ?? `Draft #${o.id}`} · {o.customer_name ?? "Not set"}</b>
              <span className="muted small">{note.text}</span>
            </span>
            <ChevronRight size={15} className="attention-go" />
          </Link>
        );
      })}
    </div>
  );
}

const ACTIVITY_LOOK: Record<string, { tone: string; icon: ReactNode }> = {
  published: { tone: "tone-liv", icon: <Radio size={18} /> },
  draft_saved: { tone: "tone-dra", icon: <FilePen size={18} /> },
  item_saved: { tone: "tone-dra", icon: <FilePen size={18} /> },
  photo_uploaded: { tone: "tone-new", icon: <Camera size={18} /> },
  photos_confirmed: { tone: "tone-don", icon: <Camera size={18} /> },
  photos_rejected: { tone: "tone-bad", icon: <Camera size={18} /> },
  printing_status_changed: { tone: "tone-pro", icon: <Printer size={18} /> },
  user_created: { tone: "tone-tot", icon: <Users size={18} /> },
};

/** Latest order activity. Sign-ins are left out here: they would crowd out the work, and the full log has them. */
export function ActivityFeed({ items }: { items: ActivityEntry[] }) {
  const orderWork = items.filter((a) => a.source === "order");
  const shown = (orderWork.length ? orderWork : items).slice(0, 5);
  if (!shown.length) return <p className="attention-empty muted">No activity yet.</p>;
  return (
    <div className="feed">
      {shown.map((a) => {
        const look = ACTIVITY_LOOK[a.action] ?? { tone: "tone-pro", icon: <History size={18} /> };
        return (
          <div className={`feed-row ${look.tone}`} key={a.id}>
            <span className="round-icon">{look.icon}</span>
            <span className="attention-text">
              <b>{a.actor}: {a.label}</b>
              <span className="muted small feed-detail" title={a.details ?? undefined}>{a.details ?? a.target ?? "—"}</span>
            </span>
            <span className="muted small nowrap">{timeAgo(a.created_at)}</span>
          </div>
        );
      })}
    </div>
  );
}

export function AttentionCard({ data, role }: { data: AttentionData | null; role: Role }) {
  return (
    <Section title="Needs your action" icon={<AlertTriangle size={18} />} className="flush">
      <AttentionList items={(data?.items ?? []).slice(0, 5)} role={role} />
    </Section>
  );
}

export function Hero({ title, greeting: hello, sub, children }: { title: string; greeting: string; sub: ReactNode; children?: ReactNode }) {
  return (
    <section className="hero">
      <Wave />
      <div className="hero-text">
        <h1>{title}</h1>
        <p className="hero-greeting">{hello}</p>
        <p className="hero-sub">{sub}</p>
        {children && <div className="head-actions">{children}</div>}
      </div>
      <div className="hero-art" aria-hidden="true">
        <span className="hero-sheet"><FilePdf size={46} /></span>
        <ArrowRight size={28} className="hero-arrow" />
        <span className="hero-tick"><Check size={28} /></span>
      </div>
    </section>
  );
}

export function QuickAction({ to, title, text, icon, tone }: { to: string; title: string; text: string; icon: ReactNode; tone: string }) {
  return (
    <Link to={to} className={`quick ${tone}`}>
      <span className="round-icon">{icon}</span>
      <span><b>{title}</b><small>{text}</small></span>
    </Link>
  );
}

function RangePicker({ days, setDays }: { days: number; setDays: (d: number) => void }) {
  return (
    <label className="range-picker">
      <Calendar size={15} aria-hidden />
      <select aria-label="Date range" value={days} onChange={(e) => setDays(Number(e.target.value))}>
        {RANGES.map((n) => <option key={n} value={n}>Last {n} days</option>)}
      </select>
    </label>
  );
}

export function TrendCard({ title, insights, series }: {
  title: string;
  insights: ReturnType<typeof useInsights>;
  series: (d: Insights) => Series[];
}) {
  const { data, days, setDays, failed } = insights;
  return (
    <Section title={title} icon={<ChartLineUp size={18} />} actions={<RangePicker days={days} setDays={setDays} />}>
      {data ? <TrendBars title={title} labels={data.trend.map((r) => fmtDay(r.date))} series={series(data)} />
        : <p className="muted small">{failed ? "Charts could not be loaded. Restart the backend if the portal was just updated." : "Loading…"}</p>}
    </Section>
  );
}

export function StageCard({ counts }: { counts: { live: number; awaiting: number; processing: number; done: number } }) {
  return (
    <Section title="Live orders by stage" icon={<FlowArrow size={18} />}>
      <Donut title="Live orders by printing stage" center={counts.live} centerLabel="Live" parts={[
        { label: "New", value: counts.awaiting, color: SERIES.amber },
        { label: "Processing", value: counts.processing, color: SERIES.blue },
        { label: "Print Done", value: counts.done, color: SERIES.green },
      ]} />
    </Section>
  );
}

export function PipelineCard({ data }: { data: Insights | null }) {
  const p = data?.pipeline;
  return (
    <Section title="Order pipeline" icon={<Funnel size={18} />}>
      <Pipeline steps={[
        { label: "Uploaded", value: p?.uploaded ?? 0 },
        { label: "Published Live", value: p?.published ?? 0 },
        { label: "Processing started", value: p?.processing ?? 0 },
        { label: "Print Done", value: p?.print_done ?? 0 },
      ]} />
    </Section>
  );
}

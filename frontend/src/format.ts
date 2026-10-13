const dateTime = new Intl.DateTimeFormat("en-IN", {
  day: "2-digit",
  month: "short",
  year: "numeric",
  hour: "2-digit",
  minute: "2-digit",
});
const dateOnly = new Intl.DateTimeFormat("en-IN", { day: "2-digit", month: "short", year: "numeric" });
const money = new Intl.NumberFormat("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function fmtDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : dateTime.format(d);
}

export function fmtDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : dateOnly.format(d);
}

/** Source order dates are stored as printed local time "YYYY-MM-DDTHH:MM" (no time zone). */
export function fmtSourceDate(value: string | null | undefined): string {
  if (!value) return "—";
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(value);
  if (!m) return value;
  const [, y, mo, d, h, mi] = m;
  return dateTime.format(new Date(Number(y), Number(mo) - 1, Number(d), Number(h), Number(mi)));
}

export function fmtMoney(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : `₹${money.format(value)}`;
}

export function fmtNumber(value: number | null | undefined): string {
  return value === null || value === undefined ? "—" : money.format(value);
}

export function timeAgo(iso: string): string {
  const diff = (Date.now() - new Date(iso).getTime()) / 1000;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)} min ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} h ago`;
  return fmtDate(iso);
}

export const EVENT_LABELS: Record<string, string> = {
  pdf_uploaded: "PDF uploaded",
  extracted: "Data extracted",
  re_extracted: "Re-extracted from PDF",
  draft_saved: "Draft saved",
  item_saved: "Product saved",
  global_saved: "Global customization saved",
  published: "Published Live",
  printing_status_changed: "Printing status changed",
  comment: "Comment",
  logo_uploaded: "Logo/artwork added",
  logo_removed: "Logo/artwork removed",
  photo_uploaded: "Photo uploaded",
  archived: "Deleted (archived)",
  restored: "Restored",
  live_edited: "Live order edited",
};

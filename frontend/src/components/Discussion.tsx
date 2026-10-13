import { History, MessageSquare, Send } from "lucide-react";
import { useState, type FormEvent } from "react";
import { api } from "../api";
import { EVENT_LABELS, fmtDateTime } from "../format";
import type { OrderDetail } from "../types";
import { ErrorAlert, Section } from "./ui";

/** Comments (allowed before and after Live) and the read-only activity history. */
export function Discussion({ order, onChange }: { order: OrderDetail; onChange: (o: OrderDetail) => void }) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [tab, setTab] = useState<"comments" | "activity">("comments");

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!text.trim()) return;
    setBusy(true);
    setError(null);
    try {
      onChange(await api.post<OrderDetail>(`/api/orders/${order.id}/comment`, { text }));
      setText("");
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section
      title={
        <div className="tabs" role="tablist">
          <button role="tab" aria-selected={tab === "comments"} className={tab === "comments" ? "active" : ""} onClick={() => setTab("comments")}>
            <MessageSquare size={16} /> Comments ({order.comments.length})
          </button>
          <button role="tab" aria-selected={tab === "activity"} className={tab === "activity" ? "active" : ""} onClick={() => setTab("activity")}>
            <History size={16} /> Activity ({order.activity.length})
          </button>
        </div>
      }
      className="discussion no-print"
    >
      {tab === "comments" ? (
        <>
          {order.comments.length === 0 && <p className="muted">No comments yet.</p>}
          <ul className="comments">
            {order.comments.map((c) => (
              <li key={c.id}>
                <div className="comment-head">
                  <strong>{c.actor}</strong>
                  <span className={`role-tag role-${c.actor_role}`}>{c.actor_role}</span>
                  <span className="muted small">{fmtDateTime(c.created_at)}</span>
                </div>
                <div className="comment-text">{c.text}</div>
              </li>
            ))}
          </ul>
          {order.permissions.can_comment && (
            <>
              <ErrorAlert error={error} onClose={() => setError(null)} />
              <form onSubmit={submit} className="comment-form">
                <label htmlFor="comment" className="sr-only">
                  Add a comment
                </label>
                <textarea
                  id="comment"
                  rows={2}
                  maxLength={5000}
                  placeholder={order.status === "Live" ? "Add a comment (order details stay locked)…" : "Add a comment…"}
                  value={text}
                  onChange={(e) => setText(e.target.value)}
                />
                <button className="btn btn-primary" disabled={busy || !text.trim()}>
                  <Send size={16} /> {busy ? "Posting…" : "Post"}
                </button>
              </form>
            </>
          )}
        </>
      ) : (
        <ol className="timeline">
          {[...order.activity].reverse().map((a) => (
            <li key={a.id} className={`tl-${a.event}`}>
              <div className="tl-head">
                <strong>{EVENT_LABELS[a.event] ?? a.event}</strong>
                <span className="muted small">
                  {a.actor} · {fmtDateTime(a.created_at)}
                </span>
              </div>
              {a.details && <div className="tl-details">{a.details}</div>}
            </li>
          ))}
        </ol>
      )}
    </Section>
  );
}

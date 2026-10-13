import { Contact, Pencil, Plus, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { api } from "../../api";
import { useAuth } from "../../auth";
import { useToast } from "../../components/Toast";
import { EmptyState, ErrorAlert, Modal, Section, Spinner } from "../../components/ui";
import { fmtDateTime } from "../../format";
import type { SalesContactRow } from "../../types";

const SOURCE_LABEL: Record<SalesContactRow["source"], string> = {
  extracted: "From a PO",
  manual: "Typed on an order",
  admin: "Added by Admin",
  backfill: "From existing orders",
};

/** Executive / sales contact names used by the Sales Order form. Orders are never changed from here. */
export function AdminContactsPage() {
  const { refreshKey } = useAuth();
  const toast = useToast();
  const [rows, setRows] = useState<SalesContactRow[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [newName, setNewName] = useState("");
  const [adding, setAdding] = useState(false);
  const [addError, setAddError] = useState<unknown>(null);
  const [editing, setEditing] = useState<SalesContactRow | null>(null);

  const load = useCallback(() => {
    setError(null);
    api.get<{ items: SalesContactRow[] }>("/api/admin/contacts").then((d) => setRows(d.items)).catch(setError);
  }, []);
  useEffect(load, [load, refreshKey]);

  const add = async (e: FormEvent) => {
    e.preventDefault();
    if (!newName.trim()) return;
    setAdding(true);
    setAddError(null);
    try {
      const created = await api.post<SalesContactRow>("/api/admin/contacts", { name: newName });
      toast(`${created.name} added`);
      setNewName("");
      load();
    } catch (err) {
      setAddError(err);
    } finally {
      setAdding(false);
    }
  };

  const remove = async (c: SalesContactRow) => {
    const usage = c.orders ? ` It is used on ${c.orders} order(s); those orders keep the name.` : "";
    if (!window.confirm(`Delete "${c.name}" from the contact list?${usage}`)) return;
    try {
      await api.del(`/api/admin/contacts/${c.id}`);
      toast(`${c.name} deleted`);
      load();
    } catch (err) {
      toast((err as Error).message, "error");
    }
  };

  return (
    <div className="page">
      <div className="page-head">
        <div>
          <h1>Executive Contacts</h1>
          <p className="muted">
            Executive / sales contact names offered on the Sales Order form. New names from uploaded POs and from saved drafts are added
            automatically. Renaming or deleting a contact here never changes existing orders.
          </p>
        </div>
      </div>

      <Section title="Add a contact" icon={<Plus size={18} />}>
        <form className="contact-add" onSubmit={add}>
          <div className="field">
            <label htmlFor="c-new">Name</label>
            <input id="c-new" maxLength={200} placeholder="e.g. Dhruv Bhojani - Izzat (6358956693)" value={newName} onChange={(e) => setNewName(e.target.value)} />
          </div>
          <button className="btn btn-primary" disabled={adding || !newName.trim()}>
            <Plus size={16} /> {adding ? "Adding…" : "Add contact"}
          </button>
        </form>
        <ErrorAlert error={addError} onClose={() => setAddError(null)} />
      </Section>

      <ErrorAlert error={error} />
      {!rows && !error && <Spinner />}
      {rows && (
        <Section title={`${rows.length} contact${rows.length === 1 ? "" : "s"}`} icon={<Contact size={18} />}>
          {rows.length === 0 ? (
            <EmptyState title="No contacts yet">Names appear here when POs are uploaded or drafts are saved with an executive.</EmptyState>
          ) : (
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th>Name</th>
                    <th className="num">Orders</th>
                    <th>Added</th>
                    <th aria-label="Actions" />
                  </tr>
                </thead>
                <tbody>
                  {rows.map((c) => (
                    <tr key={c.id}>
                      <td data-label="Name">
                        <Link to={`/admin/contacts/${c.id}`} className="strong-link contact-link" title={`Show the orders for ${c.name}`}>
                          {c.name}
                        </Link>
                      </td>
                      <td data-label="Orders" className="num">{c.orders}</td>
                      <td data-label="Added">
                        {SOURCE_LABEL[c.source] ?? c.source}
                        <div className="muted small">{fmtDateTime(c.created_at)}{c.created_by ? ` · ${c.created_by}` : ""}</div>
                      </td>
                      <td className="row-action">
                        <div className="row-buttons">
                          <button className="btn btn-sm btn-secondary" onClick={() => setEditing(c)} aria-label={`Edit ${c.name}`}>
                            <Pencil size={14} /> Edit
                          </button>
                          <button className="btn btn-sm btn-ghost danger" onClick={() => remove(c)} aria-label={`Delete ${c.name}`}>
                            <Trash2 size={14} /> Delete
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Section>
      )}
      {editing && <EditContactDialog contact={editing} onClose={() => setEditing(null)} onDone={() => { setEditing(null); load(); }} />}
    </div>
  );
}

function EditContactDialog({ contact, onClose, onDone }: { contact: SalesContactRow; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [name, setName] = useState(contact.name);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await api.patch(`/api/admin/contacts/${contact.id}`, { name });
      toast("Contact updated");
      onDone();
    } catch (err) {
      setError(err);
      setBusy(false);
    }
  };

  return (
    <Modal
      title="Edit contact"
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" form="edit-contact" disabled={busy || !name.trim()}>{busy ? "Saving…" : "Save"}</button>
        </>
      }
    >
      <form id="edit-contact" className="form-stack" onSubmit={submit}>
        <ErrorAlert error={error} />
        <div className="field">
          <label htmlFor="c-edit">Name</label>
          <input id="c-edit" maxLength={200} value={name} onChange={(e) => setName(e.target.value)} />
          {contact.orders > 0 && <div className="field-hint">The {contact.orders} order(s) using the old name keep it unchanged.</div>}
        </div>
      </form>
    </Modal>
  );
}

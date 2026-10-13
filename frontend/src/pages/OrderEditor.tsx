import {
  AlertTriangle,
  Calculator,
  CheckCircle2,
  FileText,
  Globe2,
  ImagePlus,
  Package,
  Plus,
  RotateCcw,
  Save,
  Send,
  Sparkles,
  Trash2,
  User as UserIcon,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useBlocker, useNavigate } from "react-router-dom";
import { api, ApiError, openFile } from "../api";
import { useAuth } from "../auth";
import { DeleteOrderDialog } from "../components/DeleteOrder";
import { Discussion } from "../components/Discussion";
import { AttachmentList } from "../components/Files";
import { useToast } from "../components/Toast";
import { Alert, ErrorAlert, Modal, Section, StatusPill } from "../components/ui";
import { fmtDateTime } from "../format";
import type { Attachment, ExtractionWarning, OrderDetail, OrderItem } from "../types";
import {
  blankItem,
  fieldWarnings,
  itemChecks,
  parseNum,
  splitNames,
  toForm,
  toPayload,
  type ItemForm,
  type OrderForm,
  globalToPayload,
  isGlobalDirty,
  isItemDirty,
  itemToPayload,
  keepItemKeys,
  mergeSavedGlobal,
  mergeSavedItem,
} from "./orderForm";

type FieldKey = Exclude<keyof OrderForm, "items">;

/** Save state of one independently saved section (a product card, or "global"). */
export interface SectionState {
  status: "saving" | "saved" | "error";
  error?: unknown;
}

const GLOBAL_KEY = "global";

function withoutPrefix(errors: Record<string, string>, prefix: string) {
  return Object.fromEntries(Object.entries(errors).filter(([k]) => !k.startsWith(prefix)));
}

export function OrderEditor({ order, setOrder }: { order: OrderDetail; setOrder: (o: OrderDetail) => void }) {
  const toast = useToast();
  const navigate = useNavigate();
  const [form, setForm] = useState<OrderForm>(() => toForm(order));
  const [baseline, setBaseline] = useState<OrderForm>(() => toForm(order)); // last state saved on the server
  const [sections, setSections] = useState<Record<string, SectionState>>({});
  const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({});
  const [error, setError] = useState<unknown>(null);
  const [saving, setSaving] = useState(false);
  const [publishOpen, setPublishOpen] = useState(false);
  const [confirm, setConfirm] = useState<null | "reextract">(null);
  const [deleting, setDeleting] = useState(false);
  const { user } = useAuth();
  const isLive = order.status === "Live";
  const [contactNames, setContactNames] = useState<string[]>([]);

  // Saved executive / sales contacts for the dropdown. Optional: the field still accepts any name.
  useEffect(() => {
    let cancelled = false;
    Promise.resolve(api.get<{ items: string[] }>("/api/contacts"))
      .then((d) => !cancelled && setContactNames(d?.items ?? []))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);
  const loadedVersion = useRef(order.version);
  const formRef = useRef(form);
  formRef.current = form;
  const errorRef = useRef<HTMLDivElement>(null);

  // Reset the form only when a new version arrives from the server (not for comments/attachments).
  useEffect(() => {
    if (order.version !== loadedVersion.current) {
      loadedVersion.current = order.version;
      const fresh = keepItemKeys(toForm(order), formRef.current); // keeps each card's open/closed state
      setForm(fresh);
      setBaseline(fresh);
      setSections({});
    }
  }, [order]);

  const dirty = useMemo(() => JSON.stringify(form) !== JSON.stringify(baseline), [form, baseline]);
  const sectionSaving = Object.values(sections).some((s) => s.status === "saving");
  const blocker = useBlocker(({ currentLocation, nextLocation }) => dirty && currentLocation.pathname !== nextLocation.pathname);
  useEffect(() => {
    if (blocker.state === "blocked") {
      if (window.confirm("You have unsaved changes on this draft. Leave without saving?")) blocker.proceed();
      else blocker.reset();
    }
  }, [blocker]);
  useEffect(() => {
    if (!dirty) return;
    const handler = (e: BeforeUnloadEvent) => {
      e.preventDefault();
      e.returnValue = "";
    };
    window.addEventListener("beforeunload", handler);
    return () => window.removeEventListener("beforeunload", handler);
  }, [dirty]);

  const warnings = useMemo(() => fieldWarnings(order.extraction_warnings), [order.extraction_warnings]);
  const set = (field: FieldKey, value: string) => setForm((f) => ({ ...f, [field]: value }));
  const setItem = (key: string, patch: Partial<ItemForm>) =>
    setForm((f) => ({ ...f, items: f.items.map((it) => (it.key === key ? { ...it, ...patch } : it)) }));

  /**
   * A failed Save draft must be noticed even when the user is scrolled down at the products:
   * show a toast and bring the first invalid field (or the error message) into view.
   */
  const reportSaveFailure = useCallback((err: unknown) => {
    setError(err);
    toast(`Draft NOT saved: ${(err as { message?: string }).message ?? "unknown error"}`, "error");
    requestAnimationFrame(() => {
      // Only fields showing a save error (not e.g. the names-count hint, which also uses .has-error).
      const field = document.querySelector(".field-error")?.closest(".field")?.querySelector<HTMLElement>("input, textarea, select");
      (field ?? errorRef.current)?.scrollIntoView?.({ block: "center" });
      field?.focus();
    });
  }, [toast]);

  const save = useCallback(async (): Promise<OrderDetail | null> => {
    const { payload, errors } = toPayload(form, order.version);
    setFieldErrors(errors);
    if (Object.keys(errors).length) {
      reportSaveFailure({
        message: "Please correct the highlighted values.",
        errors: Object.entries(errors).map(([key, msg]) => {
          const label = key.replace(/^items\.(\d+)\./, (_, n) => `Row ${Number(n) + 1} `).replace(/_/g, " ");
          return `${label}: ${msg}`;
        }),
      });
      return null;
    }
    setSaving(true);
    setError(null);
    try {
      const saved = await api.put<OrderDetail>(`/api/orders/${order.id}`, payload);
      setOrder(saved);
      toast(order.status === "Live" ? "Order saved" : "Draft saved");
      return saved;
    } catch (err) {
      reportSaveFailure(err); // edits stay in the form
      return null;
    } finally {
      setSaving(false);
    }
  }, [form, order.id, order.status, order.version, setOrder, toast, reportSaveFailure]);

  const setSection = (key: string, state: SectionState) => setSections((m) => ({ ...m, [key]: state }));

  /** Save one product card only. Other sections keep their unsaved edits. */
  const saveItem = async (key: string) => {
    const idx = form.items.findIndex((it) => it.key === key);
    if (idx < 0) return;
    const sent = form.items[idx];
    const { payload, errors } = itemToPayload(sent, idx);
    setFieldErrors((prev) => ({ ...withoutPrefix(prev, `items.${idx}.`), ...errors }));
    if (Object.keys(errors).length) {
      setSection(key, { status: "error", error: { message: "Correct the highlighted values in this product." } });
      return;
    }
    setSection(key, { status: "saving" });
    try {
      const body = { ...payload, version: order.version };
      const res = sent.id === null
        ? await api.post<{ order: OrderDetail; item_id: number }>(`/api/orders/${order.id}/items`, body)
        : await api.put<{ order: OrderDetail; item_id: number }>(`/api/orders/${order.id}/items/${sent.id}`, body);
      const saved = res.order.items.find((i) => i.id === res.item_id) as OrderItem;
      loadedVersion.current = res.order.version; // a section save must not reset the whole form
      setBaseline((b) => mergeSavedItem(b, key, saved));
      setForm((f) => {
        const current = f.items.find((it) => it.key === key);
        // Typed more in this card while saving? Keep those edits (card stays unsaved), just record the row id.
        if (current && JSON.stringify(current) !== JSON.stringify(sent)) {
          return { ...f, items: f.items.map((it) => (it.key === key ? { ...it, id: saved.id } : it)) };
        }
        return mergeSavedItem(f, key, saved);
      });
      setOrder(res.order);
      setSection(key, { status: "saved" });
    } catch (err) {
      setSection(key, { status: "error", error: err }); // edits stay in the form
    }
  };

  /** Save the global customization section only. */
  const saveGlobal = async () => {
    const sent = globalToPayload(form);
    setSection(GLOBAL_KEY, { status: "saving" });
    try {
      const saved = await api.put<OrderDetail>(`/api/orders/${order.id}/global`, { ...sent, version: order.version });
      loadedVersion.current = saved.version;
      setBaseline((b) => mergeSavedGlobal(b, saved));
      setForm((f) => (JSON.stringify(globalToPayload(f)) === JSON.stringify(sent) ? mergeSavedGlobal(f, saved) : f));
      setOrder(saved);
      setSection(GLOBAL_KEY, { status: "saved" });
    } catch (err) {
      setSection(GLOBAL_KEY, { status: "error", error: err });
    }
  };

  const startPublish = async () => {
    const current = dirty ? await save() : order;
    if (current) setPublishOpen(true);
  };

  const runConfirm = async () => {
    const action = confirm;
    setConfirm(null);
    setError(null);
    try {
      if (action === "reextract") {
        const fresh = await api.post<OrderDetail>(`/api/orders/${order.id}/re-extract`, { version: order.version });
        setOrder(fresh);
        toast("Fields re-extracted from the source PDF");
      }
    } catch (err) {
      setError(err);
    }
  };

  const uploadLogo = async (file: File, itemId: number | null) => {
    const data = new FormData();
    data.append("file", file);
    if (itemId !== null) data.append("item_id", String(itemId));
    try {
      setOrder(await api.upload<OrderDetail>(`/api/orders/${order.id}/attachments`, data));
      toast(`${file.name} attached`);
    } catch (err) {
      toast((err as Error).message, "error");
    }
  };
  const removeLogo = async (a: Attachment) => {
    if (!window.confirm(`Remove ${a.filename}?`)) return;
    try {
      setOrder(await api.del<OrderDetail>(`/api/orders/${order.id}/attachments/${a.id}`));
    } catch (err) {
      toast((err as Error).message, "error");
    }
  };

  const text = (field: FieldKey, label: string, opts: { required?: boolean; multiline?: boolean; type?: string; list?: string; hint?: ReactNode } = {}) => (
    <Field label={label} id={`f-${field}`} required={opts.required} warnings={warnings[field]} error={fieldErrors[field]} hint={opts.hint}>
      {opts.multiline ? (
        <textarea id={`f-${field}`} rows={3} value={form[field]} onChange={(e) => set(field, e.target.value)} />
      ) : (
        <input
          id={`f-${field}`}
          type={opts.type ?? "text"}
          list={opts.list}
          inputMode={opts.type === "money" ? "decimal" : undefined}
          value={form[field]}
          onChange={(e) => set(field, e.target.value)}
        />
      )}
    </Field>
  );

  const reviewCount = order.extraction_warnings.filter((w) => w.level !== "info").length;
  const globalHasCustomization = Boolean(
    form.global_customization.trim() || splitNames(form.global_names).length || form.global_logo_reference.trim() || order.global_attachments.length,
  );

  return (
    <div className="page">
      <div className="page-head sticky-head">
        <div>
          <div className="eyebrow">
            {isLive ? (
              <>{order.internal_order_no} · <StatusPill status="Live" /> <StatusPill status={order.printing_status} /></>
            ) : (
              <>Draft #{order.id} · <StatusPill status="Draft" /></>
            )}{" "}
            {dirty && <span className="unsaved">Unsaved changes</span>}
          </div>
          <h1>{form.customer_name || (isLive ? "Live order" : "Review draft order")}</h1>
          <p className="muted">
            PO {form.po_number || "—"} · uploaded {fmtDateTime(order.created_at)} by {order.created_by}
          </p>
        </div>
        <div className="head-actions">
          {order.has_source_pdf && (
            <button className="btn btn-secondary" onClick={() => openFile(`/api/orders/${order.id}/source-pdf`).catch((e) => toast(e.message, "error"))}>
              <FileText size={16} /> Source PDF
            </button>
          )}
          <button className="btn btn-secondary" onClick={save} disabled={saving || sectionSaving || !dirty}>
            <Save size={16} /> {saving ? "Saving…" : isLive ? "Save order" : "Save draft"}
          </button>
          {order.permissions.can_publish && (
            <button className="btn btn-primary" onClick={startPublish} disabled={saving || sectionSaving}>
              <Send size={16} /> Publish Live
            </button>
          )}
        </div>
      </div>

      <div ref={errorRef}>
        <ErrorAlert error={error} onClose={() => setError(null)} />
      </div>

      {isLive ? (
        <Alert tone="warning" title="You are editing a Live order">
          Printing status: <b>{order.printing_status}</b>. Changes are visible to Printing as soon as you save. The order number, Live date and
          printing status do not change, the order must still meet the publish rules, and every change is recorded in the activity log.
        </Alert>
      ) : (
        <ExtractionPanel order={order} reviewCount={reviewCount} onReextract={() => setConfirm("reextract")} />
      )}

      <Section title="Customer & PO" icon={<UserIcon size={18} />}>
        <div className="form-grid">
          {text("customer_name", "Customer name", { required: true })}
          {text("po_number", "Source PO / order no.")}
          {text("source_status", "Source status (as printed)")}
          {text("source_order_date", "Source order date", { type: "datetime-local" })}
          {text("contact", "Contact number")}
          {text("email", "Email", { type: "email" })}
          {text("gstin", "GSTIN")}
          {text("executive", "Executive / sales contact", {
            list: "executive-list",
            hint: "Pick a saved contact or type a new name; new names are added to the contact list when you save.",
          })}
          <datalist id="executive-list">
            {contactNames.map((n) => <option key={n} value={n} />)}
          </datalist>
        </div>
        {text("billing_address", "Billing address", { multiline: true })}
      </Section>

      <Section
        title={`Products (${form.items.length})`}
        icon={<Package size={18} />}
        actions={
          <button className="btn btn-sm btn-secondary" onClick={() => setForm((f) => ({ ...f, items: [...f.items, blankItem()] }))}>
            <Plus size={14} /> Add product row
          </button>
        }
      >
        {form.items.length === 0 && (
          <Alert tone="warning" title="No product rows">
            Add the products from the source PDF. At least one row is required to publish.
          </Alert>
        )}
        <div className="items">
          {form.items.map((item, idx) => (
            <ItemCard
              key={item.key}
              index={idx}
              item={item}
              errors={fieldErrors}
              warnings={warnings}
              attachments={order.items.find((i) => i.id === item.id)?.attachments ?? []}
              onChange={(patch) => setItem(item.key, patch)}
              onRemove={() => {
                if (window.confirm(`Remove row ${idx + 1} (${item.sku || "no SKU"})? Save the draft to apply.`))
                  setForm((f) => ({ ...f, items: f.items.filter((it) => it.key !== item.key) }));
              }}
              onUploadLogo={(file) => uploadLogo(file, item.id)}
              onRemoveLogo={removeLogo}
              savedRow={item.id !== null}
              dirty={isItemDirty(item, baseline)}
              saveState={sections[item.key]}
              saveDisabled={saving || sectionSaving}
              onSave={() => saveItem(item.key)}
            />
          ))}
        </div>
      </Section>

      <Section title="Global customization" icon={<Globe2 size={18} />} actions={globalHasCustomization ? <span className="flag flag-ok"><CheckCircle2 size={12} /> Set</span> : undefined}>
        <p className="muted small">
          Applies across the whole order. Either global customization or SKU-wise customization (on at least one product) is required. Notes alone do not count.
        </p>
        {text("global_customization", "Name / text for the whole order", { multiline: true })}
        <Field label="Global names (one per line)" id="f-global_names" hint={`${splitNames(form.global_names).length} name(s)`}>
          <textarea id="f-global_names" rows={3} value={form.global_names} onChange={(e) => set("global_names", e.target.value)} />
        </Field>
        {text("global_logo_reference", "Logo / artwork reference")}
        <LogoUpload label="Upload global logo / artwork" disabled={false} onFile={(f) => uploadLogo(f, null)} />
        <AttachmentList files={order.global_attachments} onRemove={removeLogo} />
        {text("global_notes", "Global notes (optional)", { multiline: true })}
        <SectionSaveBar
          label="Save Global Changes"
          dirty={isGlobalDirty(form, baseline)}
          state={sections[GLOBAL_KEY]}
          disabled={saving || sectionSaving}
          onSave={saveGlobal}
        />
      </Section>

      <Discussion order={order} onChange={setOrder} />

      <div className="danger-zone">
        {!isLive && (
          <button className="btn btn-ghost" onClick={() => setConfirm("reextract")} disabled={!order.has_source_pdf}>
            <RotateCcw size={16} /> Re-extract from PDF
          </button>
        )}
        {order.permissions.can_delete && (
          <button className="btn btn-ghost danger" onClick={() => setDeleting(true)}>
            <Trash2 size={16} /> Delete order
          </button>
        )}
      </div>
      {deleting && (
        <DeleteOrderDialog
          order={order}
          onClose={() => setDeleting(false)}
          onDeleted={() => {
            setBaseline(form); // nothing left to protect: do not ask about unsaved changes when leaving
            navigate(user?.role === "admin" ? "/admin/orders" : "/orders");
          }}
        />
      )}

      {publishOpen && <PublishDialog order={order} onClose={() => setPublishOpen(false)} onPublished={(o) => { setPublishOpen(false); setBaseline(form); setOrder(o); }} />}
      {confirm && (
        <Modal
          title="Re-extract from the source PDF?"
          onClose={() => setConfirm(null)}
          footer={
            <>
              <button className="btn btn-ghost" onClick={() => setConfirm(null)}>Cancel</button>
              <button className="btn btn-danger" onClick={runConfirm}>Replace fields</button>
            </>
          }
        >
          <p>Customer, address, amounts and all product rows (including SKU-wise customization and SKU logos) will be replaced with values read from the PDF. Global customization is kept.{dirty && " Your unsaved changes will be lost."}</p>
        </Modal>
      )}
    </div>
  );
}

// ---------------------------------------------------------------- pieces
function Field({ label, id, required, warnings, error, hint, children }: {
  label: string;
  id: string;
  required?: boolean;
  warnings?: ExtractionWarning[];
  error?: string;
  hint?: ReactNode;
  children: ReactNode;
}) {
  const flagged = warnings?.filter((w) => w.level !== "info") ?? [];
  return (
    <div className={`field ${error ? "has-error" : ""} ${flagged.length ? "has-flag" : ""}`}>
      <label htmlFor={id}>
        {label} {required && <span className="req" aria-label="required">*</span>}
      </label>
      {children}
      {error && <div className="field-error">{error}</div>}
      {warnings?.map((w) => (
        <div key={w.message} className={`field-flag level-${w.level}`}>
          {w.level !== "info" && <AlertTriangle size={12} />} {w.message}
        </div>
      ))}
      {hint && !error && <div className="field-hint">{hint}</div>}
    </div>
  );
}

function ExtractionPanel({ order, reviewCount, onReextract }: { order: OrderDetail; reviewCount: number; onReextract: () => void }) {
  const [open, setOpen] = useState(reviewCount > 0);
  const errors = order.extraction_warnings.filter((w) => w.level === "error");
  const tone = errors.length ? "error" : reviewCount ? "warning" : "success";
  return (
    <div className={`extraction extraction-${tone}`}>
      <div className="extraction-head">
        <div>
          <strong>
            {errors.length ? "Extraction problem" : reviewCount ? `${reviewCount} extracted value(s) need review` : "Extraction complete"}
          </strong>
          <div className="small">{order.extraction_note}</div>
        </div>
        <div className="head-actions">
          {errors.length > 0 && order.has_source_pdf && (
            <button className="btn btn-sm btn-secondary" onClick={onReextract}>
              <RotateCcw size={14} /> Retry extraction
            </button>
          )}
          {order.extraction_warnings.length > 0 && (
            <button className="btn btn-sm btn-ghost" onClick={() => setOpen((o) => !o)}>
              {open ? "Hide details" : `Show all notes (${order.extraction_warnings.length})`}
            </button>
          )}
        </div>
      </div>
      {open && (
        <ul className="extraction-list">
          {order.extraction_warnings.map((w, i) => (
            <li key={i} className={`level-${w.level}`}>
              <span className="level-tag">{w.level}</span>
              <span className="field-tag">{w.field.replace(/^items\.(\d+)\./, (_, n) => `row ${Number(n) + 1} · `).replace(/_/g, " ")}</span>
              {w.message}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function LogoUpload({ label, disabled, onFile, hint }: { label: string; disabled: boolean; onFile: (f: File) => void; hint?: string }) {
  const ref = useRef<HTMLInputElement>(null);
  return (
    <div className="logo-upload">
      <button type="button" className="btn btn-sm btn-secondary" disabled={disabled} onClick={() => ref.current?.click()} title={hint}>
        <ImagePlus size={14} /> {label}
      </button>
      {disabled && hint && <span className="muted small">{hint}</span>}
      <input
        ref={ref}
        type="file"
        hidden
        accept="image/png,image/jpeg,image/gif,image/webp,application/pdf"
        onChange={(e) => {
          const f = e.target.files?.[0];
          if (f) onFile(f);
          e.target.value = "";
        }}
      />
    </div>
  );
}

/** Save button + status for an independently saved section. Unsaved edits are kept when a save fails. */
function SectionSaveBar({ label, dirty, state, disabled, onSave }: {
  label: string;
  dirty: boolean;
  state?: SectionState;
  disabled: boolean;
  onSave: () => void;
}) {
  const busy = state?.status === "saving";
  return (
    <div className="section-save">
      {state?.status === "error" && <ErrorAlert error={state.error} />}
      <div className="section-save-row">
        <span className="section-save-status" role="status" aria-live="polite">
          {busy && <span className="muted">Saving…</span>}
          {!busy && dirty && <span className="unsaved">Unsaved changes</span>}
          {!busy && !dirty && state?.status === "saved" && (
            <span className="save-ok"><CheckCircle2 size={14} /> Saved</span>
          )}
        </span>
        <button type="button" className="btn btn-sm btn-primary" disabled={disabled || busy || !dirty} onClick={onSave}>
          <Save size={14} /> {busy ? "Saving…" : label}
        </button>
      </div>
    </div>
  );
}

function ItemCard({
  index, item, errors, warnings, attachments, onChange, onRemove, onUploadLogo, onRemoveLogo, savedRow,
  dirty, saveState, saveDisabled, onSave,
}: {
  index: number;
  item: ItemForm;
  errors: Record<string, string>;
  warnings: Record<string, ExtractionWarning[]>;
  attachments: Attachment[];
  onChange: (patch: Partial<ItemForm>) => void;
  onRemove: () => void;
  onUploadLogo: (f: File) => void;
  onRemoveLogo: (a: Attachment) => void;
  savedRow: boolean;
  dirty: boolean;
  saveState?: SectionState;
  saveDisabled: boolean;
  onSave: () => void;
}) {
  const checks = itemChecks(item);
  const customized = Boolean(item.customization_text.trim() || checks.names.count || item.logo_reference.trim() || attachments.length);
  // Product name, MRP, weight, HSN/SAC, tax and location are not edited here; their stored values are kept
  // in the form and sent back unchanged on save. Customization starts collapsed; each card toggles on its own.
  const [open, setOpen] = useState(false);
  const input = (field: keyof ItemForm, label: string, opts: { numeric?: boolean; wide?: boolean } = {}) => {
    const key = `items.${index}.${field}`;
    const id = `${item.key}-${field}`;
    return (
      <div className={`field ${opts.wide ? "span-2" : ""} ${errors[key] ? "has-error" : ""}`}>
        <label htmlFor={id}>{label}</label>
        <input id={id} inputMode={opts.numeric ? "decimal" : undefined} value={item[field] as string} onChange={(e) => onChange({ [field]: e.target.value })} />
        {errors[key] && <div className="field-error">{errors[key]}</div>}
      </div>
    );
  };
  const rowWarnings = Object.entries(warnings)
    .filter(([k]) => k.startsWith(`items.${index}.`))
    .flatMap(([, ws]) => ws);

  return (
    <div className="item-card">
      <div className="item-head">
        <span className="item-no">{index + 1}</span>
        <strong className="item-title">{item.sku || <span className="muted">New product row</span>}</strong>
        {customized ? (
          <span className="flag flag-ok"><Sparkles size={12} /> Customized</span>
        ) : (
          <span className="flag flag-muted">No SKU customization</span>
        )}
        <button className="icon-btn danger" onClick={onRemove} aria-label={`Remove row ${index + 1}`}>
          <Trash2 size={16} />
        </button>
      </div>
      {rowWarnings.length > 0 && (
        <ul className="row-flags">
          {rowWarnings.map((w) => (
            <li key={w.message} className={`level-${w.level}`}><AlertTriangle size={12} /> {w.message} <span className="muted">(from extraction)</span></li>
          ))}
        </ul>
      )}
      <div className="item-grid">
        {input("sku", "SKU / code *", { wide: true })}
        {input("quantity", "Qty *", { numeric: true })}
        {input("rate", "Rate", { numeric: true })}
        <div className={`field ${errors[`items.${index}.value`] ? "has-error" : ""} ${checks.mismatch ? "has-flag" : ""}`}>
          <label htmlFor={`${item.key}-value`}>Line value</label>
          <div className="input-with-btn">
            <input id={`${item.key}-value`} inputMode="decimal" value={item.value} onChange={(e) => onChange({ value: e.target.value })} />
            {checks.mismatch && (
              <button
                type="button"
                className="icon-btn"
                title="Set line value = rate × quantity"
                onClick={() => {
                  const q = parseNum(item.quantity), r = parseNum(item.rate);
                  if (typeof q === "number" && typeof r === "number") onChange({ value: (Math.round(q * r * 100) / 100).toFixed(2) });
                }}
              >
                <Calculator size={14} />
              </button>
            )}
          </div>
          {checks.mismatch && <div className="field-flag level-warning"><AlertTriangle size={12} /> {checks.mismatch}</div>}
          {errors[`items.${index}.value`] && <div className="field-error">{errors[`items.${index}.value`]}</div>}
        </div>
      </div>

      <button
        type="button"
        className="customize-toggle"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        aria-controls={`${item.key}-customize`}
      >
        <Sparkles size={14} /> SKU-wise customization {open ? "▴" : "▾"}
      </button>
      {open && (
        <div className="customize" id={`${item.key}-customize`}>
          <div className="field">
            <label htmlFor={`${item.key}-ctext`}>Same name / text on every unit</label>
            <input id={`${item.key}-ctext`} value={item.customization_text} onChange={(e) => onChange({ customization_text: e.target.value })} placeholder="e.g. SARADA TECH SOLUTIONS" />
          </div>
          <div className={`field ${checks.names.ok ? "" : "has-error"}`}>
            <label htmlFor={`${item.key}-names`}>Individual names — one per unit, one per line</label>
            <textarea id={`${item.key}-names`} rows={4} value={item.names} onChange={(e) => onChange({ names: e.target.value })} placeholder={"Asha\nRavi\n…"} />
            <div className={`names-count ${checks.names.count === 0 ? "" : checks.names.ok ? "ok" : "bad"}`}>
              {checks.names.count} / {checks.names.qty ?? "?"} names
              {!checks.names.ok && " — must equal the quantity to publish"}
            </div>
          </div>
          <div className="field">
            <label htmlFor={`${item.key}-logo`}>Logo / artwork reference</label>
            <input id={`${item.key}-logo`} value={item.logo_reference} onChange={(e) => onChange({ logo_reference: e.target.value })} placeholder="e.g. Customer logo from WhatsApp 12-Oct" />
          </div>
          <div className="field">
            <span className="label">Logo / artwork files</span>
            <LogoUpload label="Upload logo" disabled={!savedRow} onFile={onUploadLogo} hint={savedRow ? undefined : "Save this product first to attach files"} />
            <AttachmentList files={attachments} onRemove={onRemoveLogo} />
          </div>
          <div className="field span-all">
            <label htmlFor={`${item.key}-notes`}>SKU notes (optional)</label>
            <textarea id={`${item.key}-notes`} rows={2} value={item.notes} onChange={(e) => onChange({ notes: e.target.value })} />
          </div>
        </div>
      )}
      <SectionSaveBar label="Save Changes" dirty={dirty} state={saveState} disabled={saveDisabled} onSave={onSave} />
    </div>
  );
}

function PublishDialog({ order, onClose, onPublished }: { order: OrderDetail; onClose: () => void; onPublished: (o: OrderDetail) => void }) {
  const toast = useToast();
  const [check, setCheck] = useState<{ errors: string[]; warnings: string[] } | null>(null);
  const [reviewed, setReviewed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  useEffect(() => {
    api.get<{ errors: string[]; warnings: string[] }>(`/api/orders/${order.id}/publish-check`).then(setCheck).catch(setError);
  }, [order.id, order.version]);

  const publish = async () => {
    setBusy(true);
    setError(null);
    try {
      const live = await api.post<OrderDetail>(`/api/orders/${order.id}/publish`, { version: order.version, reviewed });
      toast(`Published Live as ${live.internal_order_no}`);
      onPublished(live);
    } catch (err) {
      if (err instanceof ApiError && err.errors.length) setCheck({ errors: err.errors, warnings: err.warnings });
      setError(err);
      setBusy(false);
    }
  };

  const blocked = !check || check.errors.length > 0;
  return (
    <Modal
      title="Publish Live"
      onClose={onClose}
      footer={
        <>
          <button className="btn btn-ghost" onClick={onClose}>Cancel</button>
          <button className="btn btn-primary" disabled={blocked || !reviewed || busy} onClick={publish}>
            <Send size={16} /> {busy ? "Publishing…" : "Publish Live"}
          </button>
        </>
      }
    >
      {!check && !error && <p className="muted">Checking the order…</p>}
      {error && !(error instanceof ApiError && error.errors.length) ? <ErrorAlert error={error} /> : null}
      {check && check.errors.length > 0 && (
        <Alert tone="error" title="Fix these before publishing">
          <ul className="bullets">{check.errors.map((e) => <li key={e}>{e}</li>)}</ul>
        </Alert>
      )}
      {check && check.errors.length === 0 && (
        <Alert tone="success" title="Ready to publish">
          Publishing generates the internal order number, records the Live date/time, locks all order details and sends the order to the Printing queue as <b>New</b>. Only comments can be added afterwards.
        </Alert>
      )}
      {check && check.warnings.length > 0 && (
        <Alert tone="warning" title="Please double-check">
          <ul className="bullets">{check.warnings.map((w) => <li key={w}>{w}</li>)}</ul>
        </Alert>
      )}
      <label className="checkbox">
        <input type="checkbox" checked={reviewed} onChange={(e) => setReviewed(e.target.checked)} disabled={blocked} />
        I reviewed the extracted data against the source PDF and the customization is correct.
      </label>
    </Modal>
  );
}

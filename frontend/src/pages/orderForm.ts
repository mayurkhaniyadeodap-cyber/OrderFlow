/** Draft form state <-> API payload conversion and client-side validation. */
import type { ExtractionWarning, OrderDetail, OrderItem } from "../types";

export const ORDER_TEXT_FIELDS = [
  "po_number", "source_status", "source_order_date", "customer_name", "billing_address", "shipping_name",
  "shipping_address", "contact", "email", "gstin", "executive", "global_customization",
  "global_logo_reference", "global_notes",
] as const;
export const ORDER_MONEY_FIELDS = [
  "subtotal", "packaging_charges", "processing_charges", "additional_charges", "tax", "total",
] as const;
const ITEM_TEXT_FIELDS = ["sku", "product_name", "weight", "hsn", "tax", "location", "customization_text", "logo_reference", "notes"] as const;
const ITEM_NUM_FIELDS = ["quantity", "rate", "original_rate", "value", "printing_price"] as const;
/** Item fields edited (and therefore sent) by the product card. The rest stay as stored on the server. */
const SENT_ITEM_TEXT_FIELDS = ["sku", "customization_text", "logo_reference", "notes"] as const;
const SENT_ITEM_NUM_FIELDS = ["quantity", "rate", "value", "printing_price"] as const;

type OrderTextField = (typeof ORDER_TEXT_FIELDS)[number];
type OrderMoneyField = (typeof ORDER_MONEY_FIELDS)[number];
type ItemTextField = (typeof ITEM_TEXT_FIELDS)[number];
type ItemNumField = (typeof ITEM_NUM_FIELDS)[number];

export type ItemForm = { key: string; id: number | null; names: string } & Record<ItemTextField | ItemNumField, string>;
export type OrderForm = { global_names: string; items: ItemForm[] } & Record<OrderTextField | OrderMoneyField, string>;

let keySeq = 0;
const newKey = () => `row-${Date.now()}-${keySeq++}`;
const str = (v: unknown) => (v === null || v === undefined ? "" : String(v));

export function itemToForm(item: OrderItem): ItemForm {
  const form = { key: item.id ? `id-${item.id}` : newKey(), id: item.id, names: item.customization_names.join("\n") } as ItemForm;
  for (const f of ITEM_TEXT_FIELDS) form[f] = str(item[f]);
  for (const f of ITEM_NUM_FIELDS) form[f] = str(item[f]);
  return form;
}

export function blankItem(): ItemForm {
  const form = { key: newKey(), id: null, names: "" } as ItemForm;
  for (const f of [...ITEM_TEXT_FIELDS, ...ITEM_NUM_FIELDS]) form[f] = "";
  return form;
}

export function toForm(order: OrderDetail): OrderForm {
  const form = { global_names: order.global_names.join("\n"), items: order.items.map(itemToForm) } as OrderForm;
  for (const f of ORDER_TEXT_FIELDS) form[f] = str(order[f]);
  for (const f of ORDER_MONEY_FIELDS) form[f] = str(order[f]);
  return form;
}

export const splitNames = (text: string) =>
  text
    .split(/\r?\n/)
    .map((s) => s.trim())
    .filter(Boolean);

export function parseNum(text: string): number | null | "invalid" {
  const t = text.trim().replace(/,/g, "").replace(/^(₹|rs\.?)\s*/i, ""); // "₹ 15", "Rs. 15", "1,250.50"
  if (!t) return null;
  if (!/^\d+(\.\d+)?$/.test(t)) return "invalid";
  return Number(t);
}

/** Build the PUT payload. Returns field errors (keyed like "subtotal" or "items.0.quantity") if any value is invalid. */
export function toPayload(form: OrderForm, version: number): { payload: Record<string, unknown>; errors: Record<string, string> } {
  const errors: Record<string, string> = {};
  const payload: Record<string, unknown> = { version };
  for (const f of ORDER_TEXT_FIELDS) payload[f] = form[f].trim() || null;
  for (const f of ORDER_MONEY_FIELDS) {
    const n = parseNum(form[f]);
    if (n === "invalid") errors[f] = "Enter a number (e.g. 1250.50)";
    payload[f] = n === "invalid" ? null : n;
  }
  if (payload.email && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(String(payload.email))) errors.email = "Enter a valid email address";
  payload.global_names = splitNames(form.global_names);
  payload.items = form.items.map((item, idx) => {
    const res = itemToPayload(item, idx);
    Object.assign(errors, res.errors);
    return { id: item.id, ...res.payload };
  });
  return { payload, errors };
}

/** Payload for saving one product row on its own (errors keyed "items.<idx>.<field>"). */
export function itemToPayload(item: ItemForm, idx: number): { payload: Record<string, unknown>; errors: Record<string, string> } {
  const errors: Record<string, string> = {};
  const out: Record<string, unknown> = { customization_names: splitNames(item.names) };
  for (const f of SENT_ITEM_TEXT_FIELDS) out[f] = item[f].trim() || null;
  for (const f of SENT_ITEM_NUM_FIELDS) {
    const n = parseNum(item[f]);
    if (n === "invalid") errors[`items.${idx}.${f}`] = f === "quantity" ? "Whole number" : "Number";
    else if (f === "quantity" && n !== null && !Number.isInteger(n)) errors[`items.${idx}.${f}`] = "Whole number";
    out[f] = n === "invalid" ? null : n;
  }
  return { payload: out, errors };
}

export const GLOBAL_FIELDS = ["global_customization", "global_names", "global_logo_reference", "global_notes"] as const;

/** Payload for saving only the global customization section. */
export function globalToPayload(form: OrderForm): Record<string, unknown> {
  return {
    global_customization: form.global_customization.trim() || null,
    global_names: splitNames(form.global_names),
    global_logo_reference: form.global_logo_reference.trim() || null,
    global_notes: form.global_notes.trim() || null,
  };
}

const itemSnapshot = (item: ItemForm | undefined) => (item ? JSON.stringify({ ...item, key: "" }) : null);

/** True when a product row differs from its last saved state (new rows are always unsaved). */
export function isItemDirty(item: ItemForm, baseline: OrderForm): boolean {
  return item.id === null || itemSnapshot(item) !== itemSnapshot(baseline.items.find((b) => b.key === item.key));
}

export function isGlobalDirty(form: OrderForm, baseline: OrderForm): boolean {
  return GLOBAL_FIELDS.some((f) => form[f] !== baseline[f]);
}

/**
 * Put a row saved on the server into a form (current edits or the saved baseline), keeping the row key
 * so React state and other rows' unsaved edits are untouched. Rows not yet in the form are appended.
 */
export function mergeSavedItem(form: OrderForm, key: string, saved: OrderItem): OrderForm {
  const row = { ...itemToForm(saved), key };
  const exists = form.items.some((it) => it.key === key);
  return { ...form, items: exists ? form.items.map((it) => (it.key === key ? row : it)) : [...form.items, row] };
}

/**
 * Reuse the current row keys so product cards keep their UI state (e.g. open customization) when the form reloads.
 * Rows are matched by id; a row that had no id yet (added, then saved with Save draft) is matched by position,
 * because the server returns rows in the order they were sent.
 */
export function keepItemKeys(fresh: OrderForm, current: OrderForm): OrderForm {
  const keyById = new Map(current.items.filter((it) => it.id !== null).map((it) => [it.id, it.key]));
  return {
    ...fresh,
    items: fresh.items.map((it, i) => {
      const byPosition = current.items[i]?.id === null ? current.items[i].key : undefined;
      return { ...it, key: keyById.get(it.id) ?? byPosition ?? it.key };
    }),
  };
}

/** Put the saved global customization into a form, leaving every other field as it is. */
export function mergeSavedGlobal(form: OrderForm, saved: OrderDetail): OrderForm {
  const fresh = toForm(saved);
  const next = { ...form };
  for (const f of GLOBAL_FIELDS) next[f] = fresh[f];
  return next;
}

export function fieldWarnings(warnings: ExtractionWarning[]): Record<string, ExtractionWarning[]> {
  const map: Record<string, ExtractionWarning[]> = {};
  for (const w of warnings) (map[w.field] ??= []).push(w);
  return map;
}

export function itemChecks(item: ItemForm): {
  mismatch: string | null;
  names: { count: number; qty: number | null; ok: boolean };
  printingTotal: number | null;
} {
  const qty = parseNum(item.quantity);
  const printing = parseNum(item.printing_price);
  const rate = parseNum(item.rate);
  const value = parseNum(item.value);
  let mismatch: string | null = null;
  if (typeof qty === "number" && typeof rate === "number" && typeof value === "number") {
    const expected = Math.round(qty * rate * 100) / 100;
    if (Math.abs(expected - value) > Math.max(0.01, value * 0.0005)) mismatch = `Rate × Qty = ${expected.toFixed(2)}`;
  }
  const count = splitNames(item.names).length;
  const q = typeof qty === "number" ? qty : null;
  const printingTotal = typeof qty === "number" && typeof printing === "number" ? Math.round(qty * printing * 100) / 100 : null;
  return { mismatch, names: { count, qty: q, ok: count === 0 || count === q }, printingTotal };
}

export const META_LABELS: Record<string, string> = {
  source_order_date_printed: "Order date (as printed)",
  agent: "Agent / DropShipper / Reseller",
  seller: "Seller GST details",
  item_summary: "Item / Qty / Wt",
  selfship_type: "SelfShip / Type",
  wallet_balance: "Wallet balance",
  pretax_total: "PreTax total",
  order_type: "Type",
  part_type: "Part type",
  total_parts: "Total parts",
  box_status: "Status box",
  other_amounts: "Other amounts",
  detected_for_reference: "Detected in text (not applied)",
};

import { describe, expect, it } from "vitest";
import { makeItem, makeOrder } from "../test/fixtures";
import {
  blankItem,
  globalToPayload,
  isGlobalDirty,
  isItemDirty,
  itemChecks,
  itemToPayload,
  keepItemKeys,
  mergeSavedGlobal,
  mergeSavedItem,
  toForm,
} from "./orderForm";

describe("itemToPayload", () => {
  it("converts one product card into an item payload", () => {
    const item = { ...toForm(makeOrder()).items[0], quantity: "61", rate: "1,000.5", names: "Asha\n\n  Ravi  \n", notes: "  " };
    const { payload, errors } = itemToPayload(item, 0);
    expect(errors).toEqual({});
    expect(payload).toMatchObject({ sku: "SKU-11", quantity: 61, rate: 1000.5, customization_names: ["Asha", "Ravi"], notes: null });
    expect(payload).not.toHaveProperty("id");
    for (const hidden of ["product_name", "original_rate", "weight", "hsn", "tax", "location"]) expect(payload).not.toHaveProperty(hidden);
  });

  it("reports invalid numbers keyed by row index", () => {
    const item = { ...blankItem(), quantity: "1.5", rate: "abc", value: "-3" };
    const { errors } = itemToPayload(item, 2);
    expect(errors).toEqual({ "items.2.quantity": "Whole number", "items.2.rate": "Number", "items.2.value": "Number" });
  });

  it("sends the printing price and totals it per row", () => {
    const item = { ...toForm(makeOrder()).items[0], quantity: "60", printing_price: "₹ 2.5" };
    expect(itemToPayload(item, 0).payload).toMatchObject({ printing_price: 2.5 });
    expect(itemChecks(item).printingTotal).toBe(150);
    expect(itemChecks({ ...item, printing_price: "" }).printingTotal).toBeNull();
    expect(itemToPayload({ ...item, printing_price: "x" }, 1).errors).toEqual({ "items.1.printing_price": "Number" });
  });
});

describe("dirty tracking and merging", () => {
  it("tracks dirtiness per product row and for the global section", () => {
    const base = toForm(makeOrder());
    const form = { ...base, contact: "9000000001", items: base.items.map((it, i) => (i === 0 ? { ...it, quantity: "61" } : it)) };
    expect(isItemDirty(form.items[0], base)).toBe(true);
    expect(isItemDirty(form.items[1], base)).toBe(false);
    expect(isItemDirty(blankItem(), base)).toBe(true); // a new row is unsaved
    expect(isGlobalDirty(form, base)).toBe(false);
    expect(isGlobalDirty({ ...form, global_notes: "x" }, base)).toBe(true);
  });

  it("merges a saved row without touching other rows or fields", () => {
    const base = toForm(makeOrder());
    const form = { ...base, contact: "9000000001", items: base.items.map((it, i) => (i === 1 ? { ...it, notes: "unsaved" } : it)) };
    const key = form.items[0].key;
    const merged = mergeSavedItem(form, key, makeItem(11, { quantity: 61, customization_text: "DEODAP" }));
    expect(merged.items[0]).toMatchObject({ key, quantity: "61", customization_text: "DEODAP" });
    expect(merged.items[1].notes).toBe("unsaved");
    expect(merged.contact).toBe("9000000001");
  });

  it("appends a newly created row to the saved baseline", () => {
    const base = toForm(makeOrder());
    const merged = mergeSavedItem(base, "row-new", makeItem(99, { sku: "NEW" }));
    expect(merged.items.map((i) => i.key)).toEqual([base.items[0].key, base.items[1].key, "row-new"]);
    expect(merged.items[2].id).toBe(99);
  });

  it("keeps existing row keys when the form is rebuilt from the server", () => {
    const current = toForm(makeOrder());
    current.items = [current.items[0], { ...blankItem(), key: "row-local", id: 99 }];
    const fresh = toForm(makeOrder({ items: [makeItem(11), makeItem(99), makeItem(100)] }));
    expect(keepItemKeys(fresh, current).items.map((i) => i.key)).toEqual([current.items[0].key, "row-local", "id-100"]);
  });

  it("keeps the key of a new row that only got its id from Save draft", () => {
    const current = toForm(makeOrder());
    current.items = [...current.items, { ...blankItem(), key: "row-new" }];
    const fresh = toForm(makeOrder({ items: [makeItem(11), makeItem(12), makeItem(99)] }));
    expect(keepItemKeys(fresh, current).items.map((i) => i.key)).toEqual([current.items[0].key, current.items[1].key, "row-new"]);
  });

  it("merges saved global customization only", () => {
    const form = { ...toForm(makeOrder()), contact: "9000000001", global_notes: "draft" };
    const merged = mergeSavedGlobal(form, makeOrder({ global_customization: "LOGO", global_names: ["A", "B"], global_notes: "saved" }));
    expect(merged).toMatchObject({ contact: "9000000001", global_customization: "LOGO", global_names: "A\nB", global_notes: "saved" });
    expect(globalToPayload(merged)).toEqual({ global_customization: "LOGO", global_names: ["A", "B"], global_logo_reference: null, global_notes: "saved" });
  });
});

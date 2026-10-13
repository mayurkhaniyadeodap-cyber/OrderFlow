import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "../api";
import { AuthProvider } from "../auth";
import { ToastProvider } from "../components/Toast";
import { makeItem, makeOrder } from "../test/fixtures";
import type { OrderDetail } from "../types";
import { OrderEditor } from "./OrderEditor";
import { OrderPage } from "./OrderPage";

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), del: vi.fn(), upload: vi.fn(), blob: vi.fn() }));
vi.mock("../api", async (importOriginal) => ({ ...(await importOriginal<typeof import("../api")>()), api }));

function Harness({ initial }: { initial: OrderDetail }) {
  const [order, setOrder] = useState(initial);
  return <OrderEditor order={order} setOrder={setOrder} />;
}

function renderEditor(order = makeOrder()) {
  const router = createMemoryRouter([{ path: "/orders/:id", element: <Harness initial={order} /> }], { initialEntries: ["/orders/1"] });
  render(
    <AuthProvider>
      <ToastProvider>
        <RouterProvider router={router} />
      </ToastProvider>
    </AuthProvider>,
  );
}

const cards = () => document.querySelectorAll<HTMLElement>(".item-card");
const card = (i: number) => within(cards()[i]);
type User = ReturnType<typeof userEvent.setup>;
/** SKU-wise customization starts collapsed: open it for card i. */
const openCustomization = (user: User, i: number) => user.click(card(i).getByRole("button", { name: /SKU-wise customization/ }));
const globalSection = () => within(screen.getByRole("button", { name: /Save Global Changes/ }).closest(".card") as HTMLElement);
/** Server response for a row save: the saved row replaces the old one and the version increases. */
const savedResponse = (order: OrderDetail, itemId: number, patch: object) => ({
  item_id: itemId,
  order: { ...order, version: order.version + 1, items: order.items.map((i) => (i.id === itemId ? { ...i, ...patch } : i)) },
});

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  sessionStorage.clear();
});

describe("product card Save Changes", () => {
  it("saves only that product and keeps unsaved edits elsewhere", async () => {
    const user = userEvent.setup();
    const order = makeOrder();
    api.put.mockResolvedValue(savedResponse(order, 11, { quantity: 61, customization_text: "DEODAP" }));
    renderEditor(order);
    await openCustomization(user, 0);
    await openCustomization(user, 1);

    await user.type(screen.getByLabelText("Contact number"), "0"); // unrelated unsaved edit
    await user.type(card(1).getByLabelText("SKU notes (optional)"), "row 2 draft"); // another card's unsaved edit
    const qty = card(0).getByLabelText("Qty *");
    await user.clear(qty);
    await user.type(qty, "61");
    await user.type(card(0).getByLabelText("Same name / text on every unit"), "DEODAP");
    expect(card(0).getByText("Unsaved changes")).toBeInTheDocument();
    await user.click(card(0).getByRole("button", { name: /Save Changes/ }));

    expect(api.put).toHaveBeenCalledTimes(1);
    const [url, body] = api.put.mock.calls[0];
    expect(url).toBe("/api/orders/1/items/11");
    expect(body).toMatchObject({ version: 3, sku: "SKU-11", quantity: 61, customization_text: "DEODAP" });
    expect(body).not.toHaveProperty("contact");
    expect(api.post).not.toHaveBeenCalled(); // never publishes

    expect(await card(0).findByText("Saved")).toBeInTheDocument();
    expect(card(0).getByRole("button", { name: /Save Changes/ })).toBeDisabled();
    expect(screen.getByLabelText("Contact number")).toHaveValue("86191404730");
    expect(card(1).getByLabelText("SKU notes (optional)")).toHaveValue("row 2 draft");
    expect(card(1).getByText("Unsaved changes")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Save draft/ })).toBeEnabled(); // contact still unsaved
    expect(screen.getByText(/Draft #1/)).toBeInTheDocument(); // still a Draft
  });

  it("shows saved server values after the save (persisted state)", async () => {
    const user = userEvent.setup();
    const order = makeOrder();
    api.put.mockResolvedValue(savedResponse(order, 11, { customization_names: ["Asha", "Ravi"] }));
    renderEditor(order);
    await openCustomization(user, 0);
    await user.type(card(0).getByLabelText(/Individual names/), "Asha{enter}{enter}Ravi{enter}");
    await user.click(card(0).getByRole("button", { name: /Save Changes/ }));
    await waitFor(() => expect(card(0).getByLabelText(/Individual names/)).toHaveValue("Asha\nRavi"));
    expect(card(0).getByText("Saved")).toBeInTheDocument();
  });

  it("blocks invalid values without calling the server", async () => {
    const user = userEvent.setup();
    renderEditor();
    const qty = card(0).getByLabelText("Qty *");
    await user.clear(qty);
    await user.type(qty, "abc");
    await user.click(card(0).getByRole("button", { name: /Save Changes/ }));
    expect(api.put).not.toHaveBeenCalled();
    expect(card(0).getByText("Correct the highlighted values in this product.")).toBeInTheDocument();
    expect(card(0).getByText("Whole number")).toBeInTheDocument();
    expect(qty).toHaveValue("abc");
  });

  it("keeps edits and shows the error when the save fails", async () => {
    const user = userEvent.setup();
    api.put.mockRejectedValue(new ApiError(422, "Please correct the highlighted values.", { errors: ["row 1 → sku: too long"] }));
    renderEditor();
    const sku = card(0).getByLabelText("SKU / code *");
    await user.type(sku, "-X");
    await user.click(card(0).getByRole("button", { name: /Save Changes/ }));
    expect(await card(0).findByText("Please correct the highlighted values.")).toBeInTheDocument();
    expect(card(0).getByText("row 1 → sku: too long")).toBeInTheDocument();
    expect(sku).toHaveValue("SKU-11-X");
    expect(card(0).getByRole("button", { name: /Save Changes/ })).toBeEnabled(); // can retry
  });

  it("shows the lock message if the order was published meanwhile", async () => {
    const user = userEvent.setup();
    api.put.mockRejectedValue(new ApiError(409, "Order OF-2026-00001 is Live and locked. Only comments can be added.", { code: "order_locked" }));
    renderEditor();
    await user.type(card(0).getByLabelText("SKU / code *"), "Z");
    await user.click(card(0).getByRole("button", { name: /Save Changes/ }));
    expect(await card(0).findByText(/is Live and locked/)).toBeInTheDocument();
    expect(card(0).getByLabelText("SKU / code *")).toHaveValue("SKU-11Z");
  });

  it("creates a new product row and then allows logo upload", async () => {
    const user = userEvent.setup();
    const order = makeOrder();
    api.post.mockResolvedValue({ item_id: 99, order: { ...order, version: 4, items: [...order.items, makeItem(99, { sku: "NEW-1", quantity: 2 })] } });
    renderEditor(order);
    await user.click(screen.getByRole("button", { name: /Add product row/ }));
    await openCustomization(user, 2);
    expect(card(2).getByRole("button", { name: /Upload logo/ })).toBeDisabled();
    await user.type(card(2).getByLabelText("SKU / code *"), "NEW-1");
    await user.type(card(2).getByLabelText("Qty *"), "2");
    await user.click(card(2).getByRole("button", { name: /Save Changes/ }));
    expect(api.post).toHaveBeenCalledWith("/api/orders/1/items", expect.objectContaining({ sku: "NEW-1", quantity: 2, version: 3 }));
    expect(await card(2).findByText("Saved")).toBeInTheDocument();
    expect(card(2).getByRole("button", { name: /Upload logo/ })).toBeEnabled();
  });
});

describe("Save Global Changes", () => {
  it("saves global customization only and keeps product edits", async () => {
    const user = userEvent.setup();
    const order = makeOrder();
    api.put.mockResolvedValue({ ...order, version: 4, global_customization: "KHODIYAR", global_names: ["Asha"], global_notes: "Front" });
    renderEditor(order);
    await openCustomization(user, 0);
    await user.type(card(0).getByLabelText("SKU notes (optional)"), "keep me");
    await user.type(screen.getByLabelText("Name / text for the whole order"), "KHODIYAR");
    await user.type(screen.getByLabelText("Global names (one per line)"), "Asha");
    await user.type(screen.getByLabelText("Global notes (optional)"), "Front");
    await user.click(screen.getByRole("button", { name: /Save Global Changes/ }));

    expect(api.put).toHaveBeenCalledWith("/api/orders/1/global", {
      version: 3, global_customization: "KHODIYAR", global_names: ["Asha"], global_logo_reference: null, global_notes: "Front",
    });
    expect(await globalSection().findByText("Saved")).toBeInTheDocument();
    expect(card(0).getByLabelText("SKU notes (optional)")).toHaveValue("keep me");
    expect(card(0).getByText("Unsaved changes")).toBeInTheDocument();
  });

  it("keeps global edits when the save fails", async () => {
    const user = userEvent.setup();
    api.put.mockRejectedValue(new ApiError(409, "This order was changed by someone else since you opened it.", { code: "version_conflict" }));
    renderEditor();
    await user.type(screen.getByLabelText("Global notes (optional)"), "Rush");
    await user.click(screen.getByRole("button", { name: /Save Global Changes/ }));
    expect(await globalSection().findByText(/changed by someone else/)).toBeInTheDocument();
    expect(screen.getByLabelText("Global notes (optional)")).toHaveValue("Rush");
    expect(globalSection().getByText("Unsaved changes")).toBeInTheDocument();
  });
});

describe("Save draft", () => {
  it("saves the same order repeatedly with the latest values", async () => {
    const user = userEvent.setup();
    const order = makeOrder();
    api.put.mockImplementation(async (_url: string, body: Record<string, unknown>) => ({
      ...order, version: (body.version as number) + 1, customer_name: body.customer_name, contact: body.contact,
    }));
    renderEditor(order);
    const saveDraft = () => screen.getByRole("button", { name: /Save draft/ });
    const name = screen.getByLabelText(/^Customer name/);

    await user.clear(name);
    await user.type(name, "First Name");
    await user.click(saveDraft());
    await waitFor(() => expect(saveDraft()).toBeDisabled()); // saved: nothing left to save

    await user.clear(name);
    await user.type(name, "Second Name");
    await user.type(screen.getByLabelText("Contact number"), "0");
    expect(saveDraft()).toBeEnabled();
    await user.click(saveDraft());

    expect(api.put).toHaveBeenCalledTimes(2);
    expect(api.put.mock.calls[0][1]).toMatchObject({ version: 3, customer_name: "First Name" });
    expect(api.put.mock.calls[1][1]).toMatchObject({ version: 4, customer_name: "Second Name", contact: "86191404730" });
    await waitFor(() => expect(saveDraft()).toBeDisabled());
    expect(name).toHaveValue("Second Name");
  });

  it("makes a failed save impossible to miss and keeps the edits", async () => {
    const user = userEvent.setup();
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    api.put.mockRejectedValue(new ApiError(409, "This order was changed by someone else since you opened it.", { code: "version_conflict" }));
    renderEditor();
    await openCustomization(user, 1);
    await user.type(card(1).getByLabelText("SKU notes (optional)"), "keep me");
    await user.click(screen.getByRole("button", { name: /Save draft/ }));
    expect(await screen.findByText(/Draft NOT saved: This order was changed/)).toBeInTheDocument(); // toast
    await waitFor(() => expect(scroll).toHaveBeenCalled()); // error brought into view
    expect(card(1).getByLabelText("SKU notes (optional)")).toHaveValue("keep me");
    expect(screen.getByRole("button", { name: /Save draft/ })).toBeEnabled(); // can retry
  });

  it("focuses the invalid field instead of silently not saving", async () => {
    const user = userEvent.setup();
    Element.prototype.scrollIntoView = vi.fn();
    renderEditor();
    const rate = card(1).getByLabelText("Rate");
    await user.clear(rate);
    await user.type(rate, "abc");
    await user.click(screen.getByRole("button", { name: /Save draft/ }));
    expect(api.put).not.toHaveBeenCalled();
    expect(await screen.findByText(/Draft NOT saved: Please correct/)).toBeInTheDocument();
    await waitFor(() => expect(rate).toHaveFocus());
  });

  it("accepts rupee amounts typed with a space", async () => {
    const user = userEvent.setup();
    const order = makeOrder();
    api.put.mockResolvedValue({ ...order, version: 4 });
    renderEditor(order);
    const rate = card(1).getByLabelText("Rate");
    await user.clear(rate);
    await user.type(rate, "₹ 15");
    await user.click(screen.getByRole("button", { name: /Save draft/ }));
    expect((api.put.mock.calls[0][1] as { items: { rate: number }[] }).items[1].rate).toBe(15);
  });
});

describe("product card layout", () => {
  it("shows only SKU, Qty, Rate and Line value as product fields", () => {
    renderEditor();
    for (const label of ["SKU / code *", "Qty *", "Rate", "Line value"]) expect(card(0).getByLabelText(label)).toBeInTheDocument();
    for (const label of ["Product name", "MRP (struck)", "Weight", "HSN/SAC", "Tax / GST", "Location / bin"]) {
      expect(card(0).queryByLabelText(label)).not.toBeInTheDocument();
    }
  });

  it("does not send hidden fields on Save Changes (server keeps them as stored)", async () => {
    const user = userEvent.setup();
    const order = makeOrder();
    api.put.mockResolvedValue({ item_id: 11, order: { ...order, version: 4 } });
    renderEditor(order);
    const qty = card(0).getByLabelText("Qty *");
    await user.clear(qty);
    await user.type(qty, "61");
    await user.click(card(0).getByRole("button", { name: /Save Changes/ }));
    const body = api.put.mock.calls[0][1] as Record<string, unknown>;
    expect(body).toMatchObject({ quantity: 61, sku: "SKU-11", rate: 87.2, value: 5232 });
    for (const hidden of ["product_name", "original_rate", "weight", "hsn", "tax", "location"]) expect(body).not.toHaveProperty(hidden);
  });

  it("does not send hidden fields on Save draft, even over-long stored ones", async () => {
    const user = userEvent.setup();
    const order = makeOrder({ items: [makeItem(11, { original_rate: 99.5, product_name: "P".repeat(400), tax: "x".repeat(50) }), makeItem(12)] });
    api.put.mockResolvedValue({ ...order, version: 4 });
    renderEditor(order);
    await user.type(screen.getByLabelText("Contact number"), "0");
    await user.click(screen.getByRole("button", { name: /Save draft/ }));
    const items = (api.put.mock.calls[0][1] as { items: Record<string, unknown>[] }).items;
    expect(items[0]).toMatchObject({ id: 11, sku: "SKU-11", quantity: 60 });
    for (const hidden of ["product_name", "original_rate", "weight", "hsn", "tax", "location"]) expect(items[0]).not.toHaveProperty(hidden);
  });

  it("starts SKU-wise customization collapsed and toggles each product independently", async () => {
    const user = userEvent.setup();
    renderEditor();
    const toggle = (i: number) => card(i).getByRole("button", { name: /SKU-wise customization/ });
    for (const i of [0, 1]) {
      expect(toggle(i)).toHaveAttribute("aria-expanded", "false");
      expect(card(i).queryByLabelText("SKU notes (optional)")).not.toBeInTheDocument();
    }
    await user.click(toggle(0));
    expect(toggle(0)).toHaveAttribute("aria-expanded", "true");
    expect(card(0).getByLabelText("SKU notes (optional)")).toBeInTheDocument();
    expect(card(1).queryByLabelText("SKU notes (optional)")).not.toBeInTheDocument(); // other product stays closed
    await user.click(toggle(1));
    expect(card(1).getByLabelText(/Individual names/)).toBeInTheDocument();
    await user.click(toggle(0));
    expect(toggle(0)).toHaveAttribute("aria-expanded", "false");
    expect(card(0).queryByLabelText("SKU notes (optional)")).not.toBeInTheDocument();
    expect(card(1).getByLabelText("SKU notes (optional)")).toBeInTheDocument(); // still open
  });

  it("keeps a new product's customization open after Save draft", async () => {
    const user = userEvent.setup();
    const order = makeOrder();
    api.put.mockResolvedValue({ ...order, version: 4, items: [...order.items, makeItem(99, { sku: "NEW-1", quantity: 2 })] });
    renderEditor(order);
    await user.click(screen.getByRole("button", { name: /Add product row/ }));
    await user.type(card(2).getByLabelText("SKU / code *"), "NEW-1");
    await user.type(card(2).getByLabelText("Qty *"), "2");
    await openCustomization(user, 2);
    await user.click(screen.getByRole("button", { name: /Save draft/ }));
    await waitFor(() => expect(screen.getByRole("button", { name: /Save draft/ })).toBeDisabled()); // saved and reloaded
    expect(card(2).getByRole("button", { name: /SKU-wise customization/ })).toHaveAttribute("aria-expanded", "true");
    expect(card(2).getByRole("button", { name: /Upload logo/ })).toBeEnabled(); // row now exists on the server
    expect(card(0).getByRole("button", { name: /SKU-wise customization/ })).toHaveAttribute("aria-expanded", "false");
  });

  it("keeps typed customization when the section is closed and reopened, and saves it", async () => {
    const user = userEvent.setup();
    const order = makeOrder();
    api.put.mockResolvedValue(savedResponse(order, 11, { customization_text: "DEODAP" }));
    renderEditor(order);
    await openCustomization(user, 0);
    await user.type(card(0).getByLabelText("Same name / text on every unit"), "DEODAP");
    await openCustomization(user, 0); // close
    expect(card(0).getByText("Unsaved changes")).toBeInTheDocument();
    await user.click(card(0).getByRole("button", { name: /Save Changes/ }));
    expect(api.put.mock.calls[0][1]).toMatchObject({ customization_text: "DEODAP" });
    await openCustomization(user, 0);
    expect(card(0).getByLabelText("Same name / text on every unit")).toHaveValue("DEODAP");
  });
});

describe("Executive / sales contact", () => {
  it("offers saved contacts and still accepts a new name", async () => {
    const user = userEvent.setup();
    const order = makeOrder();
    api.get.mockImplementation(async (url: string) => (url === "/api/contacts" ? { items: ["Dhruv Bhojani", "Rina Gohel-JD"] } : undefined));
    api.put.mockResolvedValue({ ...order, version: 4, executive: "Priya Shah" });
    renderEditor(order);
    const field = screen.getByLabelText("Executive / sales contact");
    const list = document.getElementById(field.getAttribute("list") ?? "");
    await waitFor(() => expect([...(list?.querySelectorAll("option") ?? [])].map((o) => o.value)).toEqual(["Dhruv Bhojani", "Rina Gohel-JD"]));
    await user.type(field, "Priya Shah"); // not in the list: allowed
    await user.click(screen.getByRole("button", { name: /Save draft/ }));
    expect(api.put.mock.calls[0][1]).toMatchObject({ executive: "Priya Shah" });
  });
});

describe("removed sections", () => {
  it("has no Shipping & courier or Amounts card in the draft editor", () => {
    renderEditor();
    expect(screen.queryByText("Shipping & courier")).not.toBeInTheDocument();
    expect(screen.queryByText("Amounts")).not.toBeInTheDocument();
    for (const label of [/^Courier/, /^Shipping address/, "Ship-to name", "Subtotal", "Packaging charges", "Total"]) {
      expect(screen.queryByLabelText(label)).not.toBeInTheDocument();
    }
    expect(screen.getByLabelText(/^Customer name/)).toBeInTheDocument(); // Customer & PO is still there
  });
});

describe("Delete and Admin Live editing", () => {
  it("deletes (archives) a draft after confirmation", async () => {
    const user = userEvent.setup();
    const order = makeOrder();
    api.post.mockResolvedValue({ ...order, is_archived: true });
    renderEditor(order);
    await user.click(screen.getByRole("button", { name: /Delete order/ }));
    const dialog = within(screen.getByRole("dialog", { name: "Delete Draft #1?" }));
    expect(dialog.getByText(/an Admin can restore it/)).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled(); // nothing happens without confirming
    await user.click(dialog.getByRole("button", { name: /Delete order/ }));
    expect(api.post).toHaveBeenCalledWith("/api/orders/1/archive", { version: 3 });
  });

  it("has no Delete button when the server does not allow it", () => {
    renderEditor(makeOrder({ permissions: { ...makeOrder().permissions, can_delete: false } }));
    expect(screen.queryByRole("button", { name: /Delete order/ })).not.toBeInTheDocument();
  });

  it("lets an Admin edit a Live order without publishing again", async () => {
    const user = userEvent.setup();
    const live = makeOrder({ status: "Live", internal_order_no: "OF-2026-00007", printing_status: "Processing", global_customization: "Logo",
      permissions: { can_edit: true, can_publish: false, can_comment: true, next_printing_statuses: [], can_upload_photos: false, can_delete: true, can_restore: false } });
    api.put.mockResolvedValue({ ...live, version: 4, customer_name: "Fixed Name" });
    renderEditor(live);
    expect(screen.getByText("You are editing a Live order")).toBeInTheDocument();
    expect(screen.getByText("OF-2026-00007", { exact: false })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Publish Live/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Re-extract/ })).not.toBeInTheDocument();
    const name = screen.getByLabelText(/^Customer name/);
    await user.clear(name);
    await user.type(name, "Fixed Name");
    await user.click(screen.getByRole("button", { name: /Save order/ }));
    expect(api.put).toHaveBeenCalledWith("/api/orders/1", expect.objectContaining({ version: 3, customer_name: "Fixed Name" }));
  });
});

describe("published orders", () => {
  it("show the read-only view without any save buttons", async () => {
    api.get.mockResolvedValue(makeOrder({
      status: "Live", internal_order_no: "OF-2026-00001", printing_status: "New", live_at: "2026-10-12T07:30:00+00:00",
      global_customization: "Logo",
      permissions: { can_edit: false, can_publish: false, can_comment: true, next_printing_statuses: [], can_upload_photos: false, can_delete: false, can_restore: false },
    }));
    const router = createMemoryRouter([{ path: "/orders/:id", element: <OrderPage /> }], { initialEntries: ["/orders/1"] });
    render(<AuthProvider><ToastProvider><RouterProvider router={router} /></ToastProvider></AuthProvider>);
    expect(await screen.findByText("Details locked")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Save Changes/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Save Global Changes/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Save draft/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: /Qty/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Delete order/ })).not.toBeInTheDocument(); // can_delete false
  });

  it("lets Sales delete a Live order that Printing has not started", async () => {
    const user = userEvent.setup();
    const live = makeOrder({ status: "Live", internal_order_no: "OF-2026-00001", printing_status: "New", live_at: "2026-10-12T07:30:00+00:00",
      global_customization: "Logo",
      permissions: { can_edit: false, can_publish: false, can_comment: true, next_printing_statuses: [], can_upload_photos: false, can_delete: true, can_restore: false } });
    api.get.mockResolvedValue(live);
    api.post.mockResolvedValue({ ...live, is_archived: true, permissions: { ...live.permissions, can_delete: false } });
    const router = createMemoryRouter([{ path: "/orders/:id", element: <OrderPage /> }], { initialEntries: ["/orders/1"] });
    render(<AuthProvider><ToastProvider><RouterProvider router={router} /></ToastProvider></AuthProvider>);
    await user.click(await screen.findByRole("button", { name: /Delete order/ }));
    const dialog = within(screen.getByRole("dialog"));
    expect(dialog.getByText("This order is Live")).toBeInTheDocument();
    await user.click(dialog.getByRole("button", { name: /Delete order/ }));
    expect(api.post).toHaveBeenCalledWith("/api/orders/1/archive", { version: 3 });
    expect(await screen.findByText("This order is deleted (archived)")).toBeInTheDocument();
  });
});

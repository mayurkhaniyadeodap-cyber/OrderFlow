import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { routes } from "../../App";
import { makeItem, makeOrder } from "../../test/fixtures";
import type { AdminUser, Role } from "../../types";
import { normalizeUsername, passwordProblem } from "./AdminUsers";

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn(), upload: vi.fn(), blob: vi.fn() }));
vi.mock("../../api", async (importOriginal) => ({ ...(await importOriginal<typeof import("../../api")>()), api }));

const USERS: AdminUser[] = [
  { id: 1, username: "admin", full_name: "Administrator", role: "admin", is_active: true, created_at: "2026-10-12T07:00:00Z", updated_at: null, last_login_at: "2026-10-12T08:00:00Z" },
  { id: 2, username: "sales", full_name: "Demo Sales User", role: "sales", is_active: true, created_at: "2026-10-12T07:00:00Z", updated_at: null, last_login_at: null },
];
const DASHBOARD = {
  orders: { total: 5, draft: 2, live: 3, archived: 1, new: 1, processing: 1, print_done: 1 },
  users: { admin: { active: 1, inactive: 0 }, sales: { active: 1, inactive: 0 }, printing: { active: 1, inactive: 1 } },
  trend: Array.from({ length: 14 }, (_, i) => ({ date: `2026-10-${String(i + 1).padStart(2, "0")}`, created: i % 3, published: i % 2 })),
  oldest_open: [],
  recent_activity: [{ id: "o1", source: "order", created_at: "2026-10-12T08:00:00Z", actor: "sales", actor_role: "sales", action: "published",
    label: "Published Live", details: "Published as OF-2026-00001", order_id: 7, target: "OF-2026-00001", order_customer: "Kalpit", order_po: "135" }],
};

const CONTACTS = [
  { id: 1, name: "Dhruv Bhojani - Izzat (6358956693)", mobile: "6358956693", source: "backfill", created_by: "system", created_at: "2026-10-12T12:00:00Z", updated_at: null, orders: 4 },
  { id: 2, name: "Rina Gohel-JD (9724696662)", mobile: null, source: "extracted", created_by: "sales", created_at: "2026-10-12T12:00:00Z", updated_at: null, orders: 1 },
];

const CONTACT_ORDERS = {
  contact: CONTACTS[0],
  total: 2,
  items: [
    { ...makeOrder({ id: 8, customer_name: "RUDRA KRIPA TRADING LLP", po_number: "135-51838365" }), source_order_date: "2026-10-12T15:10", executive: "Dhruv Bhojani - Izzat (6358956693)" },
    { ...makeOrder({ id: 1, internal_order_no: "OF-2026-00001", status: "Live", printing_status: "Print Done" }), source_order_date: "2026-10-08T18:13", executive: "dhruv bhojani - izzat (6358956693)" },
  ],
};

const SETTINGS = {
  editable: { max_upload_mb: 15, token_expire_minutes: 480 },
  read_only: { timezone: "Asia/Kolkata", order_number_prefix: "OF", secret_key_configured: true },
};

function signIn(role: Role, id = role === "admin" ? 1 : 2) {
  sessionStorage.setItem("orderflow.token", "test-token");
  api.get.mockImplementation(async (url: string) => {
    if (url === "/api/me") return { user: { id, username: role, full_name: null, role }, config: { max_upload_mb: 15, timezone: "Asia/Kolkata" } };
    if (url === "/api/admin/dashboard") return DASHBOARD;
    if (url === "/api/admin/users") return { items: USERS };
    if (url.startsWith("/api/orders/")) return makeOrder({ status: "Draft", permissions: { can_edit: false, can_publish: false, can_comment: false, next_printing_statuses: [], can_upload_photos: false, can_review_photos: false, can_delete: false, can_restore: false } });
    if (url === "/api/admin/settings") return SETTINGS;
    if (url === "/api/admin/contacts") return { items: CONTACTS };
    if (url === "/api/admin/contacts/1/orders") return CONTACT_ORDERS;
    if (url === "/api/admin/contacts/2/orders") return { contact: CONTACTS[1], total: 0, items: [] };
    if (url.startsWith("/api/admin/photo-reviews")) return PHOTO_REVIEWS;
    if (url === "/api/admin/backups") return { items: [{ name: "orderflow_backup_20261012_173654.zip", size_bytes: 1624220, created_at: "2026-10-12T17:36:54+05:30" }] };
    if (url === "/api/dashboard") return { role, counts: { total: 0, live: 0, awaiting_printing: 0, processing: 0, print_done: 0, draft: 0 }, recent: [] };
    throw new Error(`unexpected GET ${url}`);
  });
}

const PHOTO_ROW = {
  order_id: 1, internal_order_no: "OF-2026-00001", po_number: "135", customer_name: "Kalpit Pandya - Frn", executive: "Dhruv Bhojani",
  sales_user: "sales", printing_status: "Processing", live_at: "2026-10-12T10:00:00Z", position: 0, quantity: 60, photo_count: 1, last_photo_at: "2026-10-12T11:00:00Z",
};
const PHOTO_REVIEWS = {
  counts: { Pending: 0, Confirmed: 1, Rejected: 1, Missing: 0 },
  total: 2,
  items: [
    { ...PHOTO_ROW, item_id: 11, sku: "SKU-11", photo_status: "Confirmed", photo_reviewed_by: "sales", photo_reviewed_at: "2026-10-12T12:00:00Z", photo_review_note: null },
    { ...PHOTO_ROW, item_id: 12, sku: "SKU-12", position: 1, photo_status: "Rejected", photo_reviewed_by: "sales", photo_reviewed_at: "2026-10-12T12:05:00Z", photo_review_note: "Logo blurred" },
  ],
};

function renderAt(path: string) {
  render(<RouterProvider router={createMemoryRouter(routes, { initialEntries: [path] })} />);
}

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  sessionStorage.clear();
});

describe("Admin navigation and access", () => {
  it("shows the Admin panel navigation and dashboard to Admins only", async () => {
    signIn("admin");
    renderAt("/");
    expect(await screen.findByRole("heading", { name: "Admin Dashboard" })).toBeInTheDocument();
    const nav = within(screen.getByRole("navigation", { name: "Main" }));
    for (const link of ["Admin Dashboard", "All Orders", "Users", "Executive Contacts", "Activity Log", "Settings & Backup"]) expect(nav.getByRole("link", { name: link })).toBeInTheDocument();
    expect(nav.getByRole("link", { name: "Upload PO" })).toBeInTheDocument(); // Admin can do everything Sales can
    expect(nav.queryByRole("link", { name: /Courier/ })).not.toBeInTheDocument(); // courier exports removed
    expect(nav.queryByRole("link", { name: "Printing Queue" })).not.toBeInTheDocument();
    expect(screen.getByText("Admin Panel")).toBeInTheDocument();
    expect(await screen.findByText("Published as OF-2026-00001")).toBeInTheDocument(); // recent activity loaded from the API
  });

  it.each(["sales", "printing"] as const)("blocks %s users from Admin pages (and does not call Admin APIs)", async (role) => {
    signIn(role);
    renderAt("/admin/users");
    expect(await screen.findByText("Not available in your panel")).toBeInTheDocument();
    expect(api.get).not.toHaveBeenCalledWith("/api/admin/users");
    expect(within(screen.getByRole("navigation", { name: "Main" })).queryByRole("link", { name: "Users" })).not.toBeInTheDocument();
  });

  it("shows a deleted order with Restore for Admins", async () => {
    const user = userEvent.setup();
    signIn("admin");
    const deleted = makeOrder({ status: "Live", internal_order_no: "OF-2026-00001", printing_status: "New", is_archived: true,
      permissions: { can_edit: false, can_publish: false, can_comment: true, next_printing_statuses: [], can_upload_photos: false, can_review_photos: false, can_delete: false, can_restore: true } });
    api.get.mockImplementation(async (url: string) => (url === "/api/me"
      ? { user: { id: 1, username: "admin", full_name: null, role: "admin" }, config: { max_upload_mb: 15, timezone: "Asia/Kolkata" } }
      : deleted));
    api.post.mockResolvedValue({ ...deleted, is_archived: false, permissions: { ...deleted.permissions, can_restore: false, can_delete: true } });
    renderAt("/orders/1");
    expect(await screen.findByText("This order is deleted (archived)")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Restore order/ }));
    expect(api.post).toHaveBeenCalledWith("/api/orders/1/restore", { version: 3 });
    expect(await screen.findByRole("button", { name: /Delete order/ })).toBeInTheDocument();
  });
});

describe("User management", () => {
  it("validates and creates a user", async () => {
    const user = userEvent.setup();
    signIn("admin");
    api.post.mockResolvedValue(USERS[1]);
    renderAt("/admin/users");
    await user.click(await screen.findByRole("button", { name: /New user/ }));
    const dialog = within(screen.getByRole("dialog", { name: "New user" }));
    await user.type(dialog.getByLabelText("Username"), "Priya.S");
    await user.selectOptions(dialog.getByLabelText("Role"), "printing");
    await user.type(dialog.getByLabelText("Password"), "onlyletters");
    await user.type(dialog.getByLabelText("Repeat password"), "onlyletters");
    await user.click(dialog.getByRole("button", { name: "Create user" }));
    expect(dialog.getByText("Password must mix letters with numbers or symbols.")).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();

    await user.clear(dialog.getByLabelText("Password"));
    await user.type(dialog.getByLabelText("Password"), "Priya-Pass-1");
    await user.clear(dialog.getByLabelText("Repeat password"));
    await user.type(dialog.getByLabelText("Repeat password"), "Priya-Pass-1");
    await user.click(dialog.getByRole("button", { name: "Create user" }));
    expect(api.post).toHaveBeenCalledWith("/api/admin/users", { username: "priya.s", full_name: null, role: "printing", password: "Priya-Pass-1" });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("accepts a username with spaces and still rejects invalid characters", async () => {
    const user = userEvent.setup();
    signIn("admin");
    api.post.mockResolvedValue({ ...USERS[1], id: 5, username: "dhruv bhojani" });
    renderAt("/admin/users");
    await user.click(await screen.findByRole("button", { name: /New user/ }));
    const dialog = within(screen.getByRole("dialog", { name: "New user" }));
    await user.type(dialog.getByLabelText("Username"), "Dhruv/Bhojani");
    await user.type(dialog.getByLabelText("Password"), "Dhruv-Pass-1");
    await user.type(dialog.getByLabelText("Repeat password"), "Dhruv-Pass-1");
    await user.click(dialog.getByRole("button", { name: "Create user" }));
    expect(dialog.getByText(/Username: 3-32 characters/)).toBeInTheDocument();
    expect(api.post).not.toHaveBeenCalled();

    await user.clear(dialog.getByLabelText("Username"));
    await user.type(dialog.getByLabelText("Username"), "  Dhruv  Bhojani ");
    await user.click(dialog.getByRole("button", { name: "Create user" }));
    expect(api.post).toHaveBeenCalledWith("/api/admin/users", { username: "dhruv bhojani", full_name: null, role: "sales", password: "Dhruv-Pass-1" });
    expect(normalizeUsername("Dhruv Bhojani")).toBe("dhruv bhojani");
  });

  it("shows and hides each new-user password independently, by mouse and keyboard", async () => {
    const user = userEvent.setup();
    signIn("admin");
    renderAt("/admin/users");
    await user.click(await screen.findByRole("button", { name: /New user/ }));
    const dialog = within(screen.getByRole("dialog", { name: "New user" }));
    const password = dialog.getByLabelText("Password");
    const repeat = dialog.getByLabelText("Repeat password");
    await user.type(password, "Priya-Pass-1");
    await user.type(repeat, "Priya-Pass-1");
    expect(password).toHaveAttribute("type", "password"); // hidden by default
    expect(repeat).toHaveAttribute("type", "password");
    const [showPassword, showRepeat] = dialog.getAllByRole("button", { name: "Show password" });

    await user.click(showPassword);
    expect(password).toHaveAttribute("type", "text");
    expect(repeat).toHaveAttribute("type", "password"); // independent
    expect(showPassword).toHaveAccessibleName("Hide password");
    expect(showPassword).toHaveAttribute("aria-pressed", "true");
    await user.click(showPassword);
    expect(password).toHaveAttribute("type", "password");

    await user.click(repeat);
    await user.tab(); // the eye button is reachable with the keyboard
    expect(showRepeat).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(repeat).toHaveAttribute("type", "text");
    await user.keyboard(" ");
    expect(repeat).toHaveAttribute("type", "password");

    expect(password).toHaveValue("Priya-Pass-1"); // values kept; toggling never submits the form
    expect(repeat).toHaveValue("Priya-Pass-1");
    expect(api.post).not.toHaveBeenCalled();
  });

  it("cannot deactivate yourself; deactivating someone else asks first", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    signIn("admin");
    api.patch.mockResolvedValue({ ...USERS[1], is_active: false });
    renderAt("/admin/users");
    expect(await screen.findByRole("button", { name: "Deactivate admin" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Deactivate sales" }));
    expect(window.confirm).toHaveBeenCalled();
    expect(api.patch).toHaveBeenCalledWith("/api/admin/users/2", { is_active: false });
  });

  it("resets a password", async () => {
    const user = userEvent.setup();
    signIn("admin");
    api.post.mockResolvedValue(USERS[1]);
    renderAt("/admin/users");
    await user.click(await screen.findByRole("button", { name: "Reset password for sales" }));
    const dialog = within(screen.getByRole("dialog"));
    await user.type(dialog.getByLabelText("Password"), "New-Pass-2026");
    await user.type(dialog.getByLabelText("Repeat password"), "New-Pass-2027");
    await user.click(dialog.getByRole("button", { name: "Reset password" }));
    expect(dialog.getByText("Passwords do not match.")).toBeInTheDocument();
    await user.clear(dialog.getByLabelText("Repeat password"));
    await user.type(dialog.getByLabelText("Repeat password"), "New-Pass-2026");
    await user.click(dialog.getByRole("button", { name: "Reset password" }));
    expect(api.post).toHaveBeenCalledWith("/api/admin/users/2/reset-password", { new_password: "New-Pass-2026" });
  });

  it("does not offer a role change for your own account", async () => {
    const user = userEvent.setup();
    signIn("admin");
    renderAt("/admin/users");
    await user.click(await screen.findByRole("button", { name: "Edit admin" }));
    expect(within(screen.getByRole("dialog")).getByLabelText("Role")).toBeDisabled();
  });
});

describe("Executive Contacts", () => {
  it("lists, adds, edits and deletes contacts", async () => {
    const user = userEvent.setup();
    vi.spyOn(window, "confirm").mockReturnValue(true);
    signIn("admin");
    api.post.mockResolvedValue({ ...CONTACTS[0], id: 3, name: "Priya Shah", source: "admin", orders: 0 });
    api.patch.mockResolvedValue({ ...CONTACTS[1], name: "Rina Gohel" });
    api.del.mockResolvedValue({ ok: true });
    renderAt("/admin/contacts");
    expect(await screen.findByText("Dhruv Bhojani - Izzat (6358956693)")).toBeInTheDocument();
    expect(screen.getByText("From existing orders")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "6358956693" })).toHaveAttribute("href", "tel:6358956693");

    await user.type(screen.getByLabelText("Name"), "  Priya Shah ");
    await user.click(screen.getByRole("button", { name: /Add contact/ }));
    expect(api.post).toHaveBeenCalledWith("/api/admin/contacts", { name: "  Priya Shah " }); // server trims + de-duplicates

    await user.click(screen.getByRole("button", { name: "Edit Rina Gohel-JD (9724696662)" }));
    const dialog = within(screen.getByRole("dialog"));
    expect(dialog.getByText(/keep it unchanged/)).toBeInTheDocument();
    await user.clear(dialog.getByLabelText("Name"));
    await user.type(dialog.getByLabelText("Name"), "Rina Gohel");
    await user.type(dialog.getByLabelText("Mobile"), "97246 96662");
    await user.click(dialog.getByRole("button", { name: "Save" }));
    expect(api.patch).toHaveBeenCalledWith("/api/admin/contacts/2", { name: "Rina Gohel", mobile: "97246 96662" });

    await user.click(screen.getByRole("button", { name: "Delete Dhruv Bhojani - Izzat (6358956693)" }));
    expect(window.confirm).toHaveBeenCalledWith(expect.stringContaining("those orders keep the name"));
    expect(api.del).toHaveBeenCalledWith("/api/admin/contacts/1");
  });

  it("opens a contact's linked orders and goes back", async () => {
    const user = userEvent.setup();
    signIn("admin");
    renderAt("/admin/contacts");
    await user.click(await screen.findByRole("link", { name: "Dhruv Bhojani - Izzat (6358956693)" }));
    expect(await screen.findByRole("heading", { name: "Dhruv Bhojani - Izzat (6358956693)" })).toBeInTheDocument();
    expect(screen.getByText(/2 linked orders/)).toBeInTheDocument();
    const rows = screen.getAllByRole("row").slice(1);
    expect(rows).toHaveLength(2);
    expect(within(rows[0]).getByText("RUDRA KRIPA TRADING LLP")).toBeInTheDocument();
    expect(within(rows[0]).getByText("135-51838365")).toBeInTheDocument();
    expect(within(rows[1]).getByRole("link", { name: "OF-2026-00001" })).toHaveAttribute("href", "/orders/1");
    expect(within(rows[0]).getByRole("link", { name: "Draft #8" })).toHaveAttribute("href", "/orders/8");
    expect(within(rows[1]).getByText("Print Done")).toBeInTheDocument();
    await user.click(screen.getByRole("link", { name: /Back to Executive Contacts/ }));
    expect(await screen.findByRole("heading", { name: "Executive Contacts" })).toBeInTheDocument();
  });

  it("shows a helpful message for a contact without orders", async () => {
    signIn("admin");
    renderAt("/admin/contacts/2");
    expect(await screen.findByText("No orders for this contact yet")).toBeInTheDocument();
    expect(screen.getByText(/0 linked orders/)).toBeInTheDocument();
  });

  it("is not available to Sales", async () => {
    signIn("sales");
    renderAt("/admin/contacts");
    expect(await screen.findByText("Not available in your panel")).toBeInTheDocument();
    expect(api.get).not.toHaveBeenCalledWith("/api/admin/contacts");
  });
});

describe("Courier exports removed", () => {
  it.each(["sales", "admin", "printing"] as const)("%s has no Courier Exports link or page", async (role) => {
    signIn(role);
    renderAt("/exports");
    expect(await screen.findByText("Page not found")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Courier/ })).not.toBeInTheDocument();
  });
});

describe("Settings & Backup", () => {
  it("has no courier settings and saves upload size and session length", async () => {
    const user = userEvent.setup();
    signIn("admin");
    api.put.mockResolvedValue(SETTINGS);
    renderAt("/admin/settings");
    expect(await screen.findByLabelText("Max upload size (MB, 1–50)")).toHaveValue(15);
    expect(screen.getByLabelText("Session length (minutes, 15–1440)")).toHaveValue(480);
    expect(screen.queryByText(/courier/i)).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox", { name: /export/i })).not.toBeInTheDocument();
    expect(screen.getByText("orderflow_backup_20261012_173654.zip")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Create backup now/ })).toBeInTheDocument();

    await user.clear(screen.getByLabelText("Max upload size (MB, 1–50)"));
    await user.type(screen.getByLabelText("Max upload size (MB, 1–50)"), "20");
    await user.click(screen.getByRole("button", { name: /Save settings/ }));
    expect(api.put).toHaveBeenCalledWith("/api/admin/settings", { max_upload_mb: 20, token_expire_minutes: 480 });
  });
});

describe("passwordProblem", () => {
  it("matches the server rule", () => {
    expect(passwordProblem("short1", "short1")).toMatch(/at least 8/);
    expect(passwordProblem("12345678", "12345678")).toMatch(/mix letters/);
    expect(passwordProblem("Good-Pass-1", "Good-Pass-2")).toMatch(/do not match/);
    expect(passwordProblem("Good-Pass-1", "Good-Pass-1")).toBeNull();
  });
});

describe("Login page", () => {
  it("hides the password by default and shows it with the eye button", async () => {
    const user = userEvent.setup();
    renderAt("/login");
    const password = await screen.findByLabelText("Password");
    await user.type(password, "Secret-Pass-1");
    expect(password).toHaveAttribute("type", "password");
    await user.click(screen.getByRole("button", { name: "Show password" }));
    expect(password).toHaveAttribute("type", "text");
    expect(password).toHaveValue("Secret-Pass-1");
    await user.click(screen.getByRole("button", { name: "Hide password" }));
    expect(password).toHaveAttribute("type", "password");
    expect(api.post).not.toHaveBeenCalled(); // the eye button does not sign in
  });
});

describe("Upload PO: Admin chooses the Sales user", () => {
  const MORE_USERS: AdminUser[] = [
    ...USERS,
    { id: 3, username: "printing", full_name: null, role: "printing", is_active: true, created_at: "2026-10-12T07:00:00Z", updated_at: null, last_login_at: null },
    { id: 4, username: "mohit", full_name: "Mohit Patel", role: "sales", is_active: true, created_at: "2026-10-14T07:00:00Z", updated_at: null, last_login_at: null },
    { id: 5, username: "gone", full_name: null, role: "sales", is_active: false, created_at: "2026-10-12T07:00:00Z", updated_at: null, last_login_at: null },
  ];
  const pdf = () => new File(["%PDF-1.4"], "po.pdf", { type: "application/pdf" });

  it("requires an active Sales user and sends it with the upload", async () => {
    const user = userEvent.setup();
    signIn("admin");
    const base = api.get.getMockImplementation()!;
    api.get.mockImplementation(async (url: string) => (url === "/api/admin/users" ? { items: MORE_USERS } : base(url)));
    api.upload.mockResolvedValue(makeOrder({ id: 9 }));
    renderAt("/upload");
    const select = await screen.findByLabelText(/Sales user/);
    await waitFor(() => expect(select).toBeEnabled());
    const options = within(select).getAllByRole("option").map((o) => o.textContent);
    expect(options).toEqual(["Choose the Sales user this order belongs to", "Mohit Patel (mohit)", "Demo Sales User (sales)"]);

    await user.upload(document.querySelector<HTMLInputElement>('input[type="file"]')!, pdf());
    const button = screen.getByRole("button", { name: /Upload and extract/ });
    expect(button).toBeDisabled(); // mandatory for Admin
    await user.selectOptions(select, "mohit");
    expect(button).toBeEnabled();
    await user.click(button);
    expect(api.upload).toHaveBeenCalledTimes(1);
    const [path, form] = api.upload.mock.calls[0] as [string, FormData];
    expect(path).toBe("/api/orders/upload");
    expect(form.get("owner")).toBe("mohit");
    expect((form.get("file") as File).name).toBe("po.pdf");
  });

  it("is not shown to Sales users, whose uploads stay their own", async () => {
    const user = userEvent.setup();
    signIn("sales");
    api.upload.mockResolvedValue(makeOrder({ id: 9 }));
    renderAt("/upload");
    expect(await screen.findByRole("heading", { name: "Upload PO" })).toBeInTheDocument();
    expect(screen.queryByLabelText(/Sales user/)).not.toBeInTheDocument();
    await user.upload(document.querySelector<HTMLInputElement>('input[type="file"]')!, pdf());
    await user.click(screen.getByRole("button", { name: /Upload and extract/ }));
    const [, form] = api.upload.mock.calls[0] as [string, FormData];
    expect(form.get("owner")).toBeNull();
    expect(api.get).not.toHaveBeenCalledWith("/api/admin/users");
  });
});

describe("Product-wise photo review", () => {
  it("shows Admins which product photo was confirmed or rejected", async () => {
    signIn("admin");
    renderAt("/admin/photos");
    expect(await screen.findByRole("heading", { name: "Photo Reviews" })).toBeInTheDocument();
    const confirmed = (await screen.findByText("SKU-11")).closest("tr")!;
    expect(within(confirmed).getByText("Confirmed")).toBeInTheDocument();
    const rejected = screen.getByText("SKU-12").closest("tr")!;
    expect(within(rejected).getByText("Rejected")).toBeInTheDocument();
    expect(within(rejected).getByText("Logo blurred")).toBeInTheDocument();
    await userEvent.setup().click(screen.getByRole("tab", { name: /Rejected/ }));
    await waitFor(() => expect(api.get).toHaveBeenCalledWith("/api/admin/photo-reviews?status=Rejected"));
  });

  it("confirms the photo of one product from the order page", async () => {
    const user = userEvent.setup();
    signIn("admin");
    const base = api.get.getMockImplementation()!;
    const photo = (id: number, item_id: number) => ({ id, item_id, filename: `p${id}.png`, content_type: "image/png", uploaded_by: "printing", uploaded_at: "2026-10-12T11:00:00Z", url: `/api/orders/1/photos/${id}` });
    const order = makeOrder({
      status: "Live", printing_status: "Processing", internal_order_no: "OF-2026-00001",
      items: [
        makeItem(11, { photo_status: "Pending", photos: [photo(1, 11)] }),
        makeItem(12, { sku: "SKU-12", photo_status: "Confirmed", photo_reviewed_by: "sales", photo_reviewed_at: "2026-10-12T12:00:00Z", photos: [photo(2, 12)] }),
      ],
      photos: [photo(1, 11), photo(2, 12)],
      permissions: { can_edit: false, can_publish: false, can_comment: true, next_printing_statuses: [], can_upload_photos: false, can_review_photos: true, can_delete: true, can_restore: false },
    });
    api.get.mockImplementation(async (url: string) => (url === "/api/orders/1" ? order : base(url)));
    api.post.mockResolvedValue(order);
    api.blob.mockReturnValue(new Promise(() => {})); // photo thumbnails stay loading
    renderAt("/orders/1");
    await screen.findByRole("heading", { name: "OF-2026-00001" });
    await user.click(await screen.findByRole("button", { name: "Confirm preview of SKU-11" }));
    expect(screen.queryByRole("button", { name: "Confirm preview of SKU-12" })).not.toBeInTheDocument(); // already confirmed
    await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: /Yes, confirm/ }));
    expect(api.post).toHaveBeenCalledWith("/api/orders/1/items/11/photo-review", { version: 3, action: "confirm", note: null });
  });

  it("locks Mark Print Done for Printing until every product preview is confirmed", async () => {
    signIn("printing");
    const base = api.get.getMockImplementation()!;
    const perms = { can_edit: false, can_publish: false, can_comment: true, next_printing_statuses: ["Print Done" as const], can_upload_photos: true, can_review_photos: false, can_delete: false, can_restore: false };
    const order = makeOrder({
      status: "Live", printing_status: "Processing", internal_order_no: "OF-2026-00002",
      items: [makeItem(11, { photo_status: "Confirmed" }), makeItem(12, { sku: "SKU-12", photo_status: "Rejected", photo_review_note: "Logo too small" })],
      permissions: perms,
    });
    api.get.mockImplementation(async (url: string) => (url === "/api/orders/1" ? order : base(url)));
    renderAt("/orders/1");
    expect(await screen.findByRole("button", { name: /Mark Print Done/ })).toBeDisabled();
    expect(screen.getByText(/1 product preview not confirmed by Sales/)).toBeInTheDocument();
    expect(screen.getByText(/Logo too small/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upload preview for SKU-12" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Upload preview for SKU-11" })).not.toBeInTheDocument(); // confirmed is final
  });

  it("shows Sales' reject on the Printing screen without a manual refresh", async () => {
    signIn("printing");
    const base = api.get.getMockImplementation()!;
    const perms = { can_edit: false, can_publish: false, can_comment: true, next_printing_statuses: ["Print Done" as const], can_upload_photos: true, can_review_photos: false, can_delete: false, can_restore: false };
    const before = makeOrder({ status: "Live", printing_status: "Processing", internal_order_no: "OF-2026-00002", items: [makeItem(11, { photo_status: "Pending" })], permissions: perms });
    const after = { ...before, version: 4, items: [makeItem(11, { photo_status: "Rejected" as const, photo_review_note: "Make the logo bigger", photo_reviewed_by: "sales" })] };
    let current = before;
    api.get.mockImplementation(async (url: string) => (url === "/api/orders/1" ? current : base(url)));
    renderAt("/orders/1");
    expect(await screen.findByText("Waiting for confirmation")).toBeInTheDocument();
    current = after; // Sales rejects the preview in their own browser
    window.dispatchEvent(new Event("focus")); // also happens every 10 seconds
    expect(await screen.findByText(/Make the logo bigger/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Upload preview for SKU-11" })).toHaveTextContent("Upload new preview");
  });
});

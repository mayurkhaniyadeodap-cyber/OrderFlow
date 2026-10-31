import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { createMemoryRouter, RouterProvider } from "react-router-dom";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { routes } from "../App";
import { fmtDay } from "../format";
import { makeOrder } from "../test/fixtures";
import type { Role } from "../types";
import { Donut, HBars, Pipeline, TrendBars } from "./charts";
import { QuickFilters, ViewSwitch } from "./OrdersViews";

const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), del: vi.fn(), upload: vi.fn(), blob: vi.fn() }));
vi.mock("../api", async (importOriginal) => ({ ...(await importOriginal<typeof import("../api")>()), api }));

const trend = Array.from({ length: 14 }, (_, i) => ({ date: `2026-10-${String(i + 1).padStart(2, "0")}`, created: 1, published: 1, finished: 1 }));
const INSIGHTS = {
  days: 14,
  trend,
  job_ages: [{ label: "Under 1 day", count: 2 }],
};
const MONEY = {
  top_customers: [{ name: "Sample Traders", total: 1000 }],
  pipeline: { uploaded: 2, published: 1, processing: 1, print_done: 0 },
};
const COUNTS = { total: 3, live: 2, awaiting_printing: 1, processing: 1, print_done: 0, draft: 1 };

function open(role: Role, attention: object = { count: 0, items: [] }, insightsFail = false) {
  sessionStorage.setItem("orderflow.token", "test-token");
  api.get.mockImplementation(async (url: string) => {
    if (url === "/api/me") return { user: { id: 2, username: role, full_name: null, role }, config: { max_upload_mb: 15, timezone: "Asia/Kolkata" } };
    if (url === "/api/dashboard") return { role, counts: COUNTS, recent: [] };
    if (url === "/api/dashboard/attention") return attention;
    if (url.startsWith("/api/dashboard/insights")) {
      if (insightsFail) throw new Error("old backend");
      return { ...INSIGHTS, role, ...(role === "printing" ? {} : MONEY) };
    }
    throw new Error(`unexpected GET ${url}`);
  });
  render(<RouterProvider router={createMemoryRouter(routes, { initialEntries: ["/"] })} />);
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  delete document.documentElement.dataset.theme;
});

describe("formatters", () => {
  it("keeps a chart day on its own date in any time zone", () => {
    expect(fmtDay("2026-10-31")).toBe("31 Oct");
  });
});

describe("charts", () => {
  it("gives screen readers the numbers behind the daily bars", () => {
    render(<TrendBars title="Orders" labels={["01 Oct", "02 Oct"]} series={[{ name: "Uploaded", values: [3, 5], color: "red" }]} />);
    expect(screen.getByRole("img", { name: "Orders" })).toBeInTheDocument();
    expect(within(screen.getByRole("table")).getByRole("cell", { name: "5" })).toBeInTheDocument();
  });

  it("draws zero-only and empty data without breaking", () => {
    render(
      <>
        <TrendBars title="Quiet" labels={["01 Oct"]} series={[{ name: "A", values: [0], color: "red" }]} />
        <Donut title="Empty" center={0} centerLabel="Live" parts={[{ label: "New", value: 0, color: "red" }]} />
        <Pipeline steps={[{ label: "Uploaded", value: 0 }]} />
        <HBars rows={[]} empty="Nothing here." />
      </>,
    );
    expect(screen.getByText("Nothing here.")).toBeInTheDocument();
    expect(screen.getByText("No orders yet.")).toBeInTheDocument();
    expect(document.body.textContent).not.toMatch(/NaN|undefined/);
  });
});

describe("daily bars", () => {
  it("draws a bar only for days that have orders, and totals the period in the legend", () => {
    render(<TrendBars title="Orders" labels={["01 Oct", "02 Oct", "03 Oct"]} series={[
      { name: "Uploaded", values: [3, 0, 4], color: "blue" },
      { name: "Published", values: [1, 0, 2], color: "green" },
    ]} />);
    expect(document.querySelectorAll(".trend-day")).toHaveLength(3);
    expect(document.querySelectorAll(".trend-day path")).toHaveLength(4);
    expect(document.querySelector(".chart-legend")).toHaveTextContent("Uploaded7Published3");
  });

  it("leaves out the legend for a single series", () => {
    render(<TrendBars title="Jobs" labels={["01 Oct"]} series={[{ name: "Print Done", values: [2], color: "green" }]} />);
    expect(document.querySelector(".chart-legend")).toBeNull();
  });
});

describe("order list controls", () => {
  it("quick filters report the status and printing filter", async () => {
    const onPick = vi.fn();
    render(<QuickFilters status="" printing="" showDrafts onPick={onPick} />);
    await userEvent.click(screen.getByRole("button", { name: "Drafts" }));
    expect(onPick).toHaveBeenCalledWith("Draft", "");
    await userEvent.click(screen.getByRole("button", { name: "Print Done" }));
    expect(onPick).toHaveBeenCalledWith("", "Print Done");
  });

  it("hides the draft filters from Printing", () => {
    render(<QuickFilters status="" printing="" showDrafts={false} onPick={vi.fn()} />);
    expect(screen.queryByRole("button", { name: "Drafts" })).not.toBeInTheDocument();
  });

  it("marks the chosen layout", () => {
    render(<ViewSwitch view="board" onChange={vi.fn()} />);
    expect(screen.getByRole("button", { name: "Board" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "Table" })).toHaveAttribute("aria-pressed", "false");
  });
});

describe("app shell", () => {
  it("switches theme and remembers it", async () => {
    open("sales");
    await userEvent.click(await screen.findByRole("button", { name: "Switch to dark mode" }));
    expect(document.documentElement.dataset.theme).toBe("dark");
    expect(localStorage.getItem("orderflow.theme")).toBe("dark");
    expect(screen.getByRole("button", { name: "Switch to light mode" })).toBeInTheDocument();
  });

  it("shows waiting orders in the notification bell", async () => {
    open("sales", { count: 1, items: [makeOrder({ id: 9, customer_name: "Sample Traders", status: "Draft", warning_count: 2 })] });
    await userEvent.click(await screen.findByRole("button", { name: "Notifications, 1 waiting" }));
    const panel = document.querySelector(".bell-panel") as HTMLElement;
    expect(within(panel).getByText(/Sample Traders/)).toBeInTheDocument();
    expect(within(panel).getByText("2 to review")).toBeInTheDocument();
  });

  it("keeps the dashboard working when the charts cannot load", async () => {
    open("sales", { count: 0, items: [] }, true);
    expect(await screen.findByText(/Charts could not be loaded/)).toBeInTheDocument();
    expect(screen.getByText("Total orders")).toBeInTheDocument();
  });

  it("shows Printing no money", async () => {
    open("printing");
    expect(await screen.findByRole("heading", { name: "Jobs finished per day" })).toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: "Open jobs by age" })).toBeInTheDocument();
    expect(document.body.textContent).not.toContain("₹");
  });
});

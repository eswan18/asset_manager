import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { CashFlowsOverview, SavedFlow } from "@/api/cash-flows";
import {
  findSheet,
  mockApi,
  renderRoute,
  shellApi,
  type FakeResponse,
} from "@/test/utils";

import { EMPTY, SEED_MONTH } from "./cash-flows.fixtures";

const PAGE = "/workspaces/1/cash-flows";
const API = "/api/workspaces/1/cash-flows";
// SEED_MONTH's ids: flows 1-8 (Groceries 5, Car insurance 8), categories
// Work 11, Housing 12, Food 13, Transport 14, Gifts 15.

function saved(changes: Partial<SavedFlow> = {}): SavedFlow {
  return {
    id: 99,
    name: "Gym",
    direction: "expense",
    amount: "1045.51",
    every: 2,
    unit: "week",
    category_id: 12,
    description: "Monthly pass",
    is_estimate: true,
    per_day: "-74.68",
    per_month: "-2271.49",
    per_year: "-27257.87",
    ...changes,
  };
}

/** The shell and the overview, plus `writes`. */
function drawerApi(
  writes: Record<string, FakeResponse | (() => FakeResponse)> = {},
  overview: CashFlowsOverview = SEED_MONTH,
) {
  return mockApi({
    ...shellApi(),
    "GET /api/workspaces/1/cash-flows/overview": { body: overview },
    "GET /api/workspaces/2/cash-flows/overview": {
      body: { ...overview, can_edit: false },
    },
    ...writes,
  });
}

function lastWrite(fetchMock: ReturnType<typeof mockApi>) {
  const writes = fetchMock.mock.calls.filter(
    ([, init]) => init?.method !== undefined && init.method !== "GET",
  );
  const [url, init] = writes[writes.length - 1];
  return {
    url: new URL(String(url), "http://localhost").pathname,
    method: init!.method,
    body: typeof init!.body === "string" ? JSON.parse(init!.body) : undefined,
    csrf: (init!.headers as Record<string, string>)["X-Requested-With"],
  };
}

const field = (name: string) =>
  screen
    .getByRole("dialog")
    .querySelector<HTMLInputElement>(`[name="${name}"]`)!;
const eyebrow = () =>
  screen.getByRole("dialog").querySelector("[data-slot=eyebrow]")!;
const section = () =>
  screen.getByRole("dialog").style.getPropertyValue("--section");
const strip = () =>
  ["rate-day", "rate-month", "rate-year"].map(
    (id) => document.getElementById(id)!.textContent,
  );

describe("the cash flow drawer, editing", () => {
  it("is prefilled, over the page", async () => {
    drawerApi();
    renderRoute(`${PAGE}/5/edit?per=day`);
    const dialog = await findSheet({ name: "Groceries" });
    expect(eyebrow()).toHaveTextContent("Edit expense · Food");
    // Food is the second-largest expense category: its card's color.
    expect(section()).toBe("var(--liability-2)");
    expect(
      within(dialog).getByRole("radio", { name: "Expense" }),
    ).toBeChecked();
    expect(field("name")).toHaveValue("Groceries");
    expect(field("amount")).toHaveValue("180.00");
    expect(field("every")).toHaveValue("1");
    expect(field("unit")).toHaveValue("week");
    expect(
      within(dialog).getByRole("combobox", { name: "Category" }),
    ).toHaveValue("13");
    expect(
      within(dialog).getByRole("checkbox", { name: /This is an estimate/ }),
    ).toBeChecked();
    expect(field("description")).toHaveValue("Costco + weekly shop");
    expect(strip()).toEqual(["$25.71", "$782.14", "$9,385.71"]);
    await waitFor(() => expect(field("name")).toHaveFocus());
    expect(document.title).toBe("Groceries · Household · Sensibility");
    // The page is behind it.
    expect(
      screen.getByRole("heading", { level: 2, name: "Food", hidden: true }),
    ).toBeInTheDocument();
  });

  it("lists the categories with Uncategorized first", async () => {
    drawerApi();
    renderRoute(`${PAGE}/5/edit`);
    const select = await screen.findByRole("combobox", { name: "Category" });
    expect(
      within(select)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual([
      "Uncategorized",
      "Work",
      "Housing",
      "Food",
      "Transport",
      "Gifts",
    ]);
  });

  it("colors an income blue and an uncategorized expense as its card", async () => {
    drawerApi();
    renderRoute(`${PAGE}/1/edit`);
    await findSheet({ name: "Salary" });
    expect(eyebrow()).toHaveTextContent("Edit income · Work");
    expect(section()).toBe("var(--asset)");
  });

  it("follows direction and category in the header", async () => {
    drawerApi();
    const { user } = renderRoute(`${PAGE}/5/edit`);
    const dialog = await findSheet({ name: "Groceries" });

    await user.click(within(dialog).getByRole("radio", { name: "Income" }));
    expect(eyebrow()).toHaveTextContent("Edit income · Food");
    expect(section()).toBe("var(--asset)");

    await user.click(within(dialog).getByRole("radio", { name: "Expense" }));
    expect(eyebrow()).toHaveTextContent("Edit expense · Food");
    expect(section()).toBe("var(--liability-2)");

    const select = within(dialog).getByRole("combobox", { name: "Category" });
    await user.selectOptions(select, "Housing");
    expect(eyebrow()).toHaveTextContent("Edit expense · Housing");
    expect(section()).toBe("var(--liability)");

    // Gifts has no expenses, so no color of its own on the page.
    await user.selectOptions(select, "Gifts");
    expect(section()).toBe("var(--liability)");

    await user.selectOptions(select, "Uncategorized");
    expect(eyebrow().textContent).toBe("Edit expense");
    expect(section()).toBe("var(--liability-3)");
  });

  it("recomputes the rates strip as you type", async () => {
    drawerApi();
    const { user } = renderRoute(`${PAGE}/5/edit`);
    await findSheet();
    const enter = async (amount: string, every: string, unit: string) => {
      await user.clear(field("amount"));
      if (amount) await user.type(field("amount"), amount);
      await user.clear(field("every"));
      if (every) await user.type(field("every"), every);
      await user.selectOptions(field("unit"), unit);
    };
    await enter("100", "1", "week");
    expect(strip()).toEqual(["$14.29", "$434.52", "$5,214.29"]);
    await enter("$1,200", "2", "year");
    expect(strip()).toEqual(["$1.64", "$50.00", "$600.00"]);
    await enter("abc", "1", "month");
    expect(strip()).toEqual(["—", "—", "—"]);
    await enter("5", "0", "month");
    expect(strip()).toEqual(["—", "—", "—"]);
    await enter("5", "", "month");
    expect(strip()).toEqual(["—", "—", "—"]);
  });

  it("saves every field and goes back to the page with a flash", async () => {
    const fetchMock = drawerApi({
      "PATCH /api/workspaces/1/cash-flows/5": {
        body: saved({ id: 5, name: "Food shop", per_month: "2027.78" }),
      },
    });
    const { user, router } = renderRoute(`${PAGE}/5/edit?per=day`);
    const dialog = await findSheet({ name: "Groceries" });
    await user.clear(field("name"));
    await user.type(field("name"), "Food shop");
    await user.click(within(dialog).getByRole("radio", { name: "Income" }));
    await user.clear(field("amount"));
    await user.type(field("amount"), "200");
    await user.clear(field("every"));
    await user.type(field("every"), "3");
    await user.selectOptions(field("unit"), "day");
    await user.selectOptions(field("category_id"), "Uncategorized");
    await user.click(
      within(dialog).getByRole("checkbox", { name: /This is an estimate/ }),
    );
    await user.clear(field("description"));
    await user.click(within(dialog).getByRole("button", { name: "Save" }));

    expect(
      await screen.findByText("Saved Food shop: $2,027.78 a month."),
    ).toBeInTheDocument();
    expect(router.state.location.pathname).toBe(PAGE);
    expect(router.state.location.search).toBe("?per=day");
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(lastWrite(fetchMock)).toEqual({
      url: `${API}/5`,
      method: "PATCH",
      body: {
        name: "Food shop",
        direction: "income",
        amount: "200",
        every: 3,
        unit: "day",
        category_id: null,
        description: "",
        is_estimate: false,
      },
      csrf: "sensibility",
    });
  });

  it("deletes and goes back to the page", async () => {
    const fetchMock = drawerApi({
      "DELETE /api/workspaces/1/cash-flows/7": { body: { deleted: 7 } },
    });
    const { user, router } = renderRoute(`${PAGE}/7/edit?per=year`);
    const dialog = await findSheet({ name: "Gas" });
    await user.click(within(dialog).getByRole("button", { name: "Delete" }));
    expect(await screen.findByText("Deleted Gas")).toBeInTheDocument();
    expect(router.state.location.pathname).toBe(PAGE);
    expect(router.state.location.search).toBe("?per=year");
    expect(lastWrite(fetchMock)).toMatchObject({
      url: `${API}/7`,
      method: "DELETE",
      csrf: "sensibility",
    });
  });

  it("shows the server's refusal in the drawer, keeping the input", async () => {
    drawerApi({
      "PATCH /api/workspaces/1/cash-flows/5": {
        status: 400,
        body: { error: "A cash flow named 'Restaurants' already exists" },
      },
    });
    const { user, router } = renderRoute(`${PAGE}/5/edit?per=year`);
    const dialog = await findSheet({ name: "Groceries" });
    await user.clear(field("name"));
    await user.type(field("name"), "Restaurants");
    await user.selectOptions(field("category_id"), "Uncategorized");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "A cash flow named 'Restaurants' already exists",
    );
    // Still the saved title; the eyebrow follows the form.
    expect(screen.getByRole("dialog", { name: "Groceries" })).toBe(dialog);
    expect(eyebrow().textContent).toBe("Edit expense");
    expect(field("name")).toHaveValue("Restaurants");
    expect(router.state.location.pathname).toBe(`${PAGE}/5/edit`);
  });

  it("goes back to the page for a flow that isn't there", async () => {
    drawerApi();
    const { router } = renderRoute(`${PAGE}/999/edit?per=year`);
    await waitFor(() => expect(router.state.location.pathname).toBe(PAGE));
    expect(router.state.location.search).toBe("?per=year");
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
  });

  it.each([
    ["the ✕", "Close"],
    ["Cancel", "Cancel"],
  ])("closes to the page in its period with %s", async (_, name) => {
    drawerApi();
    const { user, router } = renderRoute(`${PAGE}/5/edit?per=year`);
    const dialog = await findSheet();
    await user.click(within(dialog).getByRole("button", { name }));
    await waitFor(() => expect(router.state.location.pathname).toBe(PAGE));
    expect(router.state.location.search).toBe("?per=year");
  });

  it("closes on Escape", async () => {
    drawerApi();
    const { user, router } = renderRoute(`${PAGE}/5/edit?per=day`);
    await findSheet();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(router.state.location.search).toBe("?per=day"));
    expect(router.state.location.pathname).toBe(PAGE);
  });
});

describe("the cash flow drawer, new", () => {
  it("starts as an uncategorized monthly expense", async () => {
    drawerApi();
    renderRoute(`${PAGE}/new`);
    const dialog = await findSheet({ name: "New cash flow" });
    expect(eyebrow().textContent).toBe("New expense");
    expect(
      within(dialog).getByRole("radio", { name: "Expense" }),
    ).toBeChecked();
    expect(field("amount")).toHaveValue("");
    expect(field("every")).toHaveValue("1");
    expect(field("unit")).toHaveValue("month");
    expect(field("category_id")).toHaveValue("");
    expect(
      within(dialog).getByRole("checkbox", { name: /This is an estimate/ }),
    ).not.toBeChecked();
    expect(strip()).toEqual(["—", "—", "—"]);
    expect(
      within(dialog).queryByRole("button", { name: "Delete" }),
    ).not.toBeInTheDocument();
    expect(document.title).toBe("New cash flow · Household · Sensibility");
  });

  it("starts as income from the income card", async () => {
    drawerApi();
    renderRoute(`${PAGE}/new?direction=income&per=year`);
    const dialog = await findSheet({ name: "New cash flow" });
    expect(eyebrow().textContent).toBe("New income");
    expect(within(dialog).getByRole("radio", { name: "Income" })).toBeChecked();
    expect(section()).toBe("var(--asset)");
  });

  it("starts in its card's category", async () => {
    drawerApi();
    renderRoute(`${PAGE}/new?direction=expense&category_id=13`);
    await findSheet();
    expect(eyebrow().textContent).toBe("New expense · Food");
    expect(field("category_id")).toHaveValue("13");
    expect(section()).toBe("var(--liability-2)");
  });

  it.each(["direction=sideways&category_id=999", "category_id=food"])(
    "reads unknown choices (%s) as an uncategorized expense",
    async (query) => {
      drawerApi();
      renderRoute(`${PAGE}/new?${query}`);
      const dialog = await findSheet();
      expect(
        within(dialog).getByRole("radio", { name: "Expense" }),
      ).toBeChecked();
      expect(field("category_id")).toHaveValue("");
    },
  );

  it("offers only Uncategorized over an empty page", async () => {
    drawerApi({}, EMPTY);
    renderRoute(`${PAGE}/new?direction=income`);
    const select = await screen.findByRole("combobox", { name: "Category" });
    expect(
      within(select)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["Uncategorized"]);
  });

  it("creates, and says what it comes to a month", async () => {
    const fetchMock = drawerApi({
      "POST /api/workspaces/1/cash-flows": { status: 201, body: saved() },
    });
    const { user, router } = renderRoute(`${PAGE}/new?per=year`);
    const dialog = await findSheet();
    await user.type(field("name"), "  Gym  ");
    await user.type(field("amount"), "$1,045.505");
    await user.clear(field("every"));
    await user.type(field("every"), "2");
    await user.selectOptions(field("unit"), "week");
    await user.selectOptions(field("category_id"), "Housing");
    await user.click(
      within(dialog).getByRole("checkbox", { name: /This is an estimate/ }),
    );
    await user.type(field("description"), " Monthly pass ");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));

    expect(
      await screen.findByText("Added Gym: $2,271.49 a month."),
    ).toBeInTheDocument();
    expect(router.state.location.pathname).toBe(PAGE);
    expect(router.state.location.search).toBe("?per=year");
    // The server trims and rounds; the drawer sends what was typed.
    expect(lastWrite(fetchMock)).toEqual({
      url: API,
      method: "POST",
      body: {
        name: "  Gym  ",
        direction: "expense",
        amount: "1045.505",
        every: 2,
        unit: "week",
        category_id: 12,
        description: " Monthly pass ",
        is_estimate: true,
      },
      csrf: "sensibility",
    });
  });

  it.each([
    ["abc", "1", "Amount must be a number"],
    ["1e3", "1", "Amount must be a number"],
    ["5", "1.5", "Every must be a whole number, e.g. 2 for every 2 weeks"],
  ])(
    "refuses %s every %s before sending: %s",
    async (amount, every, message) => {
      const fetchMock = drawerApi();
      const { user } = renderRoute(`${PAGE}/new`);
      const dialog = await findSheet();
      await user.type(field("name"), "Gym");
      await user.type(field("amount"), amount);
      await user.clear(field("every"));
      await user.type(field("every"), every);
      await user.click(within(dialog).getByRole("button", { name: "Save" }));
      expect(await within(dialog).findByRole("alert")).toHaveTextContent(
        message,
      );
      expect(field("amount")).toHaveValue(amount);
      expect(
        fetchMock.mock.calls.filter(([, init]) => init?.method === "POST"),
      ).toEqual([]);
    },
  );

  it.each([
    ["Amount cannot be negative; set the direction to expense instead", "-5"],
    ["Amount is too large", "10000000000000"],
  ])("shows the server's %s", async (message, amount) => {
    drawerApi({
      "POST /api/workspaces/1/cash-flows": {
        status: 400,
        body: { error: message },
      },
    });
    const { user } = renderRoute(`${PAGE}/new?per=day`);
    const dialog = await findSheet();
    await user.type(field("name"), "Gym");
    await user.type(field("amount"), amount);
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(message);
    expect(screen.getByRole("dialog", { name: "New cash flow" })).toBe(dialog);
  });
});

describe("the cash flow drawer, for a viewer", () => {
  it.each(["new?per=year", "5/edit?per=year"])(
    "goes back to the page (%s)",
    async (path) => {
      drawerApi();
      const { router } = renderRoute(`/workspaces/2/cash-flows/${path}`);
      await waitFor(() =>
        expect(router.state.location.pathname).toBe("/workspaces/2/cash-flows"),
      );
      expect(router.state.location.search).toBe("?per=year");
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    },
  );
});

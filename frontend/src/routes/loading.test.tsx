/** Loading states (frontend/README.md, "Loading"): a page or drawer whose
 * data is still on its way shows a skeleton in its own shape, a drawer
 * opens at once with what it knows, and reaching for a link prefetches what
 * it opens. Each test holds a request (`held`) and releases it. */
import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Dashboard } from "@/api/dashboard";
import { makeQueryClient } from "@/api/queryClient";
import type { WorkspaceSettings } from "@/api/settings";
import {
  findSheet,
  held,
  ME,
  mockApi,
  renderRoute,
  shellApi,
} from "@/test/utils";

import { CHECKING, detail, overview } from "./accounts.fixtures";
import { SEED_MONTH } from "./cash-flows.fixtures";

const API = "/api/workspaces/1";
const WS = "/workspaces/1";

/** The app's routes under the app's query defaults (data fresh for 30s,
 * which is what lets a click reuse a prefetch), without retries. */
function renderApp(path: string) {
  const rendered = renderRoute(path);
  const app = makeQueryClient().getDefaultOptions();
  rendered.queryClient.setDefaultOptions({
    ...app,
    queries: { ...app.queries, retry: false },
  });
  return rendered;
}

const DASHBOARD: Dashboard = {
  has_data: true,
  can_edit: true,
  range: "1y",
  ranges: [
    { key: "6m", label: "6M" },
    { key: "1y", label: "1Y" },
    { key: "all", label: "All" },
  ],
  net_worth: "12550.50",
  last_snapshot: "2026-10-20",
  change: null,
  history: [
    {
      date: "2026-10-20",
      assets: "13000.50",
      liabilities: "450.00",
      net_worth: "12550.50",
    },
  ],
  categories: { asset: [], liability: [] },
  bars: { asset: [], liability: [] },
  cards: [],
  onboarding: null,
};

const SETTINGS: WorkspaceSettings = {
  id: 1,
  name: "Household",
  role: "owner",
  is_owner: true,
  can_leave: false,
  members: [
    {
      user_id: 1,
      name: "Ethan Swan",
      email: "me@example.com",
      display_name: "Ethan Swan",
      role: "owner",
      joined_at: "2026-01-01T00:00:00+00:00",
      you: true,
      removable: false,
    },
  ],
  invites: [],
  invite_ttl_days: 14,
  roles: ["viewer", "editor", "owner"],
};

/** The loading region a label names: its sr-only label's region. */
function loading(label: string) {
  return screen.getByText(label).closest("[data-slot=loading]");
}

describe("a page's first load", () => {
  it("dashboard: a skeleton, then the page", async () => {
    const dashboard = held({ body: DASHBOARD });
    mockApi({
      ...shellApi(),
      [`GET ${API}/dashboard`]: dashboard.handler,
    });
    renderApp(WS);
    expect(
      await screen.findByText("Loading the dashboard"),
    ).toBeInTheDocument();
    expect(loading("Loading the dashboard")).toHaveAttribute(
      "aria-busy",
      "true",
    );
    // The chart's place keeps its height while it loads.
    expect(
      loading("Loading the dashboard")!.querySelectorAll("[data-slot=skeleton]")
        .length,
    ).toBeGreaterThan(5);

    dashboard.release();
    expect(
      await screen.findByRole("link", { name: "Update balances" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Loading the dashboard")).toBeNull();
  });

  it("accounts: a skeleton, then the page", async () => {
    const accounts = held({ body: overview() });
    mockApi({
      ...shellApi(),
      [`GET ${API}/accounts/overview`]: accounts.handler,
    });
    renderApp(`${WS}/accounts`);
    await screen.findByText("Loading accounts");
    expect(screen.queryByRole("heading", { name: "Accounts" })).toBeNull();

    accounts.release();
    expect(
      await screen.findByRole("heading", { name: "Accounts" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Loading accounts")).toBeNull();
  });

  it("cash flows: a skeleton, then the page", async () => {
    const flows = held({ body: SEED_MONTH });
    mockApi({
      ...shellApi(),
      [`GET ${API}/cash-flows/overview`]: flows.handler,
    });
    renderApp(`${WS}/cash-flows`);
    await screen.findByText("Loading cash flows");

    flows.release();
    expect(await screen.findByText("Where income goes")).toBeInTheDocument();
    expect(screen.queryByText("Loading cash flows")).toBeNull();
  });

  it("settings: a skeleton, then the page", async () => {
    const settings = held({ body: SETTINGS });
    mockApi({
      ...shellApi(),
      [`GET ${API}/settings`]: settings.handler,
    });
    renderApp(`${WS}/settings`);
    await screen.findByText("Loading settings");

    settings.release();
    expect(
      await screen.findByRole("heading", { name: "Household settings" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Loading settings")).toBeNull();
  });

  it("welcome: a skeleton until the invites are in", async () => {
    const invites = held({ body: { invites: [] } });
    mockApi({
      "GET /api/me": { body: ME },
      "GET /api/invites": invites.handler,
    });
    renderApp("/welcome");
    await screen.findByText("Loading invites");

    invites.release();
    expect(
      await screen.findByRole("heading", { name: "New workspace" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Loading invites")).toBeNull();
  });

  it("the shell: its own skeleton until it knows who you are", async () => {
    const me = held({ body: ME });
    mockApi({
      "GET /api/me": me.handler,
      "GET /api/invites": { body: { invites: [] } },
      [`GET ${API}/accounts/overview`]: { body: overview() },
    });
    renderApp(`${WS}/accounts`);
    await screen.findByText("Loading Sensibility");
    expect(screen.queryByRole("navigation")).toBeNull();

    me.release();
    expect(
      await screen.findByRole("navigation", { name: "Main" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Loading Sensibility")).toBeNull();
  });

  it("keeps a page's error state", async () => {
    mockApi({
      ...shellApi(),
      [`GET ${API}/accounts/overview`]: { status: 500, body: { error: "x" } },
    });
    renderApp(`${WS}/accounts`);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "An error occurred while loading your data.",
    );
    expect(screen.queryByText("Loading accounts")).toBeNull();
  });
});

describe("a drawer opens at once", () => {
  it("an account by its URL: the sheet, busy; then the form, focused", async () => {
    const accounts = held({ body: overview() });
    const account = held({ body: detail(CHECKING) });
    mockApi({
      ...shellApi(),
      [`GET ${API}/accounts/overview`]: accounts.handler,
      [`GET ${API}/accounts/${CHECKING.id}`]: account.handler,
    });
    renderApp(`${WS}/accounts/${CHECKING.id}/edit`);

    // Nothing known yet: a skeleton title, named for screen readers.
    const sheet = await screen.findByRole("dialog", {
      name: "Loading account",
    });
    expect(sheet).toHaveAttribute("aria-busy", "true");
    expect(sheet).toHaveTextContent("Accounts");
    expect(within(sheet).getByText("Loading the form")).toBeInTheDocument();
    expect(within(sheet).queryByLabelText("Name")).toBeNull();
    expect(sheet).toHaveFocus();

    // The overview has the account: the form, its Name focused, while
    // the history still loads.
    accounts.release();
    const form = await screen.findByRole("dialog", { name: "Checking" });
    expect(form).not.toHaveAttribute("aria-busy");
    expect(within(form).getByLabelText("Name")).toHaveFocus();
    expect(within(form).getByLabelText("Name")).toHaveValue("Checking");
    expect(within(form).getByText("Loading history")).toBeInTheDocument();
    expect(within(form).queryByRole("region", { name: "Retire" })).toBeNull();

    account.release();
    expect(
      await within(form).findByRole("region", { name: "Retire" }),
    ).toBeInTheDocument();
    expect(form.querySelector("summary")).toHaveTextContent(
      "History (1 snapshot)",
    );
    expect(within(form).queryByText("Loading history")).toBeNull();
  });

  it("an account from its row: the form at once, the history after", async () => {
    const account = held({ body: detail(CHECKING) });
    mockApi({
      ...shellApi(),
      [`GET ${API}/accounts/overview`]: { body: overview() },
      [`GET ${API}/accounts/${CHECKING.id}`]: account.handler,
    });
    const { user } = renderApp(`${WS}/accounts`);
    await user.click(await screen.findByRole("link", { name: "Checking" }));

    // The drawer's route is lazy, so its code may still be arriving; the
    // detail stays held throughout, so this is still "before the detail".
    const sheet = await screen.findByRole("dialog", { name: "Checking" });
    expect(sheet).toHaveTextContent("Edit asset");
    await waitFor(() =>
      expect(within(sheet).getByLabelText("Name")).toHaveFocus(),
    );
    expect(within(sheet).getByText("Loading history")).toBeInTheDocument();

    // What's typed survives the detail landing.
    await user.type(within(sheet).getByLabelText("Name"), " account");
    account.release();
    await within(sheet).findByRole("region", { name: "Retire" });
    expect(within(sheet).getByLabelText("Name")).toHaveValue(
      "Checking account",
    );
  });

  it("a new account by its URL: its type's header, then the form", async () => {
    const accounts = held({ body: overview() });
    mockApi({
      ...shellApi(),
      [`GET ${API}/accounts/overview`]: accounts.handler,
    });
    renderApp(`${WS}/accounts/new?type=liability`);
    const sheet = await screen.findByRole("dialog", { name: "New liability" });
    expect(sheet).toHaveAttribute("aria-busy", "true");
    expect(sheet).toHaveTextContent("New account");

    accounts.release();
    const form = await findSheet({ name: "New liability" });
    expect(within(form).getByLabelText("Name")).toHaveFocus();
    expect(within(form).getByLabelText("Liability")).toBeChecked();
  });

  it("a cash flow by its URL: busy, then the form, focused", async () => {
    const flows = held({ body: SEED_MONTH });
    mockApi({
      ...shellApi(),
      [`GET ${API}/cash-flows/overview`]: flows.handler,
    });
    renderApp(`${WS}/cash-flows/5/edit`);
    const sheet = await screen.findByRole("dialog", {
      name: "Loading cash flow",
    });
    expect(sheet).toHaveAttribute("aria-busy", "true");
    expect(within(sheet).getByText("Loading the form")).toBeInTheDocument();

    flows.release();
    const form = await findSheet({ name: "Groceries" });
    expect(within(form).getByLabelText("Name")).toHaveFocus();
    expect(within(form).getByLabelText("Name")).toHaveValue("Groceries");
  });

  it("a new cash flow by its URL: its header from the link", async () => {
    const flows = held({ body: SEED_MONTH });
    mockApi({
      ...shellApi(),
      [`GET ${API}/cash-flows/overview`]: flows.handler,
    });
    renderApp(`${WS}/cash-flows/new?direction=income`);
    const sheet = await screen.findByRole("dialog", { name: "New cash flow" });
    expect(sheet).toHaveAttribute("aria-busy", "true");
    expect(sheet).toHaveTextContent("New income");

    flows.release();
    const form = await findSheet({ name: "New cash flow" });
    expect(within(form).getByLabelText("Name")).toHaveFocus();
    expect(within(form).getByRole("radio", { name: "Income" })).toBeChecked();
  });

  it("categories by URL: the list waits, adding doesn't", async () => {
    const flows = held({ body: SEED_MONTH });
    mockApi({
      ...shellApi(),
      [`GET ${API}/cash-flows/overview`]: flows.handler,
    });
    renderApp(`${WS}/cash-flow-categories?add=1`);
    const sheet = await screen.findByRole("dialog", { name: "Categories" });
    expect(sheet).toHaveAttribute("aria-busy", "true");
    expect(within(sheet).getByText("Loading categories")).toBeInTheDocument();
    expect(within(sheet).getByLabelText("New category name")).toHaveFocus();

    flows.release();
    expect(
      await within(sheet).findByLabelText("Name of Housing"),
    ).toBeInTheDocument();
    expect(sheet).not.toHaveAttribute("aria-busy");
    expect(within(sheet).getByLabelText("New category name")).toHaveFocus();
  });

  it("closes while loading, by Escape or the ✕", async () => {
    const accounts = held({ body: overview() });
    mockApi({
      ...shellApi(),
      [`GET ${API}/accounts/overview`]: accounts.handler,
      [`GET ${API}/accounts/${CHECKING.id}`]: { body: detail(CHECKING) },
    });
    const { user, router } = renderApp(`${WS}/accounts/${CHECKING.id}/edit`);
    await screen.findByRole("dialog", { name: "Loading account" });
    await user.keyboard("{Escape}");
    await waitFor(() =>
      expect(router.state.location.pathname).toBe(`${WS}/accounts`),
    );
    expect(screen.queryByRole("dialog")).toBeNull();

    await router.navigate(`${WS}/accounts/new`);
    const sheet = await screen.findByRole("dialog", { name: "New asset" });
    await user.click(within(sheet).getByRole("button", { name: "Close" }));
    await waitFor(() =>
      expect(router.state.location.pathname).toBe(`${WS}/accounts`),
    );
    accounts.release();
  });
});

describe("prefetch on intent", () => {
  it("hovering an account starts its detail, and the click reuses it", async () => {
    const account = held({ body: detail(CHECKING) });
    mockApi({
      ...shellApi(),
      [`GET ${API}/accounts/overview`]: { body: overview() },
      [`GET ${API}/accounts/${CHECKING.id}`]: account.handler,
    });
    const { user } = renderApp(`${WS}/accounts`);
    const link = await screen.findByRole("link", { name: "Checking" });
    expect(account.calls.count).toBe(0);

    await user.hover(link);
    expect(account.calls.count).toBe(1);
    account.release();
    await user.click(link);

    const sheet = await findSheet({ name: "Checking" });
    expect(
      within(sheet).getByRole("region", { name: "Retire" }),
    ).toBeInTheDocument();
    expect(account.calls.count).toBe(1);
  });

  it("hovering a tab starts its page's data", async () => {
    const flows = held({ body: SEED_MONTH });
    mockApi({
      ...shellApi(),
      [`GET ${API}/accounts/overview`]: { body: overview() },
      [`GET ${API}/cash-flows/overview`]: flows.handler,
    });
    const { user } = renderApp(`${WS}/accounts`);
    const nav = await screen.findByRole("navigation", { name: "Main" });
    await user.hover(within(nav).getByRole("link", { name: "Cash flows" }));
    expect(flows.calls.count).toBe(1);

    flows.release();
    await user.click(within(nav).getByRole("link", { name: "Cash flows" }));
    expect(await screen.findByText("Where income goes")).toBeInTheDocument();
    expect(flows.calls.count).toBe(1);
  });
});

describe("a write in flight", () => {
  it("shows on its button: a spinner, and disabled", async () => {
    const save = held({ body: { ...CHECKING, name: "Checking 2" } });
    mockApi({
      ...shellApi(),
      [`GET ${API}/accounts/overview`]: { body: overview() },
      [`GET ${API}/accounts/${CHECKING.id}`]: { body: detail(CHECKING) },
      [`PATCH ${API}/accounts/${CHECKING.id}`]: save.handler,
    });
    const { user, router } = renderApp(`${WS}/accounts/${CHECKING.id}/edit`);
    const sheet = await findSheet({ name: "Checking" });
    const button = within(sheet).getByRole("button", { name: "Save" });
    await user.click(button);

    await waitFor(() => expect(button).toHaveAttribute("aria-busy", "true"));
    expect(button).toBeDisabled();
    expect(button.querySelector("[data-slot=spinner]")).not.toBeNull();

    save.release();
    await waitFor(() =>
      expect(router.state.location.pathname).toBe(`${WS}/accounts`),
    );
  });
});

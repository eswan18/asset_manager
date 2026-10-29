import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Dashboard, DashboardCard } from "@/api/dashboard";
import { ME, mockApi, renderRoute, shellApi } from "@/test/utils";

const URL = "GET /api/workspaces/1/dashboard";

const RANGES: Dashboard["ranges"] = [
  { key: "6m", label: "6M" },
  { key: "1y", label: "1Y" },
  { key: "all", label: "All" },
];

const CARDS: DashboardCard[] = [
  {
    kind: "asset",
    title: "Assets",
    total: "13000.50",
    groups: [
      {
        key: "bank_accounts",
        label: "Bank Accounts",
        total: "3000.50",
        accounts: [
          { id: 1, name: "Checking", amount: "3000.50", computed: null },
        ],
      },
      {
        key: "uncategorized",
        label: "Uncategorized",
        total: "10000.00",
        accounts: [
          { id: 2, name: "Schwab", amount: "10000.00", computed: null },
          { id: 5, name: "New", amount: null, computed: null },
        ],
      },
    ],
  },
  {
    kind: "liability",
    title: "Liabilities",
    total: "450.00",
    groups: [
      {
        key: "tax_liability",
        label: "Tax Liability",
        total: "450.00",
        accounts: [
          {
            id: 4,
            name: "Tax",
            amount: "450.00",
            computed: "15% of gains, computed",
          },
        ],
      },
    ],
  },
];

function dashboard(overrides: Partial<Dashboard> = {}): Dashboard {
  return {
    has_data: true,
    can_edit: true,
    range: "1y",
    ranges: RANGES,
    net_worth: "12550.50",
    last_snapshot: "2026-10-24",
    change: { since: "2026-09-24", amount: "1500.25", percent: "13.9" },
    history: [
      {
        date: "2026-09-24",
        assets: "11500.00",
        liabilities: "400.00",
        net_worth: "11100.00",
      },
      {
        date: "2026-10-24",
        assets: "13000.50",
        liabilities: "450.00",
        net_worth: "12550.50",
      },
    ],
    categories: {
      asset: [
        {
          key: "uncategorized",
          label: "Uncategorized",
          amount: "10000.00",
          color: "var(--asset)",
        },
        {
          key: "bank_accounts",
          label: "Bank Accounts",
          amount: "3000.50",
          color: "var(--asset-2)",
        },
      ],
      liability: [
        {
          key: "tax_liability",
          label: "Tax Liability",
          amount: "450.00",
          color: "var(--liability)",
        },
      ],
    },
    bars: {
      asset: [
        {
          key: "uncategorized",
          label: "Uncategorized",
          color: "var(--asset)",
          share: "76.92",
        },
        {
          key: "bank_accounts",
          label: "Bank Accounts",
          color: "var(--asset-2)",
          share: "23.08",
        },
      ],
      liability: [
        {
          key: "tax_liability",
          label: "Tax Liability",
          color: "var(--liability)",
          share: "3.46",
        },
      ],
    },
    cards: CARDS,
    onboarding: null,
    ...overrides,
  };
}

const EMPTY_CARDS: DashboardCard[] = [
  {
    kind: "asset",
    title: "Assets",
    total: "0.00",
    groups: [],
    empty: "No assets yet.",
    add: { label: "+ Add an asset", path: "/accounts/new?type=asset" },
  },
  {
    kind: "liability",
    title: "Liabilities",
    total: "0.00",
    groups: [],
    empty: "No liabilities yet. That's fine; plenty of people have none.",
    add: { label: "+ Add a liability", path: "/accounts/new?type=liability" },
  },
];

function newWorkspace(overrides: Partial<Dashboard> = {}): Dashboard {
  return dashboard({
    has_data: false,
    net_worth: null,
    last_snapshot: null,
    change: null,
    history: [],
    categories: { asset: [], liability: [] },
    bars: { asset: [], liability: [] },
    cards: EMPTY_CARDS,
    onboarding: {
      steps: [
        {
          title: "Add your accounts",
          text: "Checking, savings, retirement, your home, loans, cards. Anything with a balance.",
          done: false,
          action: {
            label: "+ Add an account",
            path: "/accounts/new?type=asset",
          },
        },
        {
          title: "Enter today's balances",
          text: "Type each balance on Accounts and save. That's your first snapshot.",
          done: false,
          action: null,
        },
        {
          title: "Come back now and then",
          text: "Save again every week or month. The chart grows with each snapshot.",
          done: false,
          action: null,
        },
      ],
      has_accounts: false,
    },
    ...overrides,
  });
}

/** Two accounts added, no snapshot yet. */
function accountsNoSnapshot(canEdit = true): Dashboard {
  const base = newWorkspace();
  return {
    ...base,
    can_edit: canEdit,
    cards: [
      {
        ...EMPTY_CARDS[0],
        total: null,
        groups: [
          {
            key: "uncategorized",
            label: "Uncategorized",
            total: "0.00",
            accounts: [
              { id: 1, name: "Cash", amount: null, computed: null },
              { id: 2, name: "Brokerage", amount: null, computed: null },
            ],
          },
        ],
      },
      EMPTY_CARDS[1],
    ],
    onboarding: {
      steps: [
        {
          ...base.onboarding!.steps[0],
          text: "Done: 2 accounts added. Add more any time.",
          done: true,
          action: null,
        },
        {
          ...base.onboarding!.steps[1],
          action: { label: "Enter balances", path: "/accounts" },
        },
        base.onboarding!.steps[2],
      ],
      has_accounts: true,
    },
  };
}

const VIEWER = {
  ...ME,
  workspaces: [{ id: 1, name: "Household", role: "viewer" as const }],
};

function region(name: string) {
  return screen.getByRole("region", { name });
}

describe("the dashboard", () => {
  it("shows net worth, its change and the last snapshot", async () => {
    mockApi({ ...shellApi(), [URL]: { body: dashboard() } });
    renderRoute("/workspaces/1");

    const overview = await screen.findByRole("region", { name: "Net worth" });
    expect(overview).toHaveTextContent("Net worth$12,551");
    expect(overview).toHaveTextContent("+$1,500 (+13.9%) since Sep 24");
    expect(overview).toHaveTextContent("Last snapshot Oct 24, 2026");
    expect(
      within(overview).getByRole("link", { name: "Update balances" }),
    ).toHaveAttribute("href", "/workspaces/1/accounts");
    expect(
      await within(overview).findByRole("img", { name: /^Assets, net worth/ }),
    ).toBeInTheDocument();
    expect(document.title).toBe("Household · Sensibility");
  });

  it("gives the change no percent when the earlier net worth was zero, and a year when it was another year", async () => {
    mockApi({
      ...shellApi(),
      [URL]: {
        body: dashboard({
          change: { since: "2025-10-20", amount: "-1200.00", percent: null },
        }),
      },
    });
    renderRoute("/workspaces/1");
    const overview = await screen.findByRole("region", { name: "Net worth" });
    expect(overview).toHaveTextContent("−$1,200 since Oct 20, 2025");
    expect(overview).not.toHaveTextContent("%");
  });

  it("has no change line with one snapshot", async () => {
    mockApi({ ...shellApi(), [URL]: { body: dashboard({ change: null }) } });
    renderRoute("/workspaces/1");
    const overview = await screen.findByRole("region", { name: "Net worth" });
    expect(overview).not.toHaveTextContent("since");
  });

  it("keys the lines and the categories, with the phone's bars", async () => {
    mockApi({ ...shellApi(), [URL]: { body: dashboard() } });
    renderRoute("/workspaces/1");
    await screen.findByRole("region", { name: "Net worth" });

    const assets = document.querySelector("[data-key-group=asset]")!;
    expect(assets).toHaveTextContent(
      "AssetsUncategorized $10,000Bank Accounts $3,001",
    );
    expect(
      document.querySelector("[data-key-group=liability]"),
    ).toHaveTextContent("LiabilitiesTax Liability $450");
    // The bars, in the categories' order and colors, sized by share.
    const bar = document.querySelector("[data-category-bar=asset]")!;
    expect(bar).toHaveAttribute("aria-hidden", "true");
    const segments = bar.querySelectorAll<HTMLElement>("[data-bar-segment]");
    expect([...segments].map((s) => s.title)).toEqual([
      "Uncategorized",
      "Bank Accounts",
    ]);
    expect(segments[0].style.width).toBe("76.92%");
    expect(segments[0].style.background).toBe("var(--asset)");
  });

  it("lists the accounts under their categories", async () => {
    mockApi({ ...shellApi(), [URL]: { body: dashboard() } });
    renderRoute("/workspaces/1");

    const assets = (
      await screen.findByRole("heading", { level: 2, name: "Assets" })
    ).closest("section")!;
    expect(assets).toHaveTextContent(
      "Assets$13,001Bank Accounts$3,001Checking$3,001Uncategorized$10,000Schwab$10,000New—",
    );
    const liabilities = screen
      .getByRole("heading", { level: 2, name: "Liabilities" })
      .closest("section")!;
    expect(
      within(liabilities).getByText("15% of gains, computed"),
    ).toHaveAttribute("data-slot", "tag");
  });

  it("says a card with no active accounts has none", async () => {
    mockApi({
      ...shellApi(),
      [URL]: {
        body: dashboard({
          cards: [
            CARDS[0],
            {
              kind: "liability",
              title: "Liabilities",
              total: "0.00",
              groups: [],
            },
          ],
        }),
      },
    });
    renderRoute("/workspaces/1");
    expect(
      await screen.findByText("No active liabilities."),
    ).toBeInTheDocument();
  });

  it("asks for the range in the URL, and a year by default", async () => {
    const fetchMock = mockApi({ ...shellApi(), [URL]: { body: dashboard() } });
    renderRoute("/workspaces/1?range=all");
    await screen.findByRole("region", { name: "Net worth" });
    const asked = fetchMock.mock.calls
      .map(([url]) => String(url))
      .filter((url) => url.includes("/dashboard"));
    expect(asked).toEqual(["/api/workspaces/1/dashboard?range=all"]);
    expect(screen.getByRole("radio", { name: "All" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  it("treats an unknown range as a year", async () => {
    const fetchMock = mockApi({ ...shellApi(), [URL]: { body: dashboard() } });
    renderRoute("/workspaces/1?range=decade");
    await screen.findByRole("region", { name: "Net worth" });
    expect(String(fetchMock.mock.calls.at(-1)![0])).toBe(
      "/api/workspaces/1/dashboard?range=1y",
    );
    expect(screen.getByRole("radio", { name: "1Y" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  it("changes the range in the URL, keeping the numbers until the new ones arrive", async () => {
    let release: () => void = () => {};
    const sixMonths = new Promise<void>((resolve) => (release = resolve));
    mockApi({
      ...shellApi(),
      [URL]: async ({ url }) => {
        if (url.searchParams.get("range") === "6m") {
          await sixMonths;
          return { body: dashboard({ range: "6m", net_worth: "99.00" }) };
        }
        return { body: dashboard() };
      },
    });
    const { router, user } = renderRoute("/workspaces/1");
    await screen.findByRole("region", { name: "Net worth" });

    await user.click(screen.getByRole("radio", { name: "6M" }));
    expect(router.state.location.search).toBe("?range=6m");
    expect(screen.getByRole("radio", { name: "6M" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    // Still the year's figure while the six months load.
    expect(region("Net worth")).toHaveTextContent("$12,551");

    release();
    await waitFor(() =>
      expect(region("Net worth")).toHaveTextContent("Net worth$99"),
    );
  });

  it("says so when the data won't load", async () => {
    mockApi({
      ...shellApi(),
      [URL]: { status: 500, body: { error: "boom" } },
    });
    renderRoute("/workspaces/1");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "An error occurred while loading your data. Please try again later.",
    );
  });
});

describe("the getting-started dashboard", () => {
  it("offers an editor the first step, and Cash flows", async () => {
    mockApi({ ...shellApi(), [URL]: { body: newWorkspace() } });
    renderRoute("/workspaces/1");

    const welcome = await screen.findByRole("region", {
      name: "Let's get your first net worth on the board.",
    });
    expect(welcome).toHaveTextContent("Household is new");
    const steps = within(welcome).getAllByRole("listitem");
    expect(steps.map((s) => s.textContent)).toEqual([
      expect.stringMatching(/^1Add your accounts/),
      expect.stringMatching(/^2Enter today's balances/),
      expect.stringMatching(/^3Come back now and then/),
    ]);
    const links = within(screen.getByRole("main"))
      .getAllByRole("link")
      .filter((a) => a.getAttribute("href")?.includes("/accounts"));
    // Step 1 is the only way to add one: no empty cards until there are
    // accounts to list.
    expect(links.map((a) => [a.textContent, a.getAttribute("href")])).toEqual([
      ["+ Add an account", "/workspaces/1/accounts/new?type=asset"],
    ]);
    expect(
      screen.queryByRole("heading", { level: 2, name: "Assets" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("No assets yet.")).not.toBeInTheDocument();
    expect(
      within(welcome).getByText(/^Optional: add your income and expenses on/),
    ).toHaveTextContent(
      "Optional: add your income and expenses on Cash flows.",
    );
    expect(
      within(welcome).getByRole("link", { name: "Cash flows" }),
    ).toHaveAttribute("href", "/workspaces/1/cash-flows");
    expect(screen.queryByText(/editor/)).not.toBeInTheDocument();
    // No chart: a placeholder, hidden from screen readers.
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(
      screen.getByText("Your first snapshot starts the line.").parentElement,
    ).toHaveAttribute("aria-hidden", "true");
  });

  it("sends an editor with accounts to enter balances", async () => {
    mockApi({ ...shellApi(), [URL]: { body: accountsNoSnapshot() } });
    renderRoute("/workspaces/1");

    const welcome = await screen.findByRole("region", {
      name: /^Let's get your first/,
    });
    const [first] = within(welcome).getAllByRole("listitem");
    expect(first).toHaveTextContent(
      "✓Add your accountsDone: 2 accounts added.",
    );
    expect(first).toHaveAttribute("data-done", "true");
    expect(
      within(welcome).getByRole("link", { name: "Enter balances" }),
    ).toHaveAttribute("href", "/workspaces/1/accounts");
    expect(
      within(welcome).queryByRole("link", { name: "+ Add an account" }),
    ).not.toBeInTheDocument();
    // The accounts show, with no amounts; liabilities can still be added.
    const assets = screen
      .getByRole("heading", { level: 2, name: "Assets" })
      .closest("section")!;
    expect(assets).toHaveTextContent("Assets—UncategorizedCash—Brokerage—");
    expect(
      screen.getByRole("link", { name: "+ Add a liability" }),
    ).toBeInTheDocument();
  });

  it.each([
    [
      newWorkspace({ can_edit: false }),
      "An editor hasn't added any accounts yet.",
    ],
    [accountsNoSnapshot(false), "An editor hasn't entered any balances yet."],
  ])("tells a viewer an editor hasn't started", async (body, note) => {
    mockApi({ ...shellApi(VIEWER), [URL]: { body } });
    renderRoute("/workspaces/1");
    expect(await screen.findByText(note)).toBeInTheDocument();
    expect(screen.queryByText(/^Optional:/)).not.toBeInTheDocument();
    expect(
      within(screen.getByRole("main"))
        .queryAllByRole("link")
        .filter((a) => a.getAttribute("href")?.includes("/accounts")),
    ).toEqual([]);
  });
});

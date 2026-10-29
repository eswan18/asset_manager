import { screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { ME, mockApi, renderRoute, shellApi } from "@/test/utils";

import { CHECKING, EMPTY, overview, TAX } from "./accounts.fixtures";

const PAGE = "/workspaces/1/accounts";
const OVERVIEW = "GET /api/workspaces/1/accounts/overview";
const STORAGE_KEY = "sensibility:staged-edits";

const VIEWER = {
  ...ME,
  workspaces: [{ id: 1, name: "Household", role: "viewer" as const }],
};

beforeEach(() => sessionStorage.clear());
afterEach(() => sessionStorage.clear());

function open(data = overview(), extra = {}, me = ME) {
  const fetchMock = mockApi({
    ...shellApi(me),
    [OVERVIEW]: { body: data },
    ...extra,
  });
  return { ...renderRoute(PAGE), fetchMock };
}

const bar = () => screen.getByRole("region", { name: "Save snapshot" });
const status = () => bar().querySelector("[data-status]")!;
const netWorth = () => bar().querySelector("[data-net-worth]")!;
const netChange = () => bar().querySelector("[data-net-change]");
const total = (kind: string) =>
  document.querySelector(`[data-section=${kind}] [data-slot=card-total]`)!;
const row = (id: number) =>
  document.querySelector<HTMLElement>(`[data-account-id="${id}"]`)!;
const taxAmount = () => row(TAX.id).querySelector("[data-computed-amount]")!;
const staged = () => JSON.parse(sessionStorage.getItem(STORAGE_KEY) || "{}");

describe("the Accounts page", () => {
  it("shows every active account with its amount, and the save bar", async () => {
    const { fetchMock } = open();
    expect(
      await screen.findByRole("heading", { level: 1, name: "Accounts" }),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Saving writes today's snapshot, Oct 28, 2026. Last saved Sep 27.",
      ),
    ).toBeInTheDocument();
    // Always with the retired accounts: Show retired is the page's toggle.
    expect(String(fetchMock.mock.calls.at(-1)![0])).toContain("retired=true");

    expect(screen.getByLabelText("Amount for Checking")).toHaveValue(
      "1,000.00",
    );
    expect(screen.getByLabelText("Amount for Checking")).toHaveAttribute(
      "inputmode",
      "decimal",
    );
    expect(screen.getByRole("link", { name: "Checking" })).toHaveAttribute(
      "href",
      "/workspaces/1/accounts/1/edit",
    );
    expect(total("asset")).toHaveTextContent("$180,265.00");
    expect(total("liability")).toHaveTextContent("$15,031.74");
    expect(screen.getByText("Bank Accounts").parentElement).toHaveTextContent(
      "$1,000.00",
    );

    // The computed row: its formula, the basis field, the live value.
    expect(row(TAX.id)).toHaveTextContent("15% × (Schwab − basis)");
    expect(screen.getByLabelText("Cost basis for Cap gains tax")).toHaveValue(
      "82,386.74",
    );
    expect(taxAmount()).toHaveTextContent("$14,531.74");
    expect(row(TAX.id)).toHaveTextContent("computed");

    expect(status()).toHaveTextContent("No unsaved changes");
    expect(netWorth()).toHaveTextContent("$165,233.26");
    expect(netChange()).toBeNull();
    expect(
      screen
        .getAllByRole("link", { name: "+ Add" })
        .map((a) => a.getAttribute("href")),
    ).toEqual([
      "/workspaces/1/accounts/new?type=asset",
      "/workspaces/1/accounts/new?type=liability",
    ]);
    expect(document.title).toBe("Household · Sensibility");
  });

  it("says when nothing is saved yet, or today's would be replaced", async () => {
    open(overview({ last_saved: null }));
    expect(
      await screen.findByText(
        "Saving writes today's snapshot, Oct 28, 2026. Nothing saved yet.",
      ),
    ).toBeInTheDocument();
  });

  it("shows retired accounts only when asked", async () => {
    const { user } = open();
    await screen.findByLabelText("Amount for Checking");
    expect(screen.queryByText("Old savings")).not.toBeInTheDocument();
    await user.click(screen.getByLabelText("Show retired (1)"));
    const old = screen.getByRole("link", { name: "Old savings" });
    expect(old).toHaveClass("line-through");
    expect(old.closest("[data-account-id]")).toHaveTextContent(
      "Retired Sep 1, 2026",
    );
    // A retired account has no field.
    expect(screen.queryByLabelText("Amount for Old savings")).toBeNull();
  });

  it("hides a group whose accounts are all retired", async () => {
    const data = overview();
    data.sections[0].groups.push({
      key: "uncategorized",
      label: "Uncategorized",
      subtotal: "0.00",
      retired: true,
      accounts: [
        { ...CHECKING, id: 9, name: "Gone", retired_at: "2026-01-02" },
      ],
    });
    const { user } = open(data);
    await screen.findByLabelText("Amount for Checking");
    expect(screen.queryByText("Uncategorized")).not.toBeInTheDocument();
    await user.click(screen.getByLabelText("Show retired (1)"));
    expect(screen.getByText("Uncategorized")).toBeInTheDocument();
  });

  it("counts a retired account's saved amount in no total", async () => {
    const data = overview();
    data.sections[0].groups[0].accounts[1] = {
      ...data.sections[0].groups[0].accounts[1],
      amount: "5000.00",
    };
    const { user } = open(data);
    await screen.findByLabelText("Amount for Checking");
    expect(netWorth()).toHaveTextContent("$165,233.26");
    expect(total("asset")).toHaveTextContent("$180,265.00");
    expect(status()).toHaveTextContent("No unsaved changes");
    await user.click(screen.getByLabelText("Show retired (1)"));
    expect(screen.queryByLabelText("Amount for Old savings")).toBeNull();
    expect(netWorth()).toHaveTextContent("$165,233.26");
  });

  it("has no Show retired without retired accounts", async () => {
    open(overview({ retired_count: 0 }));
    await screen.findByLabelText("Amount for Checking");
    expect(screen.queryByLabelText(/Show retired/)).not.toBeInTheDocument();
  });

  it("shows the error when the page can't load", async () => {
    open(overview(), { [OVERVIEW]: { status: 500, body: { error: "boom" } } });
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "An error occurred while loading your data. Please try again later.",
    );
  });
});

describe("staged edits", () => {
  it("stage, count, show was $X and move every total", async () => {
    const { user } = open();
    const checking = await screen.findByLabelText("Amount for Checking");
    expect(row(CHECKING.id)).not.toHaveTextContent("was");

    await user.clear(checking);
    await user.type(checking, "1500");
    expect(checking).toHaveAttribute("data-edited");
    expect(status()).toHaveTextContent("1 unsaved change");
    expect(netWorth()).toHaveTextContent("$165,733.26");
    expect(netChange()).toHaveTextContent("(+$500.00)");
    expect(row(CHECKING.id)).toHaveTextContent("was $1,000.00");
    expect(total("asset")).toHaveTextContent("$180,765.00");
    expect(screen.getByText("Bank Accounts").parentElement).toHaveTextContent(
      "$1,500.00",
    );
    expect(staged()).toEqual({ "amount:1": "1500" });

    // Leaving the field formats it; it is still the same edit.
    await user.tab();
    expect(checking).toHaveValue("1,500.00");
    expect(status()).toHaveTextContent("1 unsaved change");

    // A second edit counts separately; undoing it by hand uncounts it.
    const card = screen.getByLabelText("Amount for Card");
    await user.clear(card);
    await user.type(card, "750");
    expect(status()).toHaveTextContent("2 unsaved changes");
    expect(netWorth()).toHaveTextContent("$165,483.26");
    await user.clear(card);
    await user.type(card, "500.00");
    expect(status()).toHaveTextContent("1 unsaved change");
    expect(card).not.toHaveAttribute("data-edited");
    expect(staged()).toEqual({ "amount:1": "1,500.00" });
  });

  it("says was nothing yet for an account with no saved amount", async () => {
    const data = overview();
    data.sections[0].groups[0].accounts.push({
      ...CHECKING,
      id: 9,
      name: "Brand New",
      amount: null,
    });
    const { user } = open(data);
    const field = await screen.findByLabelText("Amount for Brand New");
    await user.type(field, "5");
    expect(row(9)).toHaveTextContent("was nothing yet");
  });

  it("recomputes a computed account from its input and basis", async () => {
    const { user } = open();
    const schwab = await screen.findByLabelText("Amount for Schwab");
    await user.clear(schwab);
    await user.type(schwab, "200000");
    // 0.15 × (200,000 − 82,386.74) = 17,641.989
    expect(taxAmount()).toHaveTextContent("$17,641.99");
    expect(taxAmount()).toHaveAttribute("data-edited");
    expect(row(TAX.id)).toHaveTextContent("was $14,531.74");
    expect(total("liability")).toHaveTextContent("$18,141.99");

    const basis = screen.getByLabelText("Cost basis for Cap gains tax");
    await user.clear(basis);
    await user.type(basis, "100,000");
    expect(taxAmount()).toHaveTextContent("$15,000.00");
    await user.clear(basis);
    await user.type(basis, "(1,000)");
    expect(taxAmount()).toHaveTextContent("$30,150.00");
    await user.clear(basis);
    await user.type(basis, "abc");
    expect(taxAmount()).toHaveTextContent("—");
    expect(basis).toHaveAttribute("aria-invalid", "true");
    await user.clear(basis);
    expect(taxAmount()).toHaveTextContent("$30,000.00");
    expect(netWorth()).toHaveTextContent("$170,500.00");
    expect(status()).toHaveTextContent("2 unsaved changes");
  });

  it("discards back to the page as loaded", async () => {
    const { user } = open();
    const checking = await screen.findByLabelText("Amount for Checking");
    await user.clear(checking);
    await user.type(checking, "1500");
    await user.clear(screen.getByLabelText("Cost basis for Cap gains tax"));
    expect(status()).toHaveTextContent("2 unsaved changes");

    await user.click(screen.getByRole("button", { name: "Discard" }));
    expect(checking).toHaveValue("1,000.00");
    expect(checking).not.toHaveAttribute("data-edited");
    expect(status()).toHaveTextContent("No unsaved changes");
    expect(netWorth()).toHaveTextContent("$165,233.26");
    expect(netChange()).toBeNull();
    expect(taxAmount()).toHaveTextContent("$14,531.74");
    expect(sessionStorage.getItem(STORAGE_KEY)).toBeNull();
  });

  it("comes back from sessionStorage", async () => {
    sessionStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({ "amount:1": "1,500.00", "amount:99": "5" }),
    );
    open();
    const checking = await screen.findByLabelText("Amount for Checking");
    expect(checking).toHaveValue("1,500.00");
    expect(checking).toHaveAttribute("data-edited");
    expect(status()).toHaveTextContent("1 unsaved change");
    expect(netWorth()).toHaveTextContent("$165,733.26");
  });
});

describe("saving", () => {
  it("posts every amount and basis, flashes, and starts clean", async () => {
    let saved = false;
    const { user, fetchMock } = open(overview(), {
      [OVERVIEW]: () => ({
        body: saved
          ? overview({
              last_saved: "2026-10-28",
              snapshot_is_today: true,
              sections: overview().sections.map((s) => ({
                ...s,
                groups: s.groups.map((g) => ({
                  ...g,
                  accounts: g.accounts.map((a) =>
                    a.id === 1 ? { ...a, amount: "1234.50" } : a,
                  ),
                })),
              })),
            })
          : overview(),
      }),
      "POST /api/workspaces/1/snapshots": () => {
        saved = true;
        return {
          body: {
            date: "2026-10-28",
            count: 4,
            accounts: [
              { id: 1, type: "asset", amount: "1234.50", source: "updated" },
              { id: 2, type: "asset", amount: "179265.00", source: "updated" },
              { id: 3, type: "liability", amount: "500.00", source: "updated" },
              {
                id: 4,
                type: "liability",
                amount: "14531.74",
                source: "computed",
              },
            ],
          },
        };
      },
    });
    const checking = await screen.findByLabelText("Amount for Checking");
    await user.clear(checking);
    await user.type(checking, "1234.5");
    await user.click(screen.getByRole("button", { name: "Save snapshot" }));

    expect(
      await screen.findByText(
        "Saved today's snapshot: 4 accounts, net worth $165,468.",
      ),
    ).toBeInTheDocument();
    const post = fetchMock.mock.calls.find(
      ([url, init]) =>
        String(url).endsWith("/snapshots") && init?.method === "POST",
    )!;
    // Clicking Save left the field, which tidied it to "1,234.50".
    expect(JSON.parse(String(post[1]!.body))).toEqual({
      values: { 1: "1234.50", 2: "179265.00", 3: "500.00" },
      cost_bases: { 4: "82386.74" },
    });
    const headers = post[1]!.headers as Record<string, string>;
    expect(headers["X-Requested-With"]).toBe("sensibility");
    expect(headers["X-Timezone"]).toBeTruthy();

    await waitFor(() =>
      expect(status()).toHaveTextContent("No unsaved changes"),
    );
    expect(screen.getByLabelText("Amount for Checking")).toHaveValue(
      "1,234.50",
    );
    expect(sessionStorage.getItem(STORAGE_KEY)).toBeNull();
    expect(
      screen.getByText(/Last saved today; saving again replaces it\./),
    ).toBeInTheDocument();
  });

  it("asks before replacing today's snapshot", async () => {
    let posts = 0;
    const { user } = open(overview({ snapshot_is_today: true }), {
      "POST /api/workspaces/1/snapshots": () => {
        posts += 1;
        return { body: { date: "2026-10-28", count: 1, accounts: [] } };
      },
    });
    const checking = await screen.findByLabelText("Amount for Checking");
    await user.clear(checking);
    await user.type(checking, "3000");
    await user.click(screen.getByRole("button", { name: "Save snapshot" }));
    expect(status()).toHaveTextContent(
      "Today's snapshot already exists. Saving again replaces it.",
    );
    expect(posts).toBe(0);
    await user.click(
      screen.getByRole("button", { name: "Overwrite today's snapshot" }),
    );
    await screen.findByText(/Saved today's snapshot: 1 account,/);
    expect(posts).toBe(1);
  });

  it("Discard disarms the overwrite", async () => {
    const { user } = open(overview({ snapshot_is_today: true }));
    await screen.findByLabelText("Amount for Checking");
    await user.click(screen.getByRole("button", { name: "Save snapshot" }));
    expect(
      screen.getByRole("button", { name: "Overwrite today's snapshot" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Discard" }));
    expect(
      screen.getByRole("button", { name: "Save snapshot" }),
    ).toBeInTheDocument();
    expect(status()).toHaveTextContent("No unsaved changes");
  });

  it("won't save with an amount missing", async () => {
    const { user } = open();
    const checking = await screen.findByLabelText("Amount for Checking");
    await user.clear(checking);
    await user.click(screen.getByRole("button", { name: "Save snapshot" }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Every account needs an amount before saving.",
    );
    expect(checking).toHaveAttribute("aria-invalid", "true");
    expect(checking).toHaveFocus();
    // A blank basis is fine: zero.
    expect(
      screen.getByLabelText("Cost basis for Cap gains tax"),
    ).not.toHaveAttribute("aria-invalid");
  });

  it("names a field that isn't a number", async () => {
    const { user } = open();
    const card = await screen.findByLabelText("Amount for Card");
    await user.clear(card);
    await user.type(card, "lots");
    expect(card).toHaveAttribute("aria-invalid", "true");
    await user.click(screen.getByRole("button", { name: "Save snapshot" }));
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Amount for Card isn't a number.",
    );
    expect(card).toHaveFocus();
  });

  it("shows the server's refusal and keeps the edits", async () => {
    const { user } = open(overview(), {
      "POST /api/workspaces/1/snapshots": {
        status: 400,
        body: { error: "Checking is too large" },
      },
    });
    const checking = await screen.findByLabelText("Amount for Checking");
    await user.clear(checking);
    await user.type(checking, "1500");
    await user.click(screen.getByRole("button", { name: "Save snapshot" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Checking is too large",
    );
    expect(checking).toHaveValue("1,500.00");
    expect(checking).not.toBeDisabled();
    expect(status()).toHaveTextContent("1 unsaved change");
  });
});

describe("roles and empty states", () => {
  it("gives a viewer no + Add, read-only amounts and no save bar", async () => {
    open(overview({ can_edit: false }), {}, VIEWER);
    expect(await screen.findByLabelText("Amount for Checking")).toHaveAttribute(
      "readonly",
    );
    expect(screen.queryByRole("link", { name: "+ Add" })).toBeNull();
    expect(
      screen.queryByRole("region", { name: "Save snapshot" }),
    ).not.toBeInTheDocument();
  });

  it("offers the first account to an editor", async () => {
    open(EMPTY);
    expect(
      await screen.findByRole("heading", { name: "No accounts yet" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "+ Add an account" }),
    ).toHaveAttribute("href", "/workspaces/1/accounts/new?type=asset");
    expect(
      screen.queryByRole("region", { name: "Save snapshot" }),
    ).not.toBeInTheDocument();
  });

  it("tells a viewer an editor hasn't added any", async () => {
    open({ ...EMPTY, can_edit: false }, {}, VIEWER);
    const card = (
      await screen.findByRole("heading", { name: "No accounts yet" })
    ).parentElement!;
    expect(
      within(card).getByText("An editor hasn't added any accounts yet."),
    ).toBeInTheDocument();
    expect(within(card).queryByRole("link")).toBeNull();
  });
});

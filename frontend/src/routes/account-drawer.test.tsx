import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { AccountOut } from "@/api/accounts";
import {
  ME,
  mockApi,
  renderRoute,
  shellApi,
  type FakeResponse,
} from "@/test/utils";

import {
  CARD,
  CHECKING,
  detail,
  OLD,
  overview,
  SCHWAB,
  TAX,
} from "./accounts.fixtures";

const ACCOUNTS = "/workspaces/1/accounts";
const API = "/api/workspaces/1/accounts";

const VIEWER = {
  ...ME,
  workspaces: [{ id: 1, name: "Household", role: "viewer" as const }],
};

type Handlers = Parameters<typeof mockApi>[0];

function open(path: string, extra: Handlers = {}, me = ME) {
  const fetchMock = mockApi({
    ...shellApi(me),
    [`GET ${API}/overview`]: { body: overview() },
    ...extra,
  });
  return { ...renderRoute(path), fetchMock };
}

/** `GET .../accounts/{id}` for these accounts. */
function details(
  ...accounts: [AccountOut, Partial<ReturnType<typeof detail>>?][]
) {
  return Object.fromEntries(
    accounts.map(([a, overrides]) => [
      `GET ${API}/${a.id}`,
      { body: detail(a, overrides) } as FakeResponse,
    ]),
  );
}

function lastCall(fetchMock: ReturnType<typeof mockApi>, method: string) {
  const call = fetchMock.mock.calls
    .filter(([, init]) => init?.method === method)
    .at(-1)!;
  return {
    url: String(call[0]),
    body: JSON.parse(String(call[1]!.body ?? "null")),
    headers: call[1]!.headers as Record<string, string>,
  };
}

describe("the new account drawer", () => {
  it("is a new asset by default, with the name focused", async () => {
    open(`${ACCOUNTS}/new`);
    const dialog = await screen.findByRole("dialog", { name: "New asset" });
    expect(dialog).toHaveTextContent("New account");
    expect(within(dialog).getByLabelText("Name")).toHaveFocus();
    expect(within(dialog).getByLabelText("Asset")).toBeChecked();
    expect(within(dialog).getByLabelText("Category")).toHaveValue("");
    expect(
      within(dialog).getByLabelText("Computed from other accounts"),
    ).not.toBeChecked();
    expect(within(dialog).queryByLabelText("Rate (%)")).toBeNull();
    // No history and no retire for an account that doesn't exist yet.
    expect(dialog).not.toHaveTextContent("History");
    expect(within(dialog).queryByRole("region", { name: "Retire" })).toBeNull();
    // The page behind stays.
    expect(
      screen.getByRole("heading", { name: "Accounts", hidden: true }),
    ).toBeInTheDocument();
    expect(document.title).toBe("New account · Household · Sensibility");
  });

  it("takes the type from the link, and the type switch retitles it", async () => {
    const { user } = open(`${ACCOUNTS}/new?type=liability`);
    const dialog = await screen.findByRole("dialog", { name: "New liability" });
    expect(within(dialog).getByLabelText("Liability")).toBeChecked();
    await user.click(within(dialog).getByLabelText("Asset"));
    expect(
      screen.getByRole("dialog", { name: "New asset" }),
    ).toBeInTheDocument();
  });

  it("falls back to an asset for an unknown type", async () => {
    open(`${ACCOUNTS}/new?type=boat`);
    expect(
      await screen.findByRole("dialog", { name: "New asset" }),
    ).toBeInTheDocument();
  });

  it("lists plain, active accounts as inputs, under their type", async () => {
    const { user } = open(`${ACCOUNTS}/new`);
    const dialog = await screen.findByRole("dialog");
    await user.click(
      within(dialog).getByLabelText("Computed from other accounts"),
    );
    const inputs = within(dialog).getByRole("group", { name: "Inputs" });
    expect(inputs).toHaveTextContent(
      ["Inputs", "Assets", "Checking", "Schwab", "Liabilities", "Card"].join(
        "",
      ),
    );
    // Not a computed account, not a retired one.
    expect(within(inputs).queryByLabelText(TAX.name)).toBeNull();
    expect(within(inputs).queryByLabelText(OLD.name)).toBeNull();
    await user.click(
      within(dialog).getByLabelText("Computed from other accounts"),
    );
    expect(within(dialog).queryByRole("group", { name: "Inputs" })).toBeNull();
  });

  it("needs no subheading with one type of input, and says when there are none", async () => {
    const one = overview();
    one.sections[1].groups = [];
    const { user } = open(`${ACCOUNTS}/new`, {
      [`GET ${API}/overview`]: { body: one },
    });
    const dialog = await screen.findByRole("dialog");
    await user.click(
      within(dialog).getByLabelText("Computed from other accounts"),
    );
    expect(
      within(dialog).getByRole("group", { name: "Inputs" }),
    ).not.toHaveTextContent("Assets");
  });

  it("says when there's nothing to use as an input", async () => {
    const none = overview();
    none.sections = none.sections.map((s) => ({ ...s, groups: [] }));
    const { user } = open(`${ACCOUNTS}/new`, {
      [`GET ${API}/overview`]: { body: none },
    });
    const dialog = await screen.findByRole("dialog");
    await user.click(
      within(dialog).getByLabelText("Computed from other accounts"),
    );
    expect(dialog).toHaveTextContent(
      "No plain, active accounts to use as inputs yet.",
    );
  });

  it("shows the computed value as the fields change", async () => {
    const { user } = open(`${ACCOUNTS}/new`);
    const dialog = await screen.findByRole("dialog");
    await user.click(
      within(dialog).getByLabelText("Computed from other accounts"),
    );
    const line = dialog.querySelector("[data-formula-preview]")!;
    expect(line).toHaveTextContent("rate × (sum of inputs − cost basis)—");
    await user.type(within(dialog).getByLabelText("Rate (%)"), "20");
    await user.click(within(dialog).getByLabelText("Schwab"));
    expect(line).toHaveTextContent("20% × ($179,265 − $0)$35,853.00");
    await user.type(
      within(dialog).getByLabelText("Cost basis ($)"),
      "$1,000.005",
    );
    expect(line).toHaveTextContent("$35,653.00");
    await user.click(within(dialog).getByLabelText("Checking"));
    expect(line).toHaveTextContent("20% × ($180,265 − $1,000)");
    await user.clear(within(dialog).getByLabelText("Rate (%)"));
    await user.type(within(dialog).getByLabelText("Rate (%)"), "abc");
    expect(line).toHaveTextContent("rate × (sum of inputs − cost basis)—");
  });

  it("creates the account, flashes and goes back to the page", async () => {
    const { user, router, fetchMock } = open(`${ACCOUNTS}/new`, {
      [`POST ${API}`]: {
        status: 201,
        body: {
          ...CARD,
          id: 9,
          name: "Brokerage",
          type: "asset",
          amount: null,
        },
      },
    });
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Name"), "Brokerage");
    await user.selectOptions(
      within(dialog).getByLabelText("Category"),
      "Investment Accounts",
    );
    await user.click(within(dialog).getByRole("button", { name: "Save" }));

    expect(
      await screen.findByText("Added Brokerage to assets."),
    ).toBeInTheDocument();
    await waitFor(() => expect(router.state.location.pathname).toBe(ACCOUNTS));
    const post = lastCall(fetchMock, "POST");
    expect(post.url).toBe(API);
    expect(post.body).toEqual({
      name: "Brokerage",
      type: "asset",
      category: "investment_accounts",
      formula: null,
    });
    expect(post.headers["X-Requested-With"]).toBe("sensibility");
  });

  it("creates a computed account with its formula as typed", async () => {
    const { user, fetchMock } = open(`${ACCOUNTS}/new?type=liability`, {
      [`POST ${API}`]: { status: 201, body: { ...TAX, id: 9 } },
    });
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Name"), "Tax");
    await user.click(
      within(dialog).getByLabelText("Computed from other accounts"),
    );
    await user.type(within(dialog).getByLabelText("Rate (%)"), "15");
    await user.type(within(dialog).getByLabelText("Cost basis ($)"), "1,000");
    // Checked out of order; sent in page order.
    await user.click(within(dialog).getByLabelText("Schwab"));
    await user.click(within(dialog).getByLabelText("Checking"));
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    await screen.findByText("Added Cap gains tax to liabilities.");
    expect(lastCall(fetchMock, "POST").body).toEqual({
      name: "Tax",
      type: "liability",
      category: null,
      formula: { rate_percent: "15", cost_basis: "1,000", input_ids: [1, 2] },
    });
  });

  it("shows the service's refusal in the drawer, keeping what was typed", async () => {
    const { user, router } = open(`${ACCOUNTS}/new`, {
      [`POST ${API}`]: {
        status: 400,
        body: { error: "A asset named 'Checking' already exists" },
      },
    });
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Name"), "Checking");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "A asset named 'Checking' already exists",
    );
    expect(within(dialog).getByLabelText("Name")).toHaveValue("Checking");
    expect(router.state.location.pathname).toBe(`${ACCOUNTS}/new`);
  });

  it("is editor-only", async () => {
    open(`${ACCOUNTS}/new`, {}, VIEWER);
    const dialog = await screen.findByRole("dialog", { name: "New account" });
    expect(within(dialog).getByRole("alert")).toHaveTextContent(
      "This needs the editor role or higher",
    );
    expect(within(dialog).queryByLabelText("Name")).toBeNull();
  });

  it("closes on Cancel and Escape", async () => {
    const { user, router } = open(`${ACCOUNTS}/new`);
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(router.state.location.pathname).toBe(ACCOUNTS);
    await router.navigate(`${ACCOUNTS}/new`);
    await screen.findByRole("dialog");
    await user.keyboard("{Escape}");
    await waitFor(() => expect(router.state.location.pathname).toBe(ACCOUNTS));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("the edit drawer", () => {
  it("shows a computed account: formula, live line, history, retire warning", async () => {
    open(`${ACCOUNTS}/${TAX.id}/edit`, {
      ...details([
        TAX,
        {
          retire_warning:
            "Last saved at $14,531.74 on September 27, 2026. Retiring stops counting it from the next snapshot on. History is kept.",
          history: [
            { date: "2026-09-27", amount: "14531.74" },
            { date: "2026-08-28", amount: "14289.49" },
          ],
        },
      ]),
    });
    const dialog = await screen.findByRole("dialog", { name: "Cap gains tax" });
    expect(dialog).toHaveTextContent("Edit liability");
    expect(within(dialog).getByLabelText("Name")).toHaveValue("Cap gains tax");
    expect(within(dialog).getByLabelText("Name")).toHaveFocus();
    // The type is fixed once created.
    expect(within(dialog).queryByLabelText("Asset")).toBeNull();
    expect(within(dialog).getByLabelText("Category")).toHaveValue(
      "tax_liability",
    );
    expect(
      within(dialog).getByLabelText("Computed from other accounts"),
    ).toBeChecked();
    expect(within(dialog).getByLabelText("Rate (%)")).toHaveValue("15");
    expect(within(dialog).getByLabelText("Cost basis ($)")).toHaveValue(
      "82,386.74",
    );
    expect(within(dialog).getByLabelText("Schwab")).toBeChecked();
    expect(within(dialog).getByLabelText("Checking")).not.toBeChecked();
    expect(dialog.querySelector("[data-formula-preview]")).toHaveTextContent(
      "15% × ($179,265 − $82,387)$14,531.74",
    );

    const history = dialog.querySelector("details")!;
    expect(history).not.toHaveAttribute("open");
    expect(history.querySelector("summary")).toHaveTextContent(
      "History (2 snapshots)",
    );
    expect(history.textContent!.indexOf("Sep 27, 2026")).toBeLessThan(
      history.textContent!.indexOf("Aug 28, 2026"),
    );
    expect(history).toHaveTextContent("$14,289.49");

    const retire = within(dialog).getByRole("region", { name: "Retire" });
    expect(retire).toHaveTextContent(
      "Last saved at $14,531.74 on September 27, 2026.",
    );
    expect(
      within(retire).getByRole("button", { name: "Retire anyway" }),
    ).toBeInTheDocument();
    expect(document.title).toBe("Cap gains tax · Household · Sensibility");
  });

  it("shows a plain account with no snapshots yet, and plain Retire", async () => {
    const cash = { ...CHECKING, id: 7, name: "Cash", amount: null };
    open(`${ACCOUNTS}/7/edit`, details([cash]));
    const dialog = await screen.findByRole("dialog", { name: "Cash" });
    expect(dialog).toHaveTextContent("Edit asset");
    expect(
      within(dialog).getByLabelText("Computed from other accounts"),
    ).not.toBeChecked();
    expect(within(dialog).queryByLabelText("Rate (%)")).toBeNull();
    expect(dialog.querySelector("summary")).toHaveTextContent(
      "History (no snapshots)",
    );
    expect(dialog).toHaveTextContent(
      "No snapshots yet. Save one from the Accounts page.",
    );
    const retire = within(dialog).getByRole("region", { name: "Retire" });
    expect(retire).toHaveTextContent(
      "Retiring hides this account and stops including it in snapshots. History is kept.",
    );
    expect(
      within(retire).getByRole("button", { name: "Retire" }),
    ).toBeInTheDocument();
  });

  it("says History (1 snapshot)", async () => {
    open(`${ACCOUNTS}/${CHECKING.id}/edit`, details([CHECKING]));
    const dialog = await screen.findByRole("dialog", { name: "Checking" });
    expect(dialog.querySelector("summary")).toHaveTextContent(
      "History (1 snapshot)",
    );
  });

  it("explains a blocker and offers no Retire", async () => {
    open(
      `${ACCOUNTS}/${SCHWAB.id}/edit`,
      details([
        SCHWAB,
        {
          retire_blocker:
            "Schwab is an input to Cap gains tax. Retire or edit those first.",
        },
      ]),
    );
    const dialog = await screen.findByRole("dialog", { name: "Schwab" });
    const retire = within(dialog).getByRole("region", { name: "Retire" });
    expect(retire).toHaveTextContent("Schwab is an input to Cap gains tax");
    expect(within(retire).queryByRole("button")).toBeNull();
  });

  it("saves changes with PATCH, flashes and goes back", async () => {
    const { user, router, fetchMock } = open(`${ACCOUNTS}/${TAX.id}/edit`, {
      ...details([TAX]),
      [`PATCH ${API}/${TAX.id}`]: { body: { ...TAX, name: "Tax" } },
    });
    const dialog = await screen.findByRole("dialog", { name: "Cap gains tax" });
    const name = within(dialog).getByLabelText("Name");
    await user.clear(name);
    await user.type(name, "Tax");
    await user.click(within(dialog).getByLabelText("Checking"));
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await screen.findByText("Saved Tax")).toBeInTheDocument();
    await waitFor(() => expect(router.state.location.pathname).toBe(ACCOUNTS));
    const patch = lastCall(fetchMock, "PATCH");
    expect(patch.url).toBe(`${API}/${TAX.id}`);
    expect(patch.body).toEqual({
      name: "Tax",
      category: "tax_liability",
      formula: {
        rate_percent: "15",
        cost_basis: "82,386.74",
        input_ids: [1, 2],
      },
    });
    expect(patch.headers["X-Requested-With"]).toBe("sensibility");
  });

  it("makes a computed account plain", async () => {
    const { user, fetchMock } = open(`${ACCOUNTS}/${TAX.id}/edit`, {
      ...details([TAX]),
      [`PATCH ${API}/${TAX.id}`]: { body: TAX },
    });
    const dialog = await screen.findByRole("dialog", { name: "Cap gains tax" });
    await user.click(
      within(dialog).getByLabelText("Computed from other accounts"),
    );
    await user.selectOptions(within(dialog).getByLabelText("Category"), "");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    await screen.findByText("Saved Cap gains tax");
    expect(lastCall(fetchMock, "PATCH").body).toEqual({
      name: "Cap gains tax",
      category: null,
      formula: null,
    });
  });

  it("keeps the drawer, and the input, on a refusal", async () => {
    const { user } = open(`${ACCOUNTS}/${TAX.id}/edit`, {
      ...details([TAX]),
      [`PATCH ${API}/${TAX.id}`]: {
        status: 400,
        body: { error: "Rate must be a number, e.g. 15 for 15%" },
      },
    });
    const dialog = await screen.findByRole("dialog", { name: "Cap gains tax" });
    const rate = within(dialog).getByLabelText("Rate (%)");
    await user.clear(rate);
    await user.type(rate, "abc");
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "Rate must be a number, e.g. 15 for 15%",
    );
    expect(rate).toHaveValue("abc");
    // The rest of the drawer is still there.
    expect(
      within(dialog).getByRole("region", { name: "Retire" }),
    ).toBeInTheDocument();
  });

  it("retires, flashes and goes back", async () => {
    const { user, router, fetchMock } = open(
      `${ACCOUNTS}/${CHECKING.id}/edit`,
      {
        ...details([CHECKING]),
        [`POST ${API}/${CHECKING.id}/retire`]: {
          body: { ...CHECKING, retired_at: "2026-10-28" },
        },
      },
    );
    const dialog = await screen.findByRole("dialog", { name: "Checking" });
    await user.click(within(dialog).getByRole("button", { name: "Retire" }));
    expect(await screen.findByText("Retired Checking")).toBeInTheDocument();
    await waitFor(() => expect(router.state.location.pathname).toBe(ACCOUNTS));
    const post = lastCall(fetchMock, "POST");
    expect(post.url).toBe(`${API}/${CHECKING.id}/retire`);
    expect(post.headers["X-Requested-With"]).toBe("sensibility");
  });

  it("flashes a refused retire on the page", async () => {
    const { user, router } = open(`${ACCOUNTS}/${CHECKING.id}/edit`, {
      ...details([CHECKING]),
      [`POST ${API}/${CHECKING.id}/retire`]: {
        status: 400,
        body: { error: "Checking is already retired" },
      },
    });
    const dialog = await screen.findByRole("dialog", { name: "Checking" });
    await user.click(within(dialog).getByRole("button", { name: "Retire" }));
    expect(
      await screen.findByText("Checking is already retired"),
    ).toBeInTheDocument();
    await waitFor(() => expect(router.state.location.pathname).toBe(ACCOUNTS));
  });

  it("unretires a retired account", async () => {
    const { user, fetchMock } = open(`${ACCOUNTS}/${OLD.id}/edit`, {
      ...details([OLD]),
      [`POST ${API}/${OLD.id}/unretire`]: {
        body: { ...OLD, retired_at: null },
      },
    });
    const dialog = await screen.findByRole("dialog", { name: "Old savings" });
    const retire = within(dialog).getByRole("region", { name: "Retire" });
    expect(retire).toHaveTextContent(
      "Retired Sep 1, 2026. Unretiring brings it back with a blank amount.",
    );
    expect(
      within(retire).queryByRole("button", { name: /^Retire/ }),
    ).toBeNull();
    await user.click(within(retire).getByRole("button", { name: "Unretire" }));
    expect(
      await screen.findByText("Unretired Old savings"),
    ).toBeInTheDocument();
    expect(lastCall(fetchMock, "POST").url).toBe(`${API}/${OLD.id}/unretire`);
  });

  it("says when the account isn't there", async () => {
    open(`${ACCOUNTS}/99/edit`, {
      [`GET ${API}/99`]: { status: 404, body: { error: "Account not found" } },
    });
    const dialog = await screen.findByRole("dialog", {
      name: "Account not found",
    });
    expect(within(dialog).getByRole("alert")).toHaveTextContent(
      "There's no such account in this workspace.",
    );
  });

  it("shows a viewer the same drawer; the server refuses the write", async () => {
    const { user } = open(
      `${ACCOUNTS}/${TAX.id}/edit`,
      {
        ...details([TAX, { can_edit: false }]),
        [`PATCH ${API}/${TAX.id}`]: {
          status: 403,
          body: { error: "This needs the editor role or higher" },
        },
      },
      VIEWER,
    );
    const dialog = await screen.findByRole("dialog", { name: "Cap gains tax" });
    await user.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent(
      "This needs the editor role or higher",
    );
  });
});

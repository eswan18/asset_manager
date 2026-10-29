import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { CashFlowsOverview, CategoryRow } from "@/api/cash-flows";
import {
  findSheet,
  mockApi,
  renderRoute,
  shellApi,
  type FakeResponse,
} from "@/test/utils";

import { EMPTY, SEED_MONTH, SEED_YEAR } from "./cash-flows.fixtures";

const DRAWER = "/workspaces/1/cash-flow-categories";
const API = "/api/workspaces/1/cash-flow-categories";
// SEED_MONTH's categories: Work 11, Housing 12, Food 13, Transport 14,
// Gifts 15.

type Handler = (request: { body: unknown }) => FakeResponse;

/** The shell, a live overview (each write's handler may change it), and
 * the writes. */
function categoriesApi(
  writes: Record<string, Handler> = {},
  start: CashFlowsOverview = SEED_MONTH,
) {
  const state = { overview: start };
  const fetchMock = mockApi({
    ...shellApi(),
    "GET /api/workspaces/1/cash-flows/overview": ({ url }) => ({
      body: url.searchParams.get("per") === "year" ? SEED_YEAR : state.overview,
    }),
    "GET /api/workspaces/2/cash-flows/overview": {
      body: { ...start, can_edit: false },
    },
    ...writes,
  });
  return { fetchMock, state };
}

/** The overview with its categories changed. */
function withCategories(
  change: (rows: CategoryRow[]) => CategoryRow[],
): CashFlowsOverview {
  return { ...SEED_MONTH, categories: change(SEED_MONTH.categories) };
}

function writesOf(fetchMock: ReturnType<typeof mockApi>) {
  return fetchMock.mock.calls
    .filter(([, init]) => init?.method && init.method !== "GET")
    .map(([url, init]) => ({
      method: init!.method,
      url: new URL(String(url), "http://localhost").pathname,
      body: typeof init!.body === "string" ? JSON.parse(init!.body) : undefined,
      csrf: (init!.headers as Record<string, string>)["X-Requested-With"],
    }));
}

const names = () =>
  screen
    .getAllByRole("textbox", { name: /^Name of / })
    .map((input) => (input as HTMLInputElement).value);
const status = () => screen.getByRole("status");

async function open(path = `${DRAWER}?per=month`) {
  const result = renderRoute(path);
  await findSheet({ name: "Categories" });
  return result;
}

describe("the categories drawer", () => {
  it("lists the categories in order, with their colors and flows", async () => {
    categoriesApi();
    await open();
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent(
      "Order here is the order of the cards and the bar. Renaming or reordering saves right away.",
    );
    expect(names()).toEqual(["Work", "Housing", "Food", "Transport", "Gifts"]);
    for (const meta of [
      "1 flow · income $11,080.36/mo",
      "2 flows · $2,710.00/mo",
      "2 flows · $1,132.14/mo",
      "1 flow · $120.00/mo",
      "No flows yet",
    ]) {
      expect(within(dialog).getByText(meta)).toBeInTheDocument();
    }
    const swatches = screen
      .getAllByRole("textbox", { name: /^Name of / })
      .map(
        (input) =>
          (input.previousElementSibling as HTMLElement).style.background,
      );
    expect(swatches).toEqual([
      "var(--asset)",
      "var(--liability)",
      "var(--liability-2)",
      "var(--liability-4)",
      "var(--rule-strong)",
    ]);
    expect(document.title).toBe("Categories · Household · Sensibility");
  });

  it("follows the period", async () => {
    categoriesApi();
    await open(`${DRAWER}?per=year`);
    expect(
      within(screen.getByRole("dialog")).getByText("2 flows · $32,520.00/yr"),
    ).toBeInTheDocument();
  });

  it("can't move the ends further", async () => {
    categoriesApi();
    await open();
    expect(screen.getByRole("button", { name: "Move Work up" })).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "Move Work down" }),
    ).toBeEnabled();
    expect(
      screen.getByRole("button", { name: "Move Housing up" }),
    ).toBeEnabled();
    expect(
      screen.getByRole("button", { name: "Move Gifts down" }),
    ).toBeDisabled();
  });

  it("renames when the field loses focus", async () => {
    const { fetchMock, state } = categoriesApi({
      [`PATCH ${API}/13`]: () => {
        state.overview = withCategories((rows) =>
          rows.map((r) => (r.id === 13 ? { ...r, name: "Food & drink" } : r)),
        );
        return { body: { id: 13, name: "Food & drink", position: 2 } };
      },
    });
    const { user } = await open();
    const food = screen.getByRole("textbox", { name: "Name of Food" });
    await user.clear(food);
    await user.type(food, "Food & drink");
    await user.tab();

    await waitFor(() =>
      expect(status()).toHaveTextContent("Saved Food & drink"),
    );
    expect(names()).toEqual([
      "Work",
      "Housing",
      "Food & drink",
      "Transport",
      "Gifts",
    ]);
    expect(writesOf(fetchMock)).toEqual([
      {
        method: "PATCH",
        url: `${API}/13`,
        body: { name: "Food & drink" },
        csrf: "sensibility",
      },
    ]);
  });

  it("doesn't save an unchanged or whitespace-only rename", async () => {
    const { fetchMock } = categoriesApi();
    const { user } = await open();
    const work = screen.getByRole("textbox", { name: "Name of Work" });
    await user.click(work);
    await user.tab();
    await user.clear(work);
    await user.type(work, "  Work  ");
    await user.tab();
    expect(writesOf(fetchMock)).toEqual([]);
  });

  it("saves a rename once on Enter, though the field then loses focus", async () => {
    let answer: (response: FakeResponse) => void = () => {};
    const { fetchMock, state } = categoriesApi({
      [`PATCH ${API}/15`]: () =>
        new Promise<FakeResponse>((resolve) => {
          answer = resolve;
        }) as unknown as FakeResponse,
    });
    const { user } = await open();
    const gifts = screen.getByRole("textbox", { name: "Name of Gifts" });
    await user.clear(gifts);
    await user.type(gifts, "Presents{Enter}");
    // While the save is on its way, focus moves on.
    await user.tab();
    await user.click(
      screen.getByRole("textbox", { name: "New category name" }),
    );
    state.overview = withCategories((rows) =>
      rows.map((r) => (r.id === 15 ? { ...r, name: "Presents" } : r)),
    );
    answer({ body: { id: 15, name: "Presents", position: 4 } });
    await waitFor(() => expect(status()).toHaveTextContent("Saved Presents"));
    await user.click(screen.getByRole("textbox", { name: "Name of Presents" }));
    await user.tab();
    expect(writesOf(fetchMock).map((w) => w.method)).toEqual(["PATCH"]);
  });

  it("keeps a refused rename in its row, marked, with focus", async () => {
    categoriesApi({
      [`PATCH ${API}/13`]: () => ({
        status: 400,
        body: { error: "A category named 'Housing' already exists" },
      }),
    });
    const { user } = await open();
    const food = screen.getByRole("textbox", { name: "Name of Food" });
    await user.clear(food);
    await user.type(food, "Housing{Enter}");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "A category named 'Housing' already exists",
    );
    expect(food).toHaveValue("Housing");
    expect(food).toHaveAttribute("aria-invalid", "true");
    expect(food).toHaveFocus();
    expect(status()).toHaveTextContent("");
    // The other rows are as saved.
    expect(names()).toEqual([
      "Work",
      "Housing",
      "Housing",
      "Transport",
      "Gifts",
    ]);
  });

  it("moves a category", async () => {
    const { fetchMock, state } = categoriesApi({
      [`POST ${API}/13/move`]: () => {
        state.overview = withCategories(([work, housing, food, ...rest]) => [
          work,
          food,
          housing,
          ...rest,
        ]);
        return { body: { categories: [] } };
      },
    });
    const { user } = await open();
    await user.click(screen.getByRole("button", { name: "Move Food up" }));
    await waitFor(() => expect(status()).toHaveTextContent("Moved Food up"));
    expect(names()).toEqual(["Work", "Food", "Housing", "Transport", "Gifts"]);
    expect(writesOf(fetchMock)).toEqual([
      {
        method: "POST",
        url: `${API}/13/move`,
        body: { direction: "up" },
        csrf: "sensibility",
      },
    ]);
  });

  it("asks before deleting, in the row", async () => {
    const { fetchMock, state } = categoriesApi({
      [`DELETE ${API}/13`]: () => {
        state.overview = withCategories((rows) =>
          rows.filter((r) => r.id !== 13),
        );
        return { body: { deleted: 13 } };
      },
    });
    const { user } = await open();
    await user.click(screen.getByRole("button", { name: "Delete Food" }));
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent(
      "Delete Food? 2 flows. They move to Uncategorized; nothing else is deleted.",
    );
    // The confirmation takes the row's place.
    expect(names()).toEqual(["Work", "Housing", "Transport", "Gifts"]);
    expect(screen.getByRole("button", { name: "Keep" })).toHaveFocus();

    await user.click(screen.getByRole("button", { name: "Keep" }));
    expect(names()).toEqual(["Work", "Housing", "Food", "Transport", "Gifts"]);
    expect(writesOf(fetchMock)).toEqual([]);

    await user.click(screen.getByRole("button", { name: "Delete Food" }));
    await user.click(screen.getByRole("button", { name: "Delete category" }));
    await waitFor(() => expect(status()).toHaveTextContent("Deleted Food"));
    expect(names()).toEqual(["Work", "Housing", "Transport", "Gifts"]);
    expect(writesOf(fetchMock)).toEqual([
      {
        method: "DELETE",
        url: `${API}/13`,
        body: undefined,
        csrf: "sensibility",
      },
    ]);
  });

  it.each([
    [14, "Delete Transport? 1 flow. It moves to Uncategorized"],
    [15, "Delete Gifts? It has no flows; nothing else is deleted."],
  ])("counts the flows in the confirmation (%s)", async (id, text) => {
    categoriesApi();
    const { user } = await open();
    const name = SEED_MONTH.categories.find((c) => c.id === id)!.name;
    await user.click(screen.getByRole("button", { name: `Delete ${name}` }));
    expect(screen.getByRole("dialog")).toHaveTextContent(text);
  });

  it("adds one last, ready for the next", async () => {
    const { fetchMock, state } = categoriesApi({
      [`POST ${API}`]: () => {
        state.overview = withCategories((rows) => [
          ...rows,
          { ...rows[4], id: 16, name: "Pets", position: 5 },
        ]);
        return { status: 201, body: { id: 16, name: "Pets", position: 5 } };
      },
    });
    const { user } = await open();
    const input = screen.getByRole("textbox", { name: "New category name" });
    await user.type(input, " Pets {Enter}");
    await waitFor(() => expect(status()).toHaveTextContent("Added Pets"));
    expect(names().at(-1)).toBe("Pets");
    expect(input).toHaveValue("");
    expect(input).toHaveFocus();
    expect(writesOf(fetchMock)).toEqual([
      {
        method: "POST",
        url: API,
        body: { name: " Pets " },
        csrf: "sensibility",
      },
    ]);
  });

  it("keeps a refused new name", async () => {
    categoriesApi({
      [`POST ${API}`]: () => ({
        status: 400,
        body: { error: "A category named 'Food' already exists" },
      }),
    });
    const { user } = await open();
    const input = screen.getByRole("textbox", { name: "New category name" });
    await user.type(input, "Food");
    await user.click(screen.getByRole("button", { name: "+ Add" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "A category named 'Food' already exists",
    );
    expect(input).toHaveValue("Food");
    expect(input).toHaveFocus();
  });

  it("starts in the new name from + New category", async () => {
    categoriesApi();
    await open(`${DRAWER}?per=month&add=1`);
    await waitFor(() =>
      expect(
        screen.getByRole("textbox", { name: "New category name" }),
      ).toHaveFocus(),
    );
  });

  it("says there are none yet", async () => {
    categoriesApi({}, EMPTY);
    await open();
    expect(
      screen.getByText(
        "No categories yet. Add one below; expenses in it get their own card.",
      ),
    ).toBeInTheDocument();
  });

  it("is done back on the page in its period", async () => {
    categoriesApi();
    const { user, router } = await open(`${DRAWER}?per=year`);
    await user.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/workspaces/1/cash-flows"),
    );
    expect(router.state.location.search).toBe("?per=year");
  });

  it("sends a viewer back to the page", async () => {
    categoriesApi();
    const { router } = renderRoute("/workspaces/2/cash-flow-categories");
    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/workspaces/2/cash-flows"),
    );
    expect(router.state.location.search).toBe("?per=month");
  });
});

import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { CashFlowsOverview } from "@/api/cash-flows";
import {
  mockApi,
  renderRoute,
  shellApi,
  type FakeResponse,
} from "@/test/utils";

import {
  EMPTY,
  NO_INCOME,
  OVER,
  SEED_MONTH,
  SEED_YEAR,
} from "./cash-flows.fixtures";

/** The shell, and workspace `id`'s overview: `byPeriod` answers each
 * `?per=`, falling back to month. */
function overviewApi(
  byPeriod: Partial<Record<string, CashFlowsOverview | FakeResponse>>,
  id = 1,
) {
  return mockApi({
    ...shellApi(),
    [`GET /api/workspaces/${id}/cash-flows/overview`]: ({ url }) => {
      const answer =
        byPeriod[url.searchParams.get("per") ?? ""] ?? byPeriod.month;
      return answer && "period" in answer ? { body: answer } : answer!;
    },
  });
}

function requestedPeriods(fetchMock: ReturnType<typeof mockApi>) {
  return fetchMock.mock.calls
    .map(([url]) => new URL(String(url), "http://localhost"))
    .filter((url) => url.pathname.endsWith("/overview"))
    .map((url) => url.searchParams.get("per"));
}

const PAGE = "/workspaces/1/cash-flows";

describe("the Cash flows page", () => {
  it("shows the headline, the bar and the cards", async () => {
    overviewApi({ month: SEED_MONTH });
    renderRoute(PAGE);

    expect(await screen.findByText("Left over each month")).toBeInTheDocument();
    const figure = screen.getByText("+$7,728.21");
    expect(figure).not.toHaveClass("text-danger");
    expect(figure.nextElementSibling).toHaveTextContent(
      "of $11,880.36 income · $92,739 a year · ≈ 1 estimate",
    );
    expect(screen.getByText("Expenses $4,152.14 · 35%")).toBeInTheDocument();

    const bar = screen.getByRole("img");
    expect(bar).toHaveAccessibleName(
      "Of $11,880.36 income each month: Housing 23%, Food 10%, Transport 1%, Uncategorized 2%, Left over 65%",
    );
    const slices = Array.from(bar.children) as HTMLElement[];
    expect(slices.map((s) => s.style.flexGrow)).toEqual([
      "22.8108",
      "9.5295",
      "1.0101",
      "1.5993",
      "65.0504",
    ]);
    expect(slices[1].style.background).toBe("var(--liability-2)");
    const key = screen.getByRole("list");
    expect(
      within(key)
        .getAllByRole("listitem")
        .map((li) => li.textContent),
    ).toEqual([
      "Housing $2,710.00 23%",
      "Food $1,132.14 10%",
      "Transport $120.00 1%",
      "Uncategorized $190.00 2%",
      "Left over $7,728.21 65%",
    ]);

    // Income first, then the categories with expenses, Uncategorized last.
    const cards = screen.getAllByRole("heading", { level: 2 });
    expect(cards.map((h) => h.textContent)).toEqual([
      "Income",
      "Housing",
      "Food",
      "Transport",
      "Uncategorized",
    ]);
    expect(screen.getByText("All income")).toBeInTheDocument();
    expect(screen.getByText("23% of income")).toBeInTheDocument();
    expect(document.title).toBe("Cash flows · Household · Sensibility");
  });

  it("lists each flow: name, ≈, every, and the period's amount", async () => {
    overviewApi({ month: SEED_MONTH });
    renderRoute(PAGE);
    const groceries = await screen.findByRole("link", { name: /^Groceries/ });
    expect(groceries).toHaveTextContent("Groceries ≈$180.00 every week$782.14");
    expect(within(groceries).getByTitle("Estimate")).toHaveTextContent("≈");
    expect(screen.getByRole("link", { name: /^Salary/ })).toHaveTextContent(
      "Salary$5,100.00 every 2 weeks$11,080.36",
    );
  });

  it("gives an editor every control, keeping the period", async () => {
    overviewApi({ year: SEED_YEAR });
    renderRoute(`${PAGE}?per=year`);
    const link = (name: string | RegExp) =>
      screen.getByRole("link", { name }).getAttribute("href");

    await screen.findByText("Left over each year");
    expect(link("Manage categories")).toBe(
      "/workspaces/1/cash-flow-categories?per=year",
    );
    expect(link("+ Add cash flow")).toBe(
      "/workspaces/1/cash-flows/new?per=year",
    );
    expect(link("+ New category")).toBe(
      "/workspaces/1/cash-flow-categories?per=year&add=1",
    );
    // Each row opens its drawer; each card adds into itself.
    expect(link(/^Groceries/)).toBe("/workspaces/1/cash-flows/5/edit?per=year");
    expect(
      screen
        .getAllByRole("link")
        .filter((a) => a.getAttribute("href")?.includes("/edit?")),
    ).toHaveLength(8);
    expect(link("Add to Income")).toBe(
      "/workspaces/1/cash-flows/new?direction=income&per=year",
    );
    expect(link("Add to Food")).toBe(
      "/workspaces/1/cash-flows/new?direction=expense&category_id=13&per=year",
    );
    expect(link("Add to Uncategorized")).toBe(
      "/workspaces/1/cash-flows/new?direction=expense&per=year",
    );
  });

  it("switches period in place", async () => {
    const fetchMock = overviewApi({ month: SEED_MONTH, year: SEED_YEAR });
    const { user, router } = renderRoute(PAGE);
    const toggle = await screen.findByRole("radiogroup", {
      name: "Show amounts per",
    });
    expect(
      within(toggle)
        .getAllByRole("radio")
        .map((b) => b.textContent),
    ).toEqual(["Day", "Month", "Year"]);
    expect(within(toggle).getByRole("radio", { name: "Month" })).toBeChecked();

    await user.click(within(toggle).getByRole("radio", { name: "Year" }));
    expect(await screen.findByText("Left over each year")).toBeInTheDocument();
    expect(screen.getByText("+$92,738.57")).toBeInTheDocument();
    expect(screen.getByText(/\$7,728 a month/)).toBeInTheDocument();
    expect(router.state.location.search).toBe("?per=year");
    expect(within(toggle).getByRole("radio", { name: "Year" })).toBeChecked();
    expect(requestedPeriods(fetchMock)).toEqual(["month", "year"]);
    // The links follow.
    expect(
      screen.getByRole("link", { name: "+ Add cash flow" }),
    ).toHaveAttribute("href", "/workspaces/1/cash-flows/new?per=year");
  });

  it.each(["fortnight", ""])("reads ?per=%s as month", async (per) => {
    const fetchMock = overviewApi({ month: SEED_MONTH });
    renderRoute(`${PAGE}?per=${per}`);
    await screen.findByText("Left over each month");
    expect(screen.getByRole("radio", { name: "Month" })).toBeChecked();
    expect(requestedPeriods(fetchMock)).toEqual(["month"]);
  });

  it("marks expenses above income", async () => {
    overviewApi({ month: OVER });
    renderRoute(PAGE);
    expect(await screen.findByText("Short each month")).toBeInTheDocument();
    const figure = screen.getByText("−$100.00");
    expect(figure).toHaveClass("text-danger");
    expect(figure.nextElementSibling).toHaveTextContent(
      "Expenses $1,600.00 vs income $1,500.00 · −$1,200 a year · ≈ 1 estimate",
    );
    expect(
      screen.getByText("Expenses exceed income by $100.00 (7%)"),
    ).toBeInTheDocument();
    expect(screen.getByRole("img")).toHaveAccessibleName(
      "Expenses of $1,600.00 each month: Uncategorized $1,600.00, against $1,500.00 income, which runs out before the last $100.00",
    );
    // The marker sits at income's share of expenses: 1,500 / 1,600.
    const label = screen.getByText("▲ Income runs out");
    expect(label.parentElement!.style.getPropertyValue("--marker")).toBe(
      "93.7500%",
    );
    expect(screen.getAllByRole("listitem").map((li) => li.textContent)).toEqual(
      ["Uncategorized $1,600.00", "Past income $100.00"],
    );
    expect(screen.getByText("107% of income")).toBeInTheDocument();
    expect(screen.queryByText(/Left over/)).not.toBeInTheDocument();
  });

  it("has no bar without income", async () => {
    overviewApi({ month: NO_INCOME });
    renderRoute(PAGE);
    expect(
      await screen.findByText(
        "No income yet. Add an income cash flow to see where it goes.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("−$1,400.00")).toBeInTheDocument();
    expect(screen.getByText("No income to compare")).toBeInTheDocument();
    expect(screen.getByText("No income yet")).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("offers an editor one button on an empty page, income first", async () => {
    overviewApi({ month: EMPTY });
    renderRoute(PAGE);
    expect(
      await screen.findByRole("heading", { name: "No cash flows yet" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "+ Add income" })).toHaveAttribute(
      "href",
      "/workspaces/1/cash-flows/new?direction=income&per=month",
    );
    expect(screen.queryByText("Manage categories")).not.toBeInTheDocument();
    expect(screen.queryByRole("radiogroup")).not.toBeInTheDocument();
  });

  it("gives a viewer no controls", async () => {
    // ME is a viewer in workspace 2.
    overviewApi({ month: { ...SEED_MONTH, can_edit: false } }, 2);
    renderRoute("/workspaces/2/cash-flows");
    await screen.findByText("Left over each month");
    const main = screen.getByRole("main");
    expect(within(main).queryAllByRole("link")).toEqual([]);
    expect(within(main).getByText("Groceries")).toBeInTheDocument();
    for (const control of ["+ Add", "+ New category", "Manage categories"]) {
      expect(within(main).queryByText(control)).not.toBeInTheDocument();
    }
    // The toggle is for everyone.
    expect(within(main).getByRole("radiogroup")).toBeInTheDocument();
  });

  it("tells a viewer an editor hasn't added any", async () => {
    overviewApi({ month: { ...EMPTY, can_edit: false } }, 2);
    renderRoute("/workspaces/2/cash-flows");
    expect(
      await screen.findByText("An editor hasn't added any cash flows yet."),
    ).toBeInTheDocument();
    expect(screen.queryByText("+ Add income")).not.toBeInTheDocument();
  });

  it("says so when the data can't load", async () => {
    overviewApi({ month: { status: 500, body: { error: "boom" } } });
    renderRoute(PAGE);
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        "An error occurred while loading your data. Please try again later.",
      ),
    );
  });
});

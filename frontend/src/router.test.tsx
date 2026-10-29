import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ME, mockApi, renderRoute, shellApi } from "@/test/utils";

describe("the router", () => {
  it("sends / to your oldest workspace", async () => {
    mockApi(shellApi());
    const { router } = renderRoute("/");
    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/workspaces/1"),
    );
  });

  it("sends / to welcome when you have no workspace", async () => {
    mockApi(shellApi({ ...ME, workspaces: [] }));
    const { router } = renderRoute("/");
    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/welcome"),
    );
  });

  it.each([
    ["/workspaces/1", "Dashboard"],
    ["/workspaces/1/accounts", "Accounts"],
    ["/workspaces/1/cash-flows", "Cash flows"],
    ["/workspaces/1/settings", "Settings"],
    ["/welcome", "Welcome"],
  ])("renders %s", async (path, title) => {
    mockApi(shellApi());
    renderRoute(path);
    expect(
      await screen.findByRole("heading", { level: 2, name: title }),
    ).toBeInTheDocument();
  });

  it.each([
    ["/workspaces/1/accounts/new", "New account", "Accounts"],
    ["/workspaces/1/accounts/4/edit", "Edit account", "Accounts"],
    ["/workspaces/1/cash-flows/new", "New cash flow", "Cash flows"],
    ["/workspaces/1/cash-flows/4/edit", "Edit cash flow", "Cash flows"],
    ["/workspaces/1/cash-flow-categories", "Categories", "Cash flows"],
  ])("renders the drawer %s over its page", async (path, drawer, page) => {
    mockApi(shellApi());
    renderRoute(path);
    expect(
      await screen.findByRole("dialog", { name: drawer }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 2, name: page, hidden: true }),
    ).toBeInTheDocument();
  });

  it("keeps ?per= when a cash flow drawer closes", async () => {
    mockApi(shellApi());
    const { router, user } = renderRoute(
      "/workspaces/1/cash-flows/new?per=year",
    );
    await user.click(await screen.findByRole("button", { name: "Close" }));
    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/workspaces/1/cash-flows"),
    );
    expect(router.state.location.search).toBe("?per=year");
  });

  it("has a not-found page", async () => {
    mockApi(shellApi());
    renderRoute("/nowhere");
    expect(
      await screen.findByRole("heading", { name: "Page not found" }),
    ).toBeInTheDocument();
  });
});

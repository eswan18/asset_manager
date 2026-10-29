import { screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import pageRoutes from "@/page-routes.json";
import { pagePaths } from "@/router";
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

  it("sends a bare /accounts to Accounts in your oldest workspace", async () => {
    mockApi(shellApi());
    const { router } = renderRoute("/accounts");
    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/workspaces/1/accounts"),
    );
  });

  it("sends a bare /accounts to welcome when you have no workspace", async () => {
    mockApi(shellApi({ ...ME, workspaces: [] }));
    const { router } = renderRoute("/accounts");
    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/welcome"),
    );
  });

  it("lists every page in page-routes.json, which the phone sweep reads", () => {
    expect(pagePaths()).toEqual(pageRoutes);
  });

  // Each page and drawer has its own tests beside it in routes/.

  it("has a not-found page", async () => {
    mockApi(shellApi());
    renderRoute("/nowhere");
    expect(
      await screen.findByRole("heading", { name: "Page not found" }),
    ).toBeInTheDocument();
  });
});

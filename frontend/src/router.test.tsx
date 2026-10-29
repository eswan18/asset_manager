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

  // Each page and drawer has its own tests beside it in routes/.

  it("has a not-found page", async () => {
    mockApi(shellApi());
    renderRoute("/nowhere");
    expect(
      await screen.findByRole("heading", { name: "Page not found" }),
    ).toBeInTheDocument();
  });
});

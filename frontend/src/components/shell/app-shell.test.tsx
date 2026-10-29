import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { invite, ME, mockApi, renderRoute, shellApi } from "@/test/utils";

describe("the shell", () => {
  it("shows the nav, the picker, the gear and the avatar in a workspace", async () => {
    mockApi(shellApi());
    renderRoute("/workspaces/1/accounts");

    const nav = await screen.findByRole("navigation", { name: "Main" });
    const links = within(nav).getAllByRole("link");
    expect(links.map((a) => a.textContent)).toEqual([
      "Dashboard",
      "Accounts",
      "Cash flows",
    ]);
    expect(within(nav).getByRole("link", { name: "Accounts" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(nav).toHaveAttribute("data-tabbar");

    const picker = screen.getByRole("combobox", { name: "Workspace" });
    expect(picker).toHaveValue("1");
    expect(
      screen.getByRole("link", { name: "Workspace settings" }),
    ).toHaveAttribute("href", "/workspaces/1/settings");
    expect(
      screen.getByRole("button", { name: "Account menu for Ethan Swan" }),
    ).toHaveTextContent("ES");
  });

  it("marks Cash flows current under the categories drawer", async () => {
    mockApi(shellApi());
    renderRoute("/workspaces/1/cash-flow-categories");
    // hidden: the drawer makes the page behind it inert.
    const nav = await screen.findByRole("navigation", {
      name: "Main",
      hidden: true,
    });
    expect(
      within(nav).getByRole("link", { name: "Cash flows", hidden: true }),
    ).toHaveAttribute("aria-current", "page");
  });

  it("marks the gear current on settings, and only there", async () => {
    mockApi(shellApi());
    renderRoute("/workspaces/1/settings");
    expect(
      await screen.findByRole("link", { name: "Workspace settings" }),
    ).toHaveAttribute("aria-current", "page");
  });

  it("leaves the gear unmarked on other pages", async () => {
    mockApi(shellApi());
    renderRoute("/workspaces/1/accounts");
    expect(
      await screen.findByRole("link", { name: "Workspace settings" }),
    ).not.toHaveAttribute("aria-current");
  });

  it("switches workspace, keeping the section", async () => {
    mockApi(shellApi());
    // (Deeper paths map to their section: sections.test.ts.)
    const { user, router } = renderRoute("/workspaces/1/settings");
    const picker = await screen.findByRole("combobox", { name: "Workspace" });
    await user.selectOptions(picker, "Lake house");
    expect(router.state.location.pathname).toBe("/workspaces/2/settings");
  });

  it("opens the account menu", async () => {
    mockApi(shellApi());
    const { user } = renderRoute("/workspaces/1");
    await user.click(
      await screen.findByRole("button", {
        name: "Account menu for Ethan Swan",
      }),
    );
    const menu = screen.getByRole("menu");
    expect(menu).toHaveTextContent("me@example.com");
    expect(
      within(menu).getByRole("menuitem", { name: "New workspace" }),
    ).toHaveAttribute("href", "/welcome");
    expect(
      within(menu).getByRole("menuitem", { name: "Log out" }),
    ).toHaveAttribute("href", "/logout");
  });

  it("drops the nav, picker and gear outside a workspace", async () => {
    mockApi(shellApi());
    renderRoute("/welcome");
    await screen.findByRole("button", { name: /Account menu/ });
    expect(
      screen.getByRole("link", { name: "Sensibility" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("link", { name: "Workspace settings" }),
    ).not.toBeInTheDocument();
  });

  it("keeps the account menu outside a workspace", async () => {
    mockApi(shellApi());
    const { user } = renderRoute("/welcome");
    await user.click(
      await screen.findByRole("button", {
        name: "Account menu for Ethan Swan",
      }),
    );
    expect(
      within(screen.getByRole("menu")).getByRole("menuitem", {
        name: "Log out",
      }),
    ).toHaveAttribute("href", "/logout");
  });

  it("is not found in a workspace you are not in", async () => {
    mockApi(shellApi());
    renderRoute("/workspaces/99");
    expect(
      await screen.findByRole("heading", { name: "Page not found" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("navigation")).not.toBeInTheDocument();
  });
});

describe("the invite strip", () => {
  it("shows each pending invite, newest first", async () => {
    mockApi(
      shellApi(ME, [
        invite({
          id: 1,
          workspace_name: "Older",
          created_at: "2026-10-01T00:00:00Z",
        }),
        invite({
          id: 2,
          workspace_name: "Newer",
          created_at: "2026-10-21T00:00:00Z",
        }),
      ]),
    );
    renderRoute("/workspaces/1");
    const strips = await screen.findAllByRole("region", { name: /^Invite to/ });
    expect(strips.map((s) => s.getAttribute("aria-label"))).toEqual([
      "Invite to Newer",
      "Invite to Older",
    ]);
    expect(strips[0]).toHaveTextContent(
      "Jordan Swan invited you to Newer as an editor.",
    );
    expect(strips[0]).toHaveTextContent(/Expires Nov \d/);
  });

  it("leaves out an invite that has lapsed", async () => {
    mockApi(
      shellApi(ME, [
        invite({ id: 1, workspace_name: "Live" }),
        invite({ id: 2, workspace_name: "Lapsed", acceptable: false }),
      ]),
    );
    renderRoute("/workspaces/1");
    const strips = await screen.findAllByRole("region", { name: /^Invite to/ });
    expect(strips.map((s) => s.getAttribute("aria-label"))).toEqual([
      "Invite to Live",
    ]);
  });

  it("joins: into the workspace, with a flash", async () => {
    let invites = [invite()];
    const fetchMock = mockApi({
      "GET /api/me": { body: ME },
      "GET /api/invites": () => ({ body: { invites } }),
      "POST /api/invites/7/accept": () => {
        invites = [];
        return { body: { workspace_id: 3, role: "editor" } };
      },
    });
    const { user, router } = renderRoute("/workspaces/1");
    await user.click(
      await screen.findByRole("button", { name: "Join Jordan's" }),
    );

    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/workspaces/3"),
    );
    expect(
      await screen.findByText("Joined Jordan's as an editor."),
    ).toBeInTheDocument();
    const accept = fetchMock.mock.calls.find(([url]) =>
      String(url).endsWith("/accept"),
    )!;
    expect(
      (accept[1]!.headers as Record<string, string>)["X-Requested-With"],
    ).toBe("sensibility");
  });

  it("declines: the strip goes", async () => {
    let invites = [invite()];
    mockApi({
      "GET /api/me": { body: ME },
      "GET /api/invites": () => ({ body: { invites } }),
      "POST /api/invites/7/decline": () => {
        invites = [];
        return { body: {} };
      },
    });
    const { user } = renderRoute("/workspaces/1");
    await user.click(await screen.findByRole("button", { name: "Decline" }));
    await waitFor(() =>
      expect(
        screen.queryByRole("region", { name: /^Invite to/ }),
      ).not.toBeInTheDocument(),
    );
    expect(
      await screen.findByText("Declined the invite to Jordan's."),
    ).toBeInTheDocument();
  });

  it("says who invited you only when it knows", async () => {
    mockApi(shellApi(ME, [invite({ sender_name: undefined })]));
    renderRoute("/workspaces/1");
    expect(
      await screen.findByRole("region", { name: "Invite to Jordan's" }),
    ).toHaveTextContent("You're invited to Jordan's as an editor.");
  });

  it("isn't on the welcome page", async () => {
    mockApi(shellApi(ME, [invite()]));
    renderRoute("/welcome");
    await screen.findByRole("button", { name: /Account menu/ });
    expect(
      screen.queryByRole("region", { name: /^Invite to/ }),
    ).not.toBeInTheDocument();
  });
});

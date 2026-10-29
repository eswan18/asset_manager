import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { Me, MyInvite } from "@/api/shell";
import { invite, ME, mockApi, renderRoute, shellApi } from "@/test/utils";

const NEWCOMER: Me = { ...ME, name: "Sam Lee", workspaces: [] };

function headers(fetchMock: ReturnType<typeof mockApi>, path: string) {
  const call = fetchMock.mock.calls.find(
    ([url, init]) => String(url) === path && (init?.method ?? "GET") === "POST",
  );
  expect(call, path).toBeDefined();
  return {
    body:
      typeof call![1]!.body === "string"
        ? JSON.parse(call![1]!.body)
        : undefined,
    csrf: (call![1]!.headers as Record<string, string>)["X-Requested-With"],
  };
}

const createButton = () =>
  screen.getByRole("button", { name: "Create workspace" });

describe("welcome, without invites", () => {
  it("greets a newcomer by first name and offers to create", async () => {
    mockApi(shellApi(NEWCOMER));
    renderRoute("/welcome");
    expect(
      await screen.findByRole("heading", { level: 1, name: "Welcome, Sam" }),
    ).toBeInTheDocument();
    expect(document.title).toBe("Welcome · Sensibility");
    expect(
      screen.getByText(
        "A workspace holds a set of accounts and cash flows that you track, alone or with others.",
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: "Start your own workspace" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("Invites for you")).toBeNull();
    expect(screen.queryByText("or", { exact: true })).toBeNull();
    // Create is the primary button.
    expect(createButton()).toHaveClass("bg-primary");
    // Named already, so starting is one click.
    expect(screen.getByRole("textbox", { name: "Name" })).toHaveValue(
      "Sam's Money",
    );
  });

  it("falls back to the email's local part", async () => {
    mockApi(
      shellApi({ ...NEWCOMER, name: null, email: "sam.lee@example.com" }),
    );
    renderRoute("/welcome");
    expect(
      await screen.findByRole("heading", { name: "Welcome, sam.lee" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Name" })).toHaveValue(
      "sam.lee's Money",
    );
  });

  it("is New workspace when you have some", async () => {
    mockApi(shellApi());
    renderRoute("/welcome");
    expect(
      await screen.findByRole("heading", { level: 1, name: "New workspace" }),
    ).toBeInTheDocument();
    expect(document.title).toBe("New workspace · Sensibility");
    // A second one isn't named for you.
    const field = screen.getByRole("textbox", { name: "Name" });
    expect(field).toHaveValue("");
    expect(field).toHaveAttribute("placeholder", "e.g. Personal");
  });
});

describe("welcome, with invites", () => {
  const invites: MyInvite[] = [
    invite({
      id: 7,
      workspace_name: "Test",
      sender_name: "Me",
      role: "editor",
    }),
    invite({
      id: 8,
      workspace_id: 4,
      workspace_name: "Lake house",
      sender_name: "Jordan Swan",
      role: "viewer",
    }),
    invite({ id: 9, workspace_name: "Lapsed", acceptable: false }),
  ];

  it("lists the ones you can accept, with Decline and Join", async () => {
    mockApi(shellApi(NEWCOMER, invites));
    renderRoute("/welcome");
    const card = await screen.findByRole("region", { name: "Invites for you" });
    expect(card).toHaveTextContent(
      /TestMe invited you as an editor · expires Nov \d/,
    );
    expect(card).toHaveTextContent(
      /Lake houseJordan Swan invited you as a viewer · expires Nov \d/,
    );
    expect(card).not.toHaveTextContent("Lapsed");
    for (const name of ["Test", "Lake house"]) {
      expect(
        within(card).getByRole("button", { name: `Join ${name}` }),
      ).toBeInTheDocument();
      expect(
        within(card).getByRole("button", {
          name: `Decline the invite to ${name}`,
        }),
      ).toBeInTheDocument();
    }
    expect(screen.getByText("or", { exact: true })).toBeInTheDocument();
    // Create is secondary when there are invites.
    expect(createButton()).toHaveClass("text-primary");
    expect(createButton()).not.toHaveClass("bg-primary");
  });

  it("joins: into the workspace, with a flash", async () => {
    let me = NEWCOMER;
    let pending = invites;
    const fetchMock = mockApi({
      "GET /api/me": () => ({ body: me }),
      "GET /api/invites": () => ({ body: { invites: pending } }),
      "POST /api/invites/8/accept": () => {
        me = {
          ...NEWCOMER,
          workspaces: [{ id: 4, name: "Lake house", role: "viewer" }],
        };
        pending = pending.filter((i) => i.id !== 8);
        return { body: { workspace_id: 4, role: "viewer" } };
      },
    });
    const { user, router } = renderRoute("/welcome");
    await user.click(
      await screen.findByRole("button", { name: "Join Lake house" }),
    );
    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/workspaces/4"),
    );
    expect(
      await screen.findByText("Joined Lake house as a viewer."),
    ).toBeInTheDocument();
    expect(headers(fetchMock, "/api/invites/8/accept").csrf).toBe(
      "sensibility",
    );
    // The shell knows the new workspace: the picker, not a not-found page.
    expect(
      await screen.findByRole("combobox", { name: "Workspace" }),
    ).toHaveValue("4");
  });

  it("declines: stays here, the invite goes", async () => {
    let pending = invites;
    const fetchMock = mockApi({
      "GET /api/me": { body: NEWCOMER },
      "GET /api/invites": () => ({ body: { invites: pending } }),
      "POST /api/invites/8/decline": () => {
        pending = pending.filter((i) => i.id !== 8);
        return { body: { declined: 8 } };
      },
    });
    const { user, router } = renderRoute("/welcome");
    await user.click(
      await screen.findByRole("button", {
        name: "Decline the invite to Lake house",
      }),
    );
    expect(
      await screen.findByText("Declined the invite to Lake house."),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "Join Lake house" }),
      ).toBeNull(),
    );
    expect(router.state.location.pathname).toBe("/welcome");
    expect(headers(fetchMock, "/api/invites/8/decline").csrf).toBe(
      "sensibility",
    );
  });

  it("shows a refused Join in the invites card", async () => {
    mockApi({
      ...shellApi(NEWCOMER, invites),
      "POST /api/invites/7/accept": {
        status: 400,
        body: { error: "This invite can no longer be accepted" },
      },
    });
    const { user, router } = renderRoute("/welcome");
    await user.click(await screen.findByRole("button", { name: "Join Test" }));
    const card = screen.getByRole("region", { name: "Invites for you" });
    expect(await within(card).findByRole("alert")).toHaveTextContent(
      "This invite can no longer be accepted",
    );
    expect(router.state.location.pathname).toBe("/welcome");
  });
});

describe("creating a workspace", () => {
  it("creates the first one under its default name in one click", async () => {
    const fetchMock = mockApi({
      ...shellApi(NEWCOMER),
      "POST /api/workspaces": {
        status: 201,
        body: { id: 5, name: "Sam's Money", role: "owner" },
      },
    });
    const { user } = renderRoute("/welcome");
    await screen.findByRole("textbox", { name: "Name" });
    await user.click(createButton());
    expect(await screen.findByText("Created Sam's Money.")).toBeInTheDocument();
    expect(headers(fetchMock, "/api/workspaces").body).toEqual({
      name: "Sam's Money",
    });
  });

  it("creates it and goes into it", async () => {
    let me = NEWCOMER;
    const fetchMock = mockApi({
      "GET /api/me": () => ({ body: me }),
      "GET /api/invites": { body: { invites: [] } },
      "POST /api/workspaces": ({ body }) => {
        const name = (body as { name: string }).name.trim();
        me = { ...NEWCOMER, workspaces: [{ id: 5, name, role: "owner" }] };
        return { status: 201, body: { id: 5, name, role: "owner" } };
      },
    });
    const { user, router } = renderRoute("/welcome");
    const field = await screen.findByRole("textbox", { name: "Name" });
    await user.clear(field);
    await user.type(field, " Personal ");
    await user.click(createButton());

    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/workspaces/5"),
    );
    expect(await screen.findByText("Created Personal.")).toBeInTheDocument();
    const sent = headers(fetchMock, "/api/workspaces");
    expect(sent.body).toEqual({ name: " Personal " });
    expect(sent.csrf).toBe("sensibility");
    expect(
      await screen.findByRole("combobox", { name: "Workspace" }),
    ).toHaveValue("5");
  });

  it("keeps a refused name, with the message", async () => {
    mockApi({
      ...shellApi(NEWCOMER),
      "POST /api/workspaces": {
        status: 400,
        body: { error: "Name is required" },
      },
    });
    const { user, router } = renderRoute("/welcome");
    const field = await screen.findByRole("textbox", { name: "Name" });
    await user.clear(field);
    await user.type(field, "  ");
    await user.click(createButton());

    const card = screen
      .getByRole("heading", { name: "Start your own workspace" })
      .closest("section")!;
    expect(await within(card).findByRole("alert")).toHaveTextContent(
      "Name is required",
    );
    expect(field).toHaveValue("  ");
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(field).toHaveFocus();
    expect(router.state.location.pathname).toBe("/welcome");
  });
});

import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type {
  SettingsInvite,
  SettingsMember,
  WorkspaceSettings,
} from "@/api/settings";
import type { Me } from "@/api/shell";
import type { Role } from "@/lib/wording";
import {
  ME,
  mockApi,
  renderRoute,
  shellApi,
  type FakeResponse,
} from "@/test/utils";

const PAGE = "/workspaces/1/settings";
const API = "/api/workspaces/1";

function member(overrides: Partial<SettingsMember>): SettingsMember {
  return {
    user_id: 1,
    name: "Ethan Swan",
    email: "me@example.com",
    display_name: "Ethan Swan",
    role: "owner",
    joined_at: "2026-01-01T00:00:00+00:00",
    you: true,
    removable: false,
    ...overrides,
  };
}

const STRANGER = member({
  user_id: 2,
  name: "Stranger",
  email: "stranger@example.com",
  display_name: "Stranger",
  role: "editor",
  you: false,
  removable: true,
});
const THIRD = member({
  user_id: 3,
  name: null,
  email: "third@example.com",
  display_name: "third@example.com",
  role: "viewer",
  you: false,
  removable: true,
});
const INVITE: SettingsInvite = {
  id: 9,
  email: "sam.lee@example.com",
  role: "editor",
  invited_by: 1,
  sent_by_you: true,
  sender_name: "Ethan Swan",
  // 02:00 UTC on Oct 21 is Oct 20 in Chicago; the test runs in any zone, so
  // the dates are matched loosely.
  created_at: "2026-10-21T12:00:00+00:00",
  expires_at: "2026-11-04T12:00:00+00:00",
  lapsed: false,
};

/** The seeded owner (Ethan, the only owner), Stranger an editor, Third a
 * viewer, and a pending invite from Ethan. */
function ownerSettings(
  overrides: Partial<WorkspaceSettings> = {},
): WorkspaceSettings {
  return {
    id: 1,
    name: "Household",
    role: "owner",
    is_owner: true,
    can_leave: false,
    members: [member({}), STRANGER, THIRD],
    invites: [INVITE],
    invite_ttl_days: 14,
    roles: ["owner", "editor", "viewer"],
    ...overrides,
  };
}

/** The same workspace seen by an editor or a viewer (user 2). */
function readOnlySettings(role: Role): WorkspaceSettings {
  return ownerSettings({
    role,
    is_owner: false,
    can_leave: true,
    members: [
      member({ you: false, removable: false }),
      { ...STRANGER, role, you: true, removable: true },
      { ...THIRD, removable: false },
    ],
    invites: [],
  });
}

function meAs(role: Role): Me {
  return {
    ...ME,
    workspaces: [{ id: 1, name: "Household", role }, ME.workspaces[1]],
  };
}

/** The shell's reads plus the settings, and any writes. `me` and
 * `settings` may be functions, so a write can change what comes next. */
function api(
  {
    me = () => ME,
    settings = () => ownerSettings(),
  }: { me?: () => Me; settings?: () => WorkspaceSettings } = {},
  writes: Record<
    string,
    (request: { body: unknown }) => FakeResponse | Promise<FakeResponse>
  > = {},
) {
  return mockApi({
    ...shellApi(),
    "GET /api/me": () => ({ body: me() }),
    [`GET ${API}/settings`]: () => ({ body: settings() }),
    ...writes,
  });
}

type FetchMock = ReturnType<typeof mockApi>;

/** The request made to `METHOD path`, with its body and headers. */
function sent(fetchMock: FetchMock, method: string, path: string) {
  const call = fetchMock.mock.calls.find(
    ([url, init]) =>
      new URL(String(url), "http://localhost").pathname === path &&
      (init?.method ?? "GET") === method,
  );
  expect(call, `${method} ${path}`).toBeDefined();
  const init = call![1]!;
  return {
    body: typeof init.body === "string" ? JSON.parse(init.body) : undefined,
    headers: init.headers as Record<string, string>,
  };
}

function count(fetchMock: FetchMock, method: string, path: string) {
  return fetchMock.mock.calls.filter(
    ([url, init]) =>
      new URL(String(url), "http://localhost").pathname === path &&
      (init?.method ?? "GET") === method,
  ).length;
}

function expectWrite(
  fetchMock: FetchMock,
  method: string,
  path: string,
  body?: unknown,
) {
  const request = sent(fetchMock, method, path);
  expect(request.body).toEqual(body);
  expect(request.headers["X-Requested-With"]).toBe("sensibility");
}

const heading = () =>
  screen.findByRole("heading", { level: 1, name: "Household settings" });

const people = () =>
  screen.getByRole("heading", { name: "People" }).closest("section")!;

const leaveOrDelete = () =>
  screen.getByRole("region", { name: "Leave or delete" });

describe("settings, as the owner", () => {
  it("shows the name, the people, Leave and Delete", async () => {
    api();
    renderRoute(PAGE);
    await heading();
    expect(document.title).toBe("Settings · Household · Sensibility");
    expect(
      screen.getByText("You're an owner of this workspace."),
    ).toBeInTheDocument();
    expect(screen.getByRole("textbox", { name: "Name" })).toHaveValue(
      "Household",
    );

    const list = within(people());
    expect(list.getByText("3 members · 1 invited")).toBeInTheDocument();
    const rows = list.getAllByRole("listitem");
    expect(rows.map((r) => r.textContent)).toEqual([
      expect.stringContaining("Ethan Swan(you)me@example.com"),
      expect.stringContaining("Strangerstranger@example.com"),
      expect.stringContaining("third@example.comthird@example.com"),
      expect.stringMatching(
        /^SLsam\.lee@example\.com InvitedSent by you Oct 2\d · expires Nov \dEditor$/,
      ),
    ]);
    expect(
      list.getByRole("combobox", { name: "Role for Ethan Swan" }),
    ).toHaveValue("owner");
    expect(
      list.getByRole("combobox", { name: "Role for Stranger" }),
    ).toHaveValue("editor");
    expect(
      list.getByRole("combobox", { name: "Role for third@example.com" }),
    ).toHaveValue("viewer");
    // × asks first; there is none on your own row, as the only owner.
    expect(list.getByRole("link", { name: "Remove Stranger" })).toHaveAttribute(
      "href",
      `${PAGE}?confirm=member-2`,
    );
    expect(
      list.getByRole("link", {
        name: "Revoke the invite to sam.lee@example.com",
      }),
    ).toHaveAttribute("href", `${PAGE}?confirm=invite-9`);
    expect(
      list.queryByRole("link", { name: "Leave Household" }),
    ).not.toBeInTheDocument();
    expect(
      list.getByText(/^No email is sent: tell them yourself/),
    ).toHaveTextContent(
      "they'll see the invite when they log in with that address. Invites expire after 14 days. Viewers look; editors also change data; owners also manage the workspace and its people.",
    );

    const danger = within(leaveOrDelete());
    expect(danger.getByText("Leave Household")).toBeInTheDocument();
    expect(
      danger.getByText(/^You're its only owner, so you can't leave\./),
    ).toBeInTheDocument();
    expect(danger.queryByRole("link", { name: "Leave" })).toBeNull();
    expect(
      danger.getByText(
        "Removes it for all 3 members. Its data is kept and can be restored by an admin.",
      ),
    ).toBeInTheDocument();
    expect(
      danger.getByRole("link", { name: "Delete workspace" }),
    ).toHaveAttribute("href", `${PAGE}?confirm=delete`);
  });

  it("offers Leave when another owner stays", async () => {
    api({ settings: () => ownerSettings({ can_leave: true }) });
    renderRoute(PAGE);
    await heading();
    const danger = within(leaveOrDelete());
    expect(
      danger.getByText(
        "You'll lose access. Another owner stays, so you can leave.",
      ),
    ).toBeInTheDocument();
    expect(danger.getByRole("link", { name: "Leave" })).toHaveAttribute(
      "href",
      `${PAGE}?confirm=leave`,
    );
  });

  it("is its only member", async () => {
    api({
      settings: () => ownerSettings({ members: [member({})], invites: [] }),
    });
    renderRoute(PAGE);
    await heading();
    expect(within(people()).getByText("1 member")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Removes it for you, its only member. Its data is kept and can be restored by an admin.",
      ),
    ).toBeInTheDocument();
  });

  it("says why a lapsed invite cannot be accepted", async () => {
    api({
      settings: () =>
        ownerSettings({
          invites: [
            {
              ...INVITE,
              sent_by_you: false,
              sender_name: "Stranger",
              lapsed: true,
            },
            {
              ...INVITE,
              id: 10,
              email: "x@example.com",
              sent_by_you: false,
              sender_name: null,
            },
          ],
        }),
    });
    renderRoute(PAGE);
    await heading();
    expect(
      screen.getByText(
        /^Sent by Stranger Oct 2\d · lapsed: Stranger is no longer an owner$/,
      ),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/^Sent by a former member Oct 2\d · expires Nov \d$/),
    ).toBeInTheDocument();
  });

  it("renames the workspace", async () => {
    let name = "Household";
    const fetchMock = api(
      {
        me: () => ({
          ...ME,
          workspaces: [{ id: 1, name, role: "owner" }, ME.workspaces[1]],
        }),
        settings: () => ownerSettings({ name }),
      },
      {
        [`PATCH ${API}`]: ({ body }) => {
          name = (body as { name: string }).name.trim();
          return { body: { id: 1, name, role: "owner" } };
        },
      },
    );
    const { user } = renderRoute(PAGE);
    await heading();
    const field = screen.getByRole("textbox", { name: "Name" });
    await user.clear(field);
    await user.type(field, " Home ");
    await user.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("Saved Home.")).toBeInTheDocument();
    expectWrite(fetchMock, "PATCH", API, { name: " Home " });
    expect(
      await screen.findByRole("heading", { level: 1, name: "Home settings" }),
    ).toBeInTheDocument();
    expect(field).toHaveValue("Home");
    // The picker has the new name: `me` was refetched.
    expect(count(fetchMock, "GET", "/api/me")).toBe(2);
    expect(
      screen.getByRole("option", { name: "Home", selected: true }),
    ).toBeInTheDocument();
  });

  it("keeps a refused name, with the message", async () => {
    api(
      {},
      {
        [`PATCH ${API}`]: () => ({
          status: 400,
          body: { error: "Name is required" },
        }),
      },
    );
    const { user } = renderRoute(PAGE);
    await heading();
    const field = screen.getByRole("textbox", { name: "Name" });
    await user.clear(field);
    await user.type(field, "  ");
    await user.click(screen.getByRole("button", { name: "Save" }));

    const general = screen
      .getByRole("heading", { name: "General" })
      .closest("section")!;
    expect(await within(general).findByRole("alert")).toHaveTextContent(
      "Name is required",
    );
    expect(field).toHaveValue("  ");
    expect(field).toHaveAttribute("aria-invalid", "true");
    expect(field).toHaveFocus();
    expect(
      screen.getByRole("heading", { level: 1, name: "Household settings" }),
    ).toBeInTheDocument();
  });

  it("saves a role as soon as it is chosen", async () => {
    let role: Role = "editor";
    const fetchMock = api(
      {
        settings: () =>
          ownerSettings({
            members: [member({}), { ...STRANGER, role }, THIRD],
          }),
      },
      {
        [`PATCH ${API}/members/2`]: ({ body }) => {
          role = (body as { role: Role }).role;
          return { body: { user_id: 2, role } };
        },
      },
    );
    const { user } = renderRoute(PAGE);
    await heading();
    const select = screen.getByRole("combobox", { name: "Role for Stranger" });
    await user.selectOptions(select, "viewer");

    expect(
      await screen.findByText("Stranger is now a viewer."),
    ).toBeInTheDocument();
    expectWrite(fetchMock, "PATCH", `${API}/members/2`, { role: "viewer" });
    expect(select).toHaveValue("viewer");
    expect(count(fetchMock, "GET", "/api/me")).toBe(2);
  });

  it("puts a refused role back, with the message under People", async () => {
    api(
      {},
      {
        [`PATCH ${API}/members/1`]: () => ({
          status: 400,
          body: {
            error:
              "A workspace needs at least one owner. Make someone else an owner first.",
          },
        }),
      },
    );
    const { user } = renderRoute(PAGE);
    await heading();
    const select = screen.getByRole("combobox", {
      name: "Role for Ethan Swan",
    });
    await user.selectOptions(select, "editor");

    expect(await within(people()).findByRole("alert")).toHaveTextContent(
      "A workspace needs at least one owner.",
    );
    await waitFor(() => expect(select).toHaveValue("owner"));
  });

  it("demoting yourself leaves a read-only page", async () => {
    let mine: Role = "owner";
    api(
      {
        me: () => meAs(mine),
        settings: () =>
          mine === "owner"
            ? ownerSettings({ can_leave: true })
            : {
                ...readOnlySettings(mine),
                members: [
                  member({ role: mine, removable: true }),
                  { ...STRANGER, role: "owner" },
                  THIRD,
                ],
              },
      },
      {
        [`PATCH ${API}/members/1`]: ({ body }) => {
          mine = (body as { role: Role }).role;
          return { body: { user_id: 1, role: mine } };
        },
      },
    );
    const { user } = renderRoute(PAGE);
    await heading();
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Role for Ethan Swan" }),
      "editor",
    );
    expect(
      await screen.findByText("You're now an editor."),
    ).toBeInTheDocument();
    expect(
      await screen.findByText("You're an editor of this workspace."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("textbox", { name: "Name" })).toBeNull();
    expect(screen.queryByRole("combobox", { name: /^Role for/ })).toBeNull();
  });

  it("asks in the row, then removes", async () => {
    let members = [member({}), STRANGER, THIRD];
    const fetchMock = api(
      { settings: () => ownerSettings({ members }) },
      {
        [`DELETE ${API}/members/2`]: () => {
          members = [member({}), THIRD];
          return { body: { removed: 2 } };
        },
      },
    );
    const { user, router } = renderRoute(PAGE);
    await heading();
    await user.click(screen.getByRole("link", { name: "Remove Stranger" }));
    expect(router.state.location.search).toBe("?confirm=member-2");

    const confirm =
      within(people()).getByText("Remove Stranger?").parentElement!
        .parentElement!;
    expect(confirm).toHaveTextContent(
      "Remove Stranger? They lose access to Household right away. You can invite them again.",
    );
    expect(within(confirm).getByRole("link", { name: "Keep" })).toHaveFocus();
    await user.click(within(confirm).getByRole("button", { name: "Remove" }));

    expect(await screen.findByText("Removed Stranger.")).toBeInTheDocument();
    expectWrite(fetchMock, "DELETE", `${API}/members/2`);
    expect(router.state.location.search).toBe("");
    await waitFor(() =>
      expect(within(people()).queryByText("Stranger")).toBeNull(),
    );
    expect(within(people()).getByText("2 members · 1 invited")).toBeVisible();
  });

  it("Keep goes back without asking the server", async () => {
    const fetchMock = api();
    const { user, router } = renderRoute(`${PAGE}?confirm=member-2`);
    await heading();
    await user.click(screen.getByRole("link", { name: "Keep" }));
    expect(router.state.location.pathname).toBe(PAGE);
    expect(router.state.location.search).toBe("");
    expect(screen.queryByText("Remove Stranger?")).toBeNull();
    expect(
      fetchMock.mock.calls.every(
        ([, init]) => (init?.method ?? "GET") === "GET",
      ),
    ).toBe(true);
  });

  it("shows a refused removal under People and closes the confirm", async () => {
    api(
      {},
      {
        [`DELETE ${API}/members/2`]: () => ({
          status: 404,
          body: { error: "Member not found" },
        }),
      },
    );
    const { user, router } = renderRoute(`${PAGE}?confirm=member-2`);
    await heading();
    await user.click(screen.getByRole("button", { name: "Remove" }));
    expect(await within(people()).findByRole("alert")).toHaveTextContent(
      "Member not found",
    );
    expect(router.state.location.search).toBe("");
    // Any link in the page starts afresh.
    await user.click(
      await screen.findByRole("link", { name: "Remove Stranger" }),
    );
    expect(within(people()).queryByRole("alert")).toBeNull();
  });

  it("asks in the row, then revokes an invite", async () => {
    let invites = [INVITE];
    const fetchMock = api(
      { settings: () => ownerSettings({ invites }) },
      {
        [`DELETE ${API}/invites/9`]: () => {
          invites = [];
          return { body: { revoked: 9 } };
        },
      },
    );
    const { user, router } = renderRoute(`${PAGE}?confirm=invite-9`);
    await heading();
    expect(
      screen.getByText("Revoke the invite to sam.lee@example.com?")
        .parentElement,
    ).toHaveTextContent("They won't be able to join with it.");
    await user.click(screen.getByRole("button", { name: "Revoke invite" }));

    expect(
      await screen.findByText("Revoked the invite to sam.lee@example.com."),
    ).toBeInTheDocument();
    expectWrite(fetchMock, "DELETE", `${API}/invites/9`);
    expect(router.state.location.search).toBe("");
    await waitFor(() =>
      expect(within(people()).getByText("3 members")).toBeVisible(),
    );
  });

  it("shows a refused revoke under People", async () => {
    api(
      {},
      {
        [`DELETE ${API}/invites/9`]: () => ({
          status: 400,
          body: { error: "This invite has already been resolved" },
        }),
      },
    );
    const { user } = renderRoute(`${PAGE}?confirm=invite-9`);
    await heading();
    await user.click(screen.getByRole("button", { name: "Revoke invite" }));
    expect(await within(people()).findByRole("alert")).toHaveTextContent(
      "already been resolved",
    );
  });

  it("invites with a role, then clears the form", async () => {
    let invites = [INVITE];
    const fetchMock = api(
      { settings: () => ownerSettings({ invites }) },
      {
        [`POST ${API}/invites`]: ({ body }) => {
          const { email, role } = body as { email: string; role: Role };
          invites = [...invites, { ...INVITE, id: 11, email, role }];
          return {
            status: 201,
            body: { id: 11, workspace_id: 1, email: email.toLowerCase(), role },
          };
        },
      },
    );
    const { user } = renderRoute(PAGE);
    await heading();
    const email = screen.getByRole("textbox", { name: "Invite by email" });
    const role = screen.getByRole("combobox", { name: "Role" });
    expect(role).toHaveValue("editor");
    expect(
      within(role)
        .getAllByRole("option")
        .map((o) => o.textContent),
    ).toEqual(["Owner", "Editor", "Viewer"]);
    await user.type(email, "New@example.com");
    await user.selectOptions(role, "owner");
    await user.click(screen.getByRole("button", { name: "Invite" }));

    expect(
      await screen.findByText("Invited new@example.com as an owner."),
    ).toBeInTheDocument();
    expectWrite(fetchMock, "POST", `${API}/invites`, {
      email: "New@example.com",
      role: "owner",
    });
    expect(email).toHaveValue("");
    expect(role).toHaveValue("editor");
    expect(within(people()).getByText("3 members · 2 invited")).toBeVisible();
  });

  it("keeps a refused invite's input, with the message beside the form", async () => {
    api(
      {},
      {
        [`POST ${API}/invites`]: () => ({
          status: 400,
          body: {
            error: "stranger@example.com is already a member of this workspace",
          },
        }),
      },
    );
    const { user } = renderRoute(PAGE);
    await heading();
    const email = screen.getByRole("textbox", { name: "Invite by email" });
    await user.type(email, "stranger@example.com");
    await user.selectOptions(
      screen.getByRole("combobox", { name: "Role" }),
      "viewer",
    );
    await user.click(screen.getByRole("button", { name: "Invite" }));

    const form = screen.getByRole("form", { name: "Invite" });
    expect(await within(form).findByRole("alert")).toHaveTextContent(
      "stranger@example.com is already a member of this workspace",
    );
    expect(email).toHaveValue("stranger@example.com");
    expect(email).toHaveAttribute("aria-invalid", "true");
    expect(email).toHaveFocus();
    expect(screen.getByRole("combobox", { name: "Role" })).toHaveValue(
      "viewer",
    );
  });

  it("leaves, into your oldest remaining workspace", async () => {
    let left = false;
    const fetchMock = api(
      {
        me: () => (left ? { ...ME, workspaces: [ME.workspaces[1]] } : ME),
        settings: () => ownerSettings({ can_leave: true }),
      },
      {
        [`DELETE ${API}/members/1`]: () => {
          left = true;
          return { body: { removed: 1 } };
        },
        "GET /api/workspaces/2/settings": () => ({ body: ownerSettings() }),
      },
    );
    const { user, router } = renderRoute(`${PAGE}?confirm=leave`);
    await heading();
    const danger = within(leaveOrDelete());
    expect(
      danger.getByText("Leave Household?").parentElement,
    ).toHaveTextContent("Leave Household? You'll lose access right away.");
    expect(danger.getByRole("link", { name: "Keep" })).toHaveFocus();
    await user.click(danger.getByRole("button", { name: "Leave workspace" }));

    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/workspaces/2"),
    );
    expect(await screen.findByText("You left Household.")).toBeInTheDocument();
    expectWrite(fetchMock, "DELETE", `${API}/members/1`);
    expect(
      screen.queryByRole("heading", { name: "Page not found" }),
    ).not.toBeInTheDocument();
  });

  it("leaves from your own row", async () => {
    api({
      settings: () =>
        ownerSettings({
          can_leave: true,
          members: [member({ removable: true }), STRANGER],
        }),
    });
    const { user, router } = renderRoute(PAGE);
    await heading();
    await user.click(
      within(people()).getByRole("link", { name: "Leave Household" }),
    );
    expect(router.state.location.search).toBe("?confirm=member-1");
    expect(
      within(people()).getByRole("button", { name: "Leave workspace" }),
    ).toBeInTheDocument();
  });

  it("shows a refused leave in the Leave section", async () => {
    api(
      { settings: () => ownerSettings({ can_leave: true }) },
      {
        [`DELETE ${API}/members/1`]: () => ({
          status: 400,
          body: {
            error:
              "A workspace needs at least one owner. Make someone else an owner first.",
          },
        }),
      },
    );
    const { user, router } = renderRoute(`${PAGE}?confirm=leave`);
    await heading();
    await user.click(screen.getByRole("button", { name: "Leave workspace" }));
    expect(await within(leaveOrDelete()).findByRole("alert")).toHaveTextContent(
      "A workspace needs at least one owner.",
    );
    expect(router.state.location.search).toBe("");
  });

  it("deletes, to the welcome page when nothing is left", async () => {
    let deleted = false;
    const fetchMock = api(
      {
        me: () =>
          deleted
            ? { ...ME, workspaces: [] }
            : { ...ME, workspaces: [ME.workspaces[0]] },
      },
      {
        [`DELETE ${API}`]: () => {
          deleted = true;
          return { body: { deleted: 1 } };
        },
      },
    );
    const { user, router } = renderRoute(`${PAGE}?confirm=delete`);
    await heading();
    expect(
      screen.getByText("Delete Household for all 3 members?").parentElement,
    ).toHaveTextContent(
      "Delete Household for all 3 members? Its data is kept and can be restored by an admin.",
    );
    await user.click(screen.getByRole("button", { name: "Delete workspace" }));

    await waitFor(() =>
      expect(router.state.location.pathname).toBe("/welcome"),
    );
    expect(await screen.findByText("Deleted Household.")).toBeInTheDocument();
    expectWrite(fetchMock, "DELETE", API);
  });

  it("ignores a confirm it cannot act on", async () => {
    api();
    // The only owner cannot leave.
    renderRoute(`${PAGE}?confirm=leave`);
    await heading();
    expect(document.querySelector("[data-slot=confirm]")).toBeNull();
    expect(screen.queryByText("Leave Household?")).toBeNull();
  });
});

describe.each(["editor", "viewer"] as const)("settings, as %s", (role) => {
  const setup = () =>
    api({ me: () => meAs(role), settings: () => readOnlySettings(role) });

  it("is read-only, with Leave", async () => {
    setup();
    renderRoute(PAGE);
    await heading();
    expect(
      screen.getByText(
        `You're a${role === "editor" ? "n" : ""} ${role} of this workspace.`,
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "General" })).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("combobox", { name: /^Role/ })).toBeNull();
    expect(screen.queryByText("Delete Household")).toBeNull();
    expect(screen.queryByText(/invited/)).toBeNull();

    const list = within(people());
    expect(list.getByText("3 members")).toBeInTheDocument();
    // Roles as text, in member order.
    expect(
      list.getAllByText(/^(Owner|Editor|Viewer)$/).map((r) => r.textContent),
    ).toEqual(["Owner", role === "editor" ? "Editor" : "Viewer", "Viewer"]);
    // Your own × is Leave; nobody else's row has one.
    expect(
      list.getAllByRole("link").map((a) => a.getAttribute("aria-label")),
    ).toEqual(["Leave Household"]);
    expect(
      list.getByText(/Only owners can invite people or change roles\.$/),
    ).toHaveTextContent(
      "Viewers look; editors also change data; owners also manage the workspace and its people. Only owners can invite people or change roles.",
    );

    const danger = within(leaveOrDelete());
    expect(
      danger.getByText("You'll lose access until an owner invites you again."),
    ).toBeInTheDocument();
    expect(danger.getByRole("link", { name: "Leave" })).toHaveAttribute(
      "href",
      `${PAGE}?confirm=leave`,
    );
  });

  it("asks before leaving", async () => {
    setup();
    renderRoute(`${PAGE}?confirm=leave`);
    await heading();
    expect(
      within(leaveOrDelete()).getByRole("button", { name: "Leave workspace" }),
    ).toBeInTheDocument();
  });

  it.each(["delete", "member-1", "invite-9"])(
    "ignores the owner's confirm %s",
    async (confirm) => {
      setup();
      renderRoute(`${PAGE}?confirm=${confirm}`);
      await heading();
      expect(document.querySelector("[data-slot=confirm]")).toBeNull();
    },
  );
});

describe("settings that fail to load", () => {
  it("says so", async () => {
    mockApi({
      ...shellApi(),
      [`GET ${API}/settings`]: { status: 500, body: { error: "Boom" } },
    });
    renderRoute(PAGE);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Couldn't load the settings (Boom).",
    );
  });
});

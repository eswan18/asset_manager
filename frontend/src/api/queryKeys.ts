/**
 * Every TanStack Query key in the app, in one place.
 *
 * Conventions:
 * - Everything inside a workspace starts with `["workspaces", id]`
 *   (`queryKeys.workspace(id)`), so one prefix invalidation refreshes a whole
 *   workspace (after a save that touches several pages, or a role change).
 * - Below that, the segment is the API path's next part ("dashboard",
 *   "accounts", "cash-flows", …), then an object of the query's parameters.
 * - Things that are about you rather than a workspace (`me`, your invites)
 *   have their own roots.
 * - A page invalidates the narrowest prefix that covers what its mutation
 *   changed; when in doubt, `queryKeys.workspace(id)`.
 *
 * Page agents: add your keys here (one line each), and your typed fetchers
 * in your own `api/<area>.ts` file, so parallel work doesn't collide.
 */
export const queryKeys = {
  me: () => ["me"] as const,
  myInvites: () => ["invites", "mine"] as const,

  workspace: (workspaceId: number) => ["workspaces", workspaceId] as const,

  dashboard: (workspaceId: number, range: string) =>
    ["workspaces", workspaceId, "dashboard", { range }] as const,

  accounts: (workspaceId: number) =>
    ["workspaces", workspaceId, "accounts"] as const,
  accountsOverview: (workspaceId: number, retired: boolean) =>
    ["workspaces", workspaceId, "accounts", "overview", { retired }] as const,
  account: (workspaceId: number, accountId: number) =>
    ["workspaces", workspaceId, "accounts", accountId] as const,

  cashFlows: (workspaceId: number) =>
    ["workspaces", workspaceId, "cash-flows"] as const,
  cashFlowsOverview: (workspaceId: number, per: string) =>
    ["workspaces", workspaceId, "cash-flows", "overview", { per }] as const,
  cashFlowCategories: (workspaceId: number) =>
    ["workspaces", workspaceId, "cash-flow-categories"] as const,

  members: (workspaceId: number) =>
    ["workspaces", workspaceId, "members"] as const,
  workspaceInvites: (workspaceId: number) =>
    ["workspaces", workspaceId, "invites"] as const,
};

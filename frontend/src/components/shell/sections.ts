/** Which part of a workspace a path is in: the first segment after
 * `/workspaces/{id}` ("" for the dashboard, "accounts", "cash-flows",
 * "cash-flow-categories", "settings"). Mirrors shell_context in
 * web/access.py. */
export function sectionOf(pathname: string, base: string): string {
  if (pathname !== base && !pathname.startsWith(`${base}/`)) return "";
  return pathname.slice(base.length).split("/").filter(Boolean)[0] ?? "";
}

/** The tab a section belongs to (the categories drawer sits over Cash flows). */
export type Tab = "dashboard" | "accounts" | "cash_flows" | "settings" | null;

export function tabOf(section: string): Tab {
  switch (section) {
    case "":
      return "dashboard";
    case "accounts":
      return "accounts";
    case "cash-flows":
    case "cash-flow-categories":
      return "cash_flows";
    case "settings":
      return "settings";
    default:
      return null;
  }
}

/** The same section of another workspace, for the workspace picker (an
 * account's edit drawer maps to the other workspace's Accounts page). */
export function sameSectionIn(workspaceId: number, section: string): string {
  return `/workspaces/${workspaceId}` + (section ? `/${section}` : "");
}

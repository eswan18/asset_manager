import { Outlet, useParams } from "react-router";

import { useMe } from "@/api/shell";
import { NotFound } from "@/routes/not-found";

import { ShellHeader } from "./header";
import { InviteStrips } from "./invite-strip";
import {
  currentWorkspace,
  WorkspaceContext,
  type CurrentWorkspace,
} from "./workspace-context";

/** The page frame for every route: the top bar (and tab bar on phones), the
 * invite strips inside a workspace, then the page. Inside
 * `/workspaces/:workspaceId` it provides `useWorkspace()`; a workspace you
 * are not in (or that doesn't exist) is a not-found page, as the server's
 * 404 would be. */
export function AppShell() {
  const { workspaceId } = useParams();
  const me = useMe();

  if (me.isPending) return null;
  if (me.isError) {
    return (
      <main className="mx-auto max-w-[1160px] px-gutter py-6">
        <div
          role="alert"
          className="rounded-[14px] bg-danger-tint px-[18px] py-3.5 text-[14px] text-danger"
        >
          Couldn't load Sensibility ({me.error.message}). Try reloading the
          page.
        </div>
      </main>
    );
  }

  let workspace: CurrentWorkspace | null = null;
  if (workspaceId !== undefined) {
    const found = me.data.workspaces.find((w) => String(w.id) === workspaceId);
    if (found) workspace = currentWorkspace(found.id, found.name, found.role);
  }
  const missing = workspaceId !== undefined && workspace === null;

  return (
    <WorkspaceContext.Provider value={workspace}>
      <ShellHeader me={me.data} workspace={workspace} />
      <main className="mx-auto max-w-[1160px] px-gutter pt-2 pb-[calc(64px+var(--tabbar-h))]">
        {workspace && <InviteStrips />}
        {missing ? <NotFound /> : <Outlet />}
      </main>
    </WorkspaceContext.Provider>
  );
}

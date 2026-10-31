import { Outlet, useParams } from "react-router";

import { useMe } from "@/api/shell";
import { Card, CardGrid, CardHead } from "@/components/ui/card";
import {
  Loading,
  Skeleton,
  SkeletonRow,
  SkeletonText,
} from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";
import { NotFound } from "@/routes/not-found";

import { ShellHeader } from "./header";
import { InviteStrips } from "./invite-strip";
import { Logo } from "./logo";
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

  if (me.isPending) return <ShellSkeleton />;
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

/** The app's very first paint, before it knows who you are (`/api/me`):
 * the top bar's shape (wordmark, nav, picker, gear, avatar) over a page of
 * cards. Once `me` is cached, every later page skips straight to its own
 * skeleton, inside the real shell. */
export function ShellSkeleton() {
  return (
    <Loading label="Loading Sensibility">
      <div
        className={cn(
          "mx-auto flex max-w-[1160px] items-center justify-between gap-3 px-gutter py-5",
          "phone:min-h-[60px] phone:gap-2 phone:py-2",
        )}
      >
        <Logo className="min-h-11" />
        <Skeleton
          on="bg"
          className="h-12 w-[300px] rounded-full phone:hidden"
        />
        <span className="flex items-center gap-3 phone:gap-2">
          <Skeleton on="bg" className="h-10 w-36 rounded-input phone:hidden" />
          <Skeleton on="bg" className="size-10 rounded-full phone:size-11" />
          <Skeleton on="bg" className="size-10 rounded-full phone:size-11" />
        </span>
      </div>
      <div className="mx-auto max-w-[1160px] px-gutter pt-2">
        <div className="mb-4 flex flex-col gap-1 px-1 py-2">
          <SkeletonText on="bg" className="w-44 text-[32px]" />
          <SkeletonText on="bg" className="w-64 text-[14px]" />
        </div>
        <CardGrid>
          {(["asset", "liability"] as const).map((kind) => (
            <Card key={kind} kind={kind} className="phone:px-4 phone:py-5">
              <CardHead>
                <SkeletonText className="w-28 text-[20px]" />
                <SkeletonText className="w-24 text-[20px]" />
              </CardHead>
              <SkeletonRow name="w-36" />
              <SkeletonRow name="w-28" />
              <SkeletonRow name="w-40" />
            </Card>
          ))}
        </CardGrid>
      </div>
    </Loading>
  );
}

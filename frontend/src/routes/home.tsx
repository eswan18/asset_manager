import { Navigate } from "react-router";

import { useMe } from "@/api/shell";
import { ShellSkeleton } from "@/components/shell/app-shell";

/** `/`: into your oldest workspace, or to the welcome page if you have none.
 * `section` keeps a bare path's page: `/accounts` is `<Home section="/accounts" />`.
 * Until it knows, the shell's skeleton. */
export function Home({ section = "" }: { section?: string }) {
  const me = useMe();
  if (me.isPending) return <ShellSkeleton />;
  if (me.isError) return <Navigate to="/welcome" replace />;
  const oldest = me.data.workspaces[0];
  return (
    <Navigate
      to={oldest ? `/workspaces/${oldest.id}${section}` : "/welcome"}
      replace
    />
  );
}

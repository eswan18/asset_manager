import { Navigate } from "react-router";

import { useMe } from "@/api/shell";

/** `/`: into your oldest workspace, or to the welcome page if you have none
 * (as `GET /` does in web/app.py). */
export function Home() {
  const me = useMe();
  if (me.isPending) return null;
  if (me.isError) return <Navigate to="/welcome" replace />;
  const oldest = me.data.workspaces[0];
  return (
    <Navigate to={oldest ? `/workspaces/${oldest.id}` : "/welcome"} replace />
  );
}

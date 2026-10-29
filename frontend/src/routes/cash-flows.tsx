import { Link, Outlet, useLocation } from "react-router";

import { Button } from "@/components/ui/button";
import {
  useDocumentTitle,
  useWorkspace,
} from "@/components/shell/workspace-context";

import { PagePlaceholder } from "./placeholder";

/** `/workspaces/:workspaceId/cash-flows?per=day|month|year` (Phase B: the
 * Cash flows page). Its drawers (`cash-flows/new`,
 * `cash-flows/:flowId/edit`, `cash-flow-categories`) render in the
 * <Outlet />; each keeps `?per=`. */
export function CashFlowsPage() {
  const workspace = useWorkspace();
  const { search } = useLocation();
  useDocumentTitle(workspace.name);
  return (
    <>
      <PagePlaceholder
        title="Cash flows"
        tools={
          workspace.canEdit && (
            <>
              <Button asChild variant="secondary">
                <Link to={`${workspace.base}/cash-flow-categories${search}`}>
                  Manage categories
                </Link>
              </Button>
              <Button asChild variant="secondary">
                <Link to={`${workspace.base}/cash-flows/new${search}`}>
                  + Add
                </Link>
              </Button>
            </>
          )
        }
      />
      <Outlet />
    </>
  );
}

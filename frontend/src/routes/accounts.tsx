import { Link, Outlet } from "react-router";

import { Button } from "@/components/ui/button";
import {
  useDocumentTitle,
  useWorkspace,
} from "@/components/shell/workspace-context";

import { PagePlaceholder } from "./placeholder";

/** `/workspaces/:workspaceId/accounts` (Phase B: the Accounts page). Its
 * drawers (`accounts/new`, `accounts/:accountId/edit`) render in the
 * <Outlet />, over the page, which stays mounted. */
export function AccountsPage() {
  const workspace = useWorkspace();
  useDocumentTitle(workspace.name);
  return (
    <>
      <PagePlaceholder
        title="Accounts"
        tools={
          workspace.canEdit && (
            <Button asChild variant="secondary">
              <Link to={`${workspace.base}/accounts/new`}>+ Add</Link>
            </Button>
          )
        }
      />
      <Outlet />
    </>
  );
}

import { useParams } from "react-router";

import { Button } from "@/components/ui/button";
import {
  RouteSheet,
  SheetBody,
  SheetClose,
  SheetContent,
  SheetFooter,
  SheetHeader,
} from "@/components/ui/sheet";
import { useWorkspace } from "@/components/shell/workspace-context";

/** `accounts/new` and `accounts/:accountId/edit`, over the Accounts page
 * (Phase B: the account drawer in every state). */
export function AccountDrawer() {
  const workspace = useWorkspace();
  const { accountId } = useParams();
  return (
    <RouteSheet closeTo={`${workspace.base}/accounts`}>
      <SheetContent kind="asset">
        <SheetHeader
          eyebrow="Accounts"
          title={accountId ? "Edit account" : "New account"}
        />
        <SheetBody>
          <p className="text-muted">This drawer is being ported.</p>
        </SheetBody>
        <SheetFooter>
          <SheetClose asChild>
            <Button variant="outline">Cancel</Button>
          </SheetClose>
        </SheetFooter>
      </SheetContent>
    </RouteSheet>
  );
}

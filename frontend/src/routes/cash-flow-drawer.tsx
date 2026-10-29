import { useLocation, useParams } from "react-router";

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

/** `cash-flows/new` and `cash-flows/:flowId/edit`, over the Cash flows page
 * (Phase B: the cash flow drawer and its rates strip). */
export function CashFlowDrawer() {
  const workspace = useWorkspace();
  const { flowId } = useParams();
  const { search } = useLocation();
  return (
    <RouteSheet closeTo={`${workspace.base}/cash-flows${search}`}>
      <SheetContent>
        <SheetHeader
          eyebrow="Cash flows"
          title={flowId ? "Edit cash flow" : "New cash flow"}
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

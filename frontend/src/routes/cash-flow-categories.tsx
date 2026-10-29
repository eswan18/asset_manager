import { useLocation } from "react-router";

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

/** `cash-flow-categories`, over the Cash flows page (Phase B: add, rename,
 * move and delete categories). */
export function CashFlowCategoriesDrawer() {
  const workspace = useWorkspace();
  const { search } = useLocation();
  return (
    <RouteSheet closeTo={`${workspace.base}/cash-flows${search}`}>
      <SheetContent>
        <SheetHeader eyebrow="Cash flows" title="Categories" />
        <SheetBody>
          <p className="text-muted">This drawer is being ported.</p>
        </SheetBody>
        <SheetFooter>
          <SheetClose asChild>
            <Button variant="outline">Done</Button>
          </SheetClose>
        </SheetFooter>
      </SheetContent>
    </RouteSheet>
  );
}

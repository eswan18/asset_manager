import { useSearchParams } from "react-router";

import {
  useDocumentTitle,
  useWorkspace,
} from "@/components/shell/workspace-context";

import { PagePlaceholder } from "./placeholder";

/** `/workspaces/:workspaceId?range=6m|1y|all` (Phase B: the dashboard). */
export function DashboardPage() {
  const workspace = useWorkspace();
  const [params] = useSearchParams();
  useDocumentTitle(workspace.name);
  return (
    <PagePlaceholder title="Dashboard">
      <p className="text-muted">Range: {params.get("range") ?? "1y"}</p>
    </PagePlaceholder>
  );
}

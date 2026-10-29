import {
  useDocumentTitle,
  useWorkspace,
} from "@/components/shell/workspace-context";

import { PagePlaceholder } from "./placeholder";

/** `/workspaces/:workspaceId/settings` (Phase B: settings for owners,
 * editors and viewers). */
export function SettingsPage() {
  const workspace = useWorkspace();
  useDocumentTitle(`Settings · ${workspace.name}`);
  return <PagePlaceholder title="Settings" />;
}

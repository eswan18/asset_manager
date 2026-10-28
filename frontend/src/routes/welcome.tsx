import { useDocumentTitle } from "@/components/shell/workspace-context";

import { PagePlaceholder } from "./placeholder";

/** `/welcome`, outside any workspace (Phase B: your invites and creating a
 * workspace). */
export function WelcomePage() {
  useDocumentTitle("Welcome");
  return <PagePlaceholder title="Welcome" />;
}

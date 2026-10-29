import { EmptyCard } from "@/components/ui/empty-card";
import { useDocumentTitle } from "@/components/shell/workspace-context";

/** Any path the router doesn't know, and a workspace you aren't in. */
export function NotFound() {
  useDocumentTitle("Not found");
  return (
    <EmptyCard
      title="Page not found"
      text="There's nothing here, or it isn't yours to see."
      action={{ label: "Go to your dashboard", to: "/" }}
    />
  );
}

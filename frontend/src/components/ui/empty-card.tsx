import { Link, type To } from "react-router";

import { cn } from "@/lib/utils";

import { Button } from "./button";
import { Card } from "./card";

/** An empty page's card (ui.empty_card): what goes here, then one button to
 * add the first — or, for a viewer, who can add nothing, `viewerNote`.
 * Centered and only as wide as its text, like the welcome page's cards. */
function EmptyCard({
  title,
  text,
  action,
  viewerNote,
  className,
}: {
  title: string;
  text: string;
  action?: { label: string; to: To };
  viewerNote?: string;
  className?: string;
}) {
  return (
    <Card
      className={cn(
        "fade-in mx-auto w-full max-w-[640px] items-start gap-3 p-10 phone:px-6 phone:py-7",
        className,
      )}
    >
      <h1 className="font-display text-[28px] font-semibold tracking-[-0.02em]">
        {title}
      </h1>
      <p className="max-w-[560px] text-muted">{text}</p>
      {action ? (
        <Button asChild variant="primary" size="lg" className="mt-2">
          <Link to={action.to}>{action.label}</Link>
        </Button>
      ) : (
        viewerNote && <p className="max-w-[560px] text-ink">{viewerNote}</p>
      )}
    </Card>
  );
}

export { EmptyCard };

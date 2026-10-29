import type { ReactNode } from "react";

import { Card, CardHead, CardTitle, CardTools } from "@/components/ui/card";

/** Stands in for a page until its Phase B port lands. Delete it with the
 * last placeholder. */
export function PagePlaceholder({
  title,
  tools,
  children,
}: {
  title: string;
  tools?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <Card className="fade-in gap-4">
      <CardHead>
        <CardTitle>{title}</CardTitle>
        {tools && <CardTools>{tools}</CardTools>}
      </CardHead>
      <p className="text-muted">
        This page is being ported to the new frontend. Until then, use the
        current page.
      </p>
      {children}
    </Card>
  );
}

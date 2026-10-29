import * as React from "react";

import { cn } from "@/lib/utils";

type Kind = "asset" | "liability";

const SECTION: Record<Kind, string> = {
  asset: "[--section:var(--asset)]",
  liability: "[--section:var(--liability)]",
};

/** base.html's .card: a surface panel. `kind` colors the head's rule
 * (assets blue, liabilities orange); without it the rule is ink. */
function Card({
  className,
  kind,
  ...props
}: React.ComponentProps<"section"> & { kind?: Kind }) {
  return (
    <section
      data-slot="card"
      className={cn(
        "flex flex-col rounded-card bg-surface p-7",
        kind && SECTION[kind],
        className,
      )}
      {...props}
    />
  );
}

/** The title row: a title, then (optionally) actions and a total, over a 2px
 * rule in the card's section color. */
function CardHead({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-head"
      className={cn(
        "flex items-center justify-between gap-3 border-b-2 border-section pb-3",
        className,
      )}
      {...props}
    />
  );
}

function CardTitle({ className, ...props }: React.ComponentProps<"h2">) {
  return (
    <h2
      data-slot="card-title"
      className={cn("font-display text-[20px] font-semibold", className)}
      {...props}
    />
  );
}

/** The head's right side: actions and/or the total. */
function CardTools({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div className={cn("flex items-center gap-3", className)} {...props} />
  );
}

function CardTotal({ className, ...props }: React.ComponentProps<"span">) {
  return (
    <span
      data-slot="card-total"
      className={cn("font-display text-[20px] font-semibold", className)}
      {...props}
    />
  );
}

/** A category subheading with its subtotal (.group-head). */
function CardGroupHead({
  label,
  total,
  className,
}: {
  label: React.ReactNode;
  total?: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex justify-between pt-[18px] pb-1.5 text-[13px] font-semibold text-muted",
        className,
      )}
    >
      <span>{label}</span>
      {total !== undefined && <span>{total}</span>}
    </div>
  );
}

/** A row: name left, amount right, a hairline between rows (.row). */
function CardRow({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="card-row"
      className={cn(
        "flex min-h-[52px] items-center justify-between gap-3 border-b border-rule py-1 last:border-b-0",
        className,
      )}
      {...props}
    />
  );
}

/** The grid cards sit in (.card-grid). */
function CardGrid({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      className={cn(
        "grid grid-cols-[repeat(auto-fit,minmax(min(100%,420px),1fr))] items-start gap-4",
        className,
      )}
      {...props}
    />
  );
}

export {
  Card,
  CardGrid,
  CardGroupHead,
  CardHead,
  CardRow,
  CardTitle,
  CardTools,
  CardTotal,
};

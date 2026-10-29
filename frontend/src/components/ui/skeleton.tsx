import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Loading placeholders, shaped like what is coming.
 *
 * A `Loading` region holds them: it is `aria-busy`, says what is loading to
 * screen readers (`label`), and fades in only after 150ms (index.css's
 * `skeleton-reveal`), so an answer that comes quickly never flashes a
 * skeleton. That delay is the one flash-avoidance rule: use `Loading`
 * around every skeleton, page or drawer, and nothing blinks.
 *
 *   <Loading label="Loading accounts">
 *     <Card><SkeletonText className="w-40 text-[20px]" /><SkeletonRow /></Card>
 *   </Loading>
 *
 * The blocks are hidden from assistive tech and pulse gently (not under
 * reduced motion). They are spans, so they fit inside headings and labels.
 */
function Loading({
  label,
  className,
  children,
  ...props
}: React.ComponentProps<"div"> & { label: string }) {
  return (
    <div
      data-slot="loading"
      aria-busy="true"
      className={cn("skeleton-reveal", className)}
      {...props}
    >
      <span className="sr-only">{label}</span>
      {children}
    </div>
  );
}

/** A block, in the strong rule's color: half-strength on a card or a drawer
 * (the surface), stronger with `on="bg"`, straight on the page background.
 * (Chip, the obvious choice, all but vanishes on white in light mode.) */
function Skeleton({
  className,
  on = "surface",
  ...props
}: React.ComponentProps<"span"> & { on?: "surface" | "bg" }) {
  return (
    <span
      data-slot="skeleton"
      aria-hidden="true"
      className={cn(
        "skeleton-pulse block rounded-md",
        on === "bg" ? "bg-rule-strong/80" : "bg-rule-strong/50",
        className,
      )}
      {...props}
    />
  );
}

/** A line of text: a bar centred in the line's height. Size it as the text
 * it stands for, with a width: `className="w-48 text-[32px]"`. */
function SkeletonText({
  className,
  on,
}: {
  className?: string;
  on?: "surface" | "bg";
}) {
  return (
    <span
      aria-hidden="true"
      className={cn("flex h-[1.5em] w-32 max-w-full items-center", className)}
    >
      <Skeleton on={on} className="h-[0.7em] w-full rounded-full" />
    </span>
  );
}

/** A card row (CardRow's shape): a name left, an amount right; `input`
 * makes the amount a field, as on the Accounts page. */
function SkeletonRow({
  className,
  input = false,
  name = "w-36",
}: {
  className?: string;
  input?: boolean;
  /** The name's width class, to vary rows. */
  name?: string;
}) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "flex min-h-[52px] items-center justify-between gap-3 border-b border-rule py-1 last:border-b-0",
        className,
      )}
    >
      <SkeletonText className={cn("min-w-0 shrink", name)} />
      {input ? (
        <Skeleton className="h-10 w-[140px] flex-none rounded-input phone:h-11 phone:w-[124px]" />
      ) : (
        <SkeletonText className="w-20 flex-none" />
      )}
    </span>
  );
}

/** A labelled field (Field's shape): the label over a 44px control. */
function SkeletonField({
  className,
  label = "w-20",
}: {
  className?: string;
  /** The label's width class. */
  label?: string;
}) {
  return (
    <span aria-hidden="true" className={cn("flex flex-col gap-1.5", className)}>
      <SkeletonText className={cn("text-[13px]", label)} />
      <Skeleton className="h-11 w-full rounded-input" />
    </span>
  );
}

/** A button (Button's shape): a pill, 44px tall. */
function SkeletonButton({ className }: { className?: string }) {
  return (
    <Skeleton className={cn("h-11 w-24 flex-none rounded-full", className)} />
  );
}

export {
  Loading,
  Skeleton,
  SkeletonButton,
  SkeletonField,
  SkeletonRow,
  SkeletonText,
};

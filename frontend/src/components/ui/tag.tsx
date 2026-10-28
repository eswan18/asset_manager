import * as React from "react";

import { cn } from "@/lib/utils";

/** A small pill beside a name (.tag): "computed", or the estimate mark. */
function Tag({
  className,
  estimate = false,
  ...props
}: React.ComponentProps<"span"> & { estimate?: boolean }) {
  return (
    <span
      data-slot="tag"
      className={cn(
        "inline-flex items-center rounded-full bg-chip px-2 py-px text-[12px] text-muted",
        estimate && "bg-estimate-bg font-semibold text-estimate-fg",
        className,
      )}
      {...props}
    />
  );
}

/** ≈ : the amount is an estimate. */
function EstimateTag(props: React.ComponentProps<"span">) {
  return (
    <Tag estimate title="Estimate" {...props}>
      ≈
    </Tag>
  );
}

/** "computed": the amount comes from a formula. */
function ComputedTag({
  text = "computed",
  ...props
}: React.ComponentProps<"span"> & { text?: string }) {
  return <Tag {...props}>{text}</Tag>;
}

export { ComputedTag, EstimateTag, Tag };

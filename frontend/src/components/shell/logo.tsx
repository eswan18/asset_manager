import { cn } from "@/lib/utils";

import { APP_NAME } from "./workspace-context";

/**
 * The brand lockup: the silver coin (the favicon art, which holds up at this
 * size) and the outlined serif wordmark, both from frontend/public. The
 * wordmark is a mask filled with --ink, so it follows the theme; the coin
 * reads on either. login.html draws the same.
 */
export function Logo({ className }: { className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-2", className)}>
      <img src="/favicon.svg" alt="" className="size-[30px]" />
      <span
        aria-hidden
        className="aspect-[1740/378] h-[21px] bg-ink [mask:url(/wordmark.svg)_center/contain_no-repeat]"
      />
      <span className="sr-only">{APP_NAME}</span>
    </span>
  );
}

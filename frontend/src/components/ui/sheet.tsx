import * as React from "react";
import { Dialog } from "radix-ui";
import { X } from "lucide-react";
import { useNavigate, type To } from "react-router";

import { cn } from "@/lib/utils";

import { SkeletonText } from "./skeleton";

/**
 * The drawer (base.html's .drawer): a form over its page. On desktop it
 * comes in from the right, 500px wide; on phones it is a full-screen sheet
 * that slides up, its footer pinned above the bottom safe area. Escape, the
 * scrim and the ✕ all close it; focus stays inside and the page behind is
 * inert and doesn't scroll (Radix Dialog does both).
 *
 * Drawers are routes. Render a `RouteSheet` from the drawer's route
 * component, with `closeTo` the page it sits over:
 *
 *   <RouteSheet closeTo={`${base}/accounts`}>
 *     <SheetContent kind="asset">
 *       <SheetHeader eyebrow="Assets" title="New account" />
 *       <SheetForm onSubmit={…}>
 *         <SheetBody>…fields (the first with data-autofocus)…</SheetBody>
 *         <SheetFooter>
 *           <SheetClose asChild><Button variant="outline">Cancel</Button></SheetClose>
 *           <Button type="submit" variant="primary">Save</Button>
 *         </SheetFooter>
 *       </SheetForm>
 *     </SheetContent>
 *   </RouteSheet>
 */

const Sheet = Dialog.Root;
const SheetClose = Dialog.Close;

/** Whether the RouteSheet around a SheetContent has already slid one in. */
interface SlideMemory {
  slid: () => boolean;
  markSlid: () => void;
}
const SlidIn = React.createContext<SlideMemory | null>(null);

function slideMemory(): SlideMemory {
  let slid = false;
  return {
    slid: () => slid,
    markSlid: () => {
      slid = true;
    },
  };
}

/** A Sheet that is open while its route is, and closes by navigating to
 * `closeTo` (keep the page's search params in it, e.g. `?per=year`).
 *
 * Opening one never waits for data: render it at once with a `busy`
 * SheetContent (the header you already know, a skeleton body), then, from
 * the same RouteSheet, the real SheetContent once the data is here. The
 * new content takes focus as a freshly opened sheet does (the
 * `data-autofocus` field), and doesn't slide in a second time. */
function RouteSheet({
  closeTo,
  children,
}: {
  closeTo: To;
  children: React.ReactNode;
}) {
  const navigate = useNavigate();
  const [memory] = React.useState(slideMemory);
  return (
    <SlidIn.Provider value={memory}>
      <Sheet
        open
        onOpenChange={(open) => {
          if (!open) navigate(closeTo);
        }}
      >
        {children}
      </Sheet>
    </SlidIn.Provider>
  );
}

const SECTION = {
  asset: "[--section:var(--asset)]",
  liability: "[--section:var(--liability)]",
} as const;

/** Where focus goes when a sheet opens: the element marked `data-autofocus`
 * (the Jinja drawers' `autofocus`, e.g. the Name field), else the sheet
 * itself, so the ✕ doesn't open wearing a focus ring. */
function focusOnOpen(event: Event) {
  event.preventDefault();
  const sheet = event.currentTarget as HTMLElement;
  const target = sheet.querySelector<HTMLElement>("[data-autofocus]") ?? sheet;
  target.focus();
}

function SheetContent({
  className,
  children,
  kind,
  busy = false,
  onOpenAutoFocus = focusOnOpen,
  ...props
}: React.ComponentProps<typeof Dialog.Content> & {
  kind?: keyof typeof SECTION;
  /** Still loading: marked `aria-busy`. Escape, the scrim and the ✕ work
   * as ever. */
  busy?: boolean;
}) {
  const memory = React.useContext(SlidIn);
  // Content that replaces its RouteSheet's loading state is already in.
  const [slide] = React.useState(() => !memory?.slid());
  React.useEffect(() => memory?.markSlid(), [memory]);
  return (
    <Dialog.Portal>
      <Dialog.Overlay
        data-slot="sheet-scrim"
        className="fixed inset-0 z-40 bg-scrim"
      />
      <Dialog.Content
        data-slot="sheet"
        // No description by default; pass aria-describedby to add one.
        aria-describedby={undefined}
        aria-busy={busy || undefined}
        onOpenAutoFocus={onOpenAutoFocus}
        className={cn(
          "fixed top-0 right-0 bottom-0 z-[41] flex w-[min(100%,500px)] flex-col bg-surface shadow-drawer outline-none",
          slide && "drawer-in",
          "phone:bottom-auto phone:left-0 phone:h-dvh phone:w-full phone:shadow-none phone:[--drawer-from:translateY(40px)]",
          kind && SECTION[kind],
          className,
        )}
        {...props}
      >
        {children}
      </Dialog.Content>
    </Dialog.Portal>
  );
}

/** The head: an optional eyebrow over the title, and the ✕. The rule under
 * it takes the content's `kind` color. */
function SheetHeader({
  eyebrow,
  title,
  closeLabel = "Close",
  className,
}: {
  eyebrow?: React.ReactNode;
  title: React.ReactNode;
  closeLabel?: string;
  className?: string;
}) {
  return (
    <div
      data-slot="sheet-head"
      className={cn(
        "flex items-center justify-between gap-3 border-b-2 border-section px-6 py-5",
        "phone:px-gutter phone:pt-[calc(12px+env(safe-area-inset-top,0px))] phone:pb-3",
        className,
      )}
    >
      <div className="flex min-w-0 flex-col">
        {eyebrow && <span className="text-[13px] text-muted">{eyebrow}</span>}
        <Dialog.Title className="font-display text-[22px] leading-tight font-semibold [overflow-wrap:anywhere]">
          {title}
        </Dialog.Title>
      </div>
      <Dialog.Close
        aria-label={closeLabel}
        className="flex h-11 flex-[0_0_44px] cursor-pointer items-center justify-center rounded-full bg-chip text-ink focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-asset"
      >
        <X size={18} aria-hidden="true" />
      </Dialog.Close>
    </div>
  );
}

/** A form spanning body and footer, so the footer's submit stays pinned. */
function SheetForm({ className, ...props }: React.ComponentProps<"form">) {
  return (
    <form
      className={cn("flex min-h-0 flex-1 flex-col", className)}
      {...props}
    />
  );
}

/** The scrolling middle. */
function SheetBody({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="sheet-body"
      className={cn(
        "flex min-h-0 grow flex-col gap-[18px] overflow-y-auto overscroll-contain p-6",
        "phone:px-gutter phone:py-5",
        className,
      )}
      {...props}
    />
  );
}

/** The pinned footer. Its buttons are 44px; on phones they share the row. */
function SheetFooter({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="sheet-foot"
      className={cn(
        "flex shrink-0 justify-end gap-2 border-t border-rule-strong px-6 py-4",
        "phone:px-gutter phone:pt-3 phone:pb-[calc(12px+env(safe-area-inset-bottom,0px))]",
        "[&_[data-slot=button]]:min-h-11 [&_[data-slot=button]]:px-[22px]",
        "phone:[&_[data-slot=button]]:min-w-0 phone:[&_[data-slot=button]]:flex-1 phone:[&_[data-slot=button]]:px-3",
        className,
      )}
      {...props}
    />
  );
}

/** The server's refusal, inside the drawer (.drawer-error). */
function SheetError({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      role="alert"
      className={cn(
        "rounded-xl border border-danger/35 bg-danger/8 px-4 py-3 text-[14px] text-danger",
        className,
      )}
      {...props}
    />
  );
}

/** The title of a sheet whose subject isn't known yet (an edit drawer
 * opened by its URL): a skeleton line, named `label` for screen readers. */
function SheetTitleLoading({ label }: { label: string }) {
  return (
    <>
      <span className="sr-only">{label}</span>
      <SkeletonText className="skeleton-reveal w-48 max-w-full" />
    </>
  );
}

export {
  RouteSheet,
  Sheet,
  SheetBody,
  SheetClose,
  SheetContent,
  SheetError,
  SheetFooter,
  SheetForm,
  SheetHeader,
  SheetTitleLoading,
};

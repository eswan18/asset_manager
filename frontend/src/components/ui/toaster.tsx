import { Toaster as Sonner, toast } from "sonner";
import { X } from "lucide-react";

import { cn } from "@/lib/utils";

/**
 * Flashes (base.html's .flash), shown as toasts: one line of what just
 * happened, with a × to dismiss. Call `flash.success("Saved.")` or
 * `flash.error(message)` from anywhere; `<Toaster />` is mounted once in
 * App. Success is the asset tint with a check; an error is the danger tint
 * and is announced as an alert.
 */

type Kind = "success" | "error";

function Flash({
  kind,
  text,
  onDismiss,
}: {
  kind: Kind;
  text: string;
  onDismiss: () => void;
}) {
  const error = kind === "error";
  return (
    <div
      data-slot="flash"
      data-kind={kind}
      role={error ? "alert" : "status"}
      className={cn(
        "flex w-full items-center justify-between gap-3 rounded-[14px] py-3.5 pr-2 pl-[18px] text-[14px] shadow-menu",
        "phone:pr-1",
        error ? "bg-danger-tint text-danger" : "bg-asset-tint text-ink",
      )}
    >
      <span className="flex items-center gap-2.5">
        {error ? (
          <svg
            className="flex-none"
            width="18"
            height="18"
            viewBox="0 0 20 20"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            aria-hidden="true"
          >
            <circle cx="10" cy="10" r="7" />
            <path d="M10 6v5M10 13.5v.5" />
          </svg>
        ) : (
          <svg
            className="flex-none text-asset"
            width="18"
            height="18"
            viewBox="0 0 20 20"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
            aria-hidden="true"
          >
            <path d="M4 10.5l4 4 8-9" />
          </svg>
        )}
        <span>{text}</span>
      </span>
      <button
        type="button"
        aria-label="Dismiss"
        onClick={onDismiss}
        className={cn(
          "flex size-8 flex-none cursor-pointer items-center justify-center rounded-full bg-transparent phone:size-11",
          "hover:bg-current/10 focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-asset",
          error ? "text-danger" : "text-muted",
        )}
      >
        <X size={14} aria-hidden="true" />
      </button>
    </div>
  );
}

function show(kind: Kind, text: string) {
  return toast.custom(
    (id) => (
      <Flash kind={kind} text={text} onDismiss={() => toast.dismiss(id)} />
    ),
    // Errors stay until dismissed; a success fades on its own.
    { duration: kind === "error" ? Infinity : 5000 },
  );
}

const flash = {
  success: (text: string) => show("success", text),
  error: (text: string) => show("error", text),
};

function Toaster() {
  return (
    <Sonner
      position="top-center"
      offset={16}
      mobileOffset={16}
      toastOptions={{ unstyled: true, className: "w-full" }}
    />
  );
}

export { Flash, flash, Toaster };

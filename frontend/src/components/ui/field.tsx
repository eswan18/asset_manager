import * as React from "react";

import { cn } from "@/lib/utils";

/** Form fields (base.html's .field and friends). Every field is 44px tall
 * and 16px on phones, where iOS would otherwise zoom in on focus. */

const control = [
  "w-full min-w-0 min-h-11 rounded-input border border-rule-strong bg-input px-3",
  "text-[15px] font-normal text-ink phone:text-[16px]",
  "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-asset",
];

/** A labelled field: the label text over its control. */
function Field({
  label,
  className,
  children,
  ...props
}: React.ComponentProps<"label"> & { label: React.ReactNode }) {
  return (
    <label
      className={cn(
        "flex flex-col gap-1.5 text-[13px] font-medium text-muted",
        className,
      )}
      {...props}
    >
      <span>{label}</span>
      {children}
    </label>
  );
}

/** Two fields side by side, down to the narrowest phone (.field-pair). */
function FieldPair({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      className={cn("grid grid-cols-2 gap-3 [&>*]:min-w-0", className)}
      {...props}
    />
  );
}

/** A text input; `num` right-aligns it for amounts. */
function Input({
  className,
  num = false,
  ...props
}: React.ComponentProps<"input"> & { num?: boolean }) {
  return (
    <input
      data-slot="input"
      className={cn(control, num && "text-right", className)}
      {...props}
    />
  );
}

/** A native select: the phone's own picker, which is what thumbs want. */
function Select({ className, ...props }: React.ComponentProps<"select">) {
  return (
    <select data-slot="select" className={cn(control, className)} {...props} />
  );
}

function Textarea({ className, ...props }: React.ComponentProps<"textarea">) {
  return (
    <textarea
      data-slot="textarea"
      className={cn(
        control,
        "min-h-0 resize-y py-2.5 leading-[1.4]",
        className,
      )}
      {...props}
    />
  );
}

/** A checkbox with its label as the 44px target (.check). */
function Check({
  label,
  className,
  ...props
}: Omit<React.ComponentProps<"input">, "type"> & { label: React.ReactNode }) {
  return (
    <label
      className={cn(
        "flex min-h-11 cursor-pointer items-center gap-2.5 font-semibold",
        className,
      )}
    >
      <input
        type="checkbox"
        className="size-[18px] accent-primary"
        {...props}
      />
      {label}
    </label>
  );
}

/** The Accounts page's amount input (.money-input); `edited` marks a staged
 * change. */
function MoneyInput({
  className,
  edited = false,
  ...props
}: React.ComponentProps<"input"> & { edited?: boolean }) {
  return (
    <input
      data-slot="money-input"
      data-edited={edited || undefined}
      inputMode="decimal"
      className={cn(
        "min-h-10 w-[140px] rounded-input border border-rule-strong bg-input px-3 text-right text-ink",
        "phone:min-h-11 phone:text-[16px]",
        "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-asset",
        edited && "border-[1.5px] border-asset bg-asset-tint",
        className,
      )}
      {...props}
    />
  );
}

/** A form's refusal, beside the form (.form-error). In a drawer use
 * SheetError. */
function FormError({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      role="alert"
      className={cn(
        "rounded-xl border border-danger/35 bg-danger/8 px-3.5 py-2.5 text-[14px] text-danger",
        className,
      )}
      {...props}
    />
  );
}

export {
  Check,
  Field,
  FieldPair,
  FormError,
  Input,
  MoneyInput,
  Select,
  Textarea,
};

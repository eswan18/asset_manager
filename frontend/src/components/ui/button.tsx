import * as React from "react";
import { Slot } from "radix-ui";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

/** base.html's .btn and its variants. 40px tall pills (44px on phones);
 * `size="lg"` is the 44px form used in drawer footers, invite strips and
 * empty cards. `asChild` renders a router <Link> (or <a>) as the button. */
const buttonVariants = cva(
  [
    "inline-flex items-center justify-center gap-1.5 min-h-10 px-[18px] phone:min-h-11",
    "rounded-full border border-transparent text-[14px] font-medium no-underline cursor-pointer",
    "disabled:cursor-not-allowed disabled:opacity-50",
    "focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-asset",
  ],
  {
    variants: {
      variant: {
        primary: "bg-primary text-on-primary font-semibold",
        secondary: "bg-chip text-ink",
        outline: "bg-transparent text-ink border-rule-strong",
        "primary-outline":
          "bg-transparent text-primary border-primary font-semibold",
        danger: "bg-transparent text-danger",
        "danger-outline": "bg-transparent text-danger border-danger",
        "danger-solid": "bg-danger text-on-primary font-semibold",
      },
      size: {
        default: "",
        lg: "min-h-11 px-[22px]",
      },
    },
    defaultVariants: { variant: "secondary", size: "default" },
  },
);

type ButtonProps = React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & { asChild?: boolean };

function Button({
  className,
  variant,
  size,
  asChild = false,
  type,
  ...props
}: ButtonProps) {
  const Comp = asChild ? Slot.Root : "button";
  return (
    <Comp
      data-slot="button"
      // A plain <button> never submits a form by accident.
      type={asChild ? type : (type ?? "button")}
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  );
}

export { Button, buttonVariants, type ButtonProps };

import { ToggleGroup } from "radix-ui";

import { cn } from "@/lib/utils";

interface Option<T extends string> {
  value: T;
  label: string;
}

/** base.html's .toggle: a pill of options, one always chosen (the dashboard's
 * range, the cash flows period). Controlled: keep `value` in the URL's search
 * params and update them in `onValueChange`. `fill` stretches it across its
 * container in equal segments (the phone layout of both toggles). */
function SegmentedControl<T extends string>({
  label,
  options,
  value,
  onValueChange,
  fill = false,
  className,
}: {
  label: string;
  options: readonly Option<T>[];
  value: T;
  onValueChange: (value: T) => void;
  fill?: boolean;
  className?: string;
}) {
  return (
    <ToggleGroup.Root
      type="single"
      aria-label={label}
      value={value}
      // Radix lets a click on the chosen option clear it; a toggle here
      // always has one.
      onValueChange={(next) => next && onValueChange(next as T)}
      className={cn(
        "flex gap-0.5 rounded-full bg-chip p-[3px]",
        fill && "w-full",
        className,
      )}
    >
      {options.map((option) => (
        <ToggleGroup.Item
          key={option.value}
          value={option.value}
          className={cn(
            "inline-flex min-h-9 cursor-pointer items-center rounded-full border-0 bg-transparent px-3.5 text-[14px] text-muted",
            "phone:min-h-11 phone:justify-center",
            "data-[state=on]:bg-surface data-[state=on]:font-semibold data-[state=on]:text-ink data-[state=on]:shadow-pill",
            "focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-asset",
            fill && "flex-1 justify-center",
          )}
        >
          {option.label}
        </ToggleGroup.Item>
      ))}
    </ToggleGroup.Root>
  );
}

export { SegmentedControl };

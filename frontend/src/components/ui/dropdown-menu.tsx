import * as React from "react";
import { DropdownMenu as Menu } from "radix-ui";

import { cn } from "@/lib/utils";

/** A menu panel under its trigger (base.html's .user-menu-panel): a
 * surface card, 220px or wider, aligned to the trigger's right edge. On
 * phones it is a full-width card between the gutters. Closes on Escape, a
 * click outside, or choosing an item. */
const DropdownMenu = Menu.Root;
const DropdownMenuTrigger = Menu.Trigger;
const DropdownMenuGroup = Menu.Group;

function DropdownMenuContent({
  className,
  sideOffset = 8,
  align = "end",
  ...props
}: React.ComponentProps<typeof Menu.Content>) {
  return (
    <Menu.Portal>
      <Menu.Content
        data-slot="dropdown-menu"
        sideOffset={sideOffset}
        align={align}
        collisionPadding={16}
        className={cn(
          "z-[35] flex min-w-[220px] flex-col gap-3 rounded-[14px] border border-rule-strong bg-surface p-4 shadow-menu outline-none",
          "phone:w-[calc(100vw-2*var(--gutter))]",
          "data-[state=open]:animate-in data-[state=open]:fade-in-0",
          className,
        )}
        {...props}
      />
    </Menu.Portal>
  );
}

/** A menu item. With `asChild`, wrap a Button or link so it keeps its look;
 * the keyboard highlight draws the focus ring. */
function DropdownMenuItem({
  className,
  ...props
}: React.ComponentProps<typeof Menu.Item>) {
  return (
    <Menu.Item
      data-slot="dropdown-menu-item"
      className={cn(
        "outline-none data-[highlighted]:outline-2 data-[highlighted]:outline-offset-2 data-[highlighted]:outline-asset",
        className,
      )}
      {...props}
    />
  );
}

/** Text in the menu that isn't an action (who you're logged in as). */
function DropdownMenuLabel({
  className,
  ...props
}: React.ComponentProps<typeof Menu.Label>) {
  return (
    <Menu.Label
      className={cn("flex flex-col [overflow-wrap:anywhere]", className)}
      {...props}
    />
  );
}

export {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
};

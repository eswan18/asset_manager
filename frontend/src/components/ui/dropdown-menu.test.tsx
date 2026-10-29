import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "./dropdown-menu";

function Menu({ onPick }: { onPick: () => void }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger>Open</DropdownMenuTrigger>
      <DropdownMenuContent>
        <DropdownMenuLabel>me@example.com</DropdownMenuLabel>
        <DropdownMenuItem onSelect={onPick}>New workspace</DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

describe("DropdownMenu", () => {
  it("opens from its trigger and closes after a choice", async () => {
    const onPick = vi.fn();
    const user = userEvent.setup();
    render(<Menu onPick={onPick} />);
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Open" }));
    const menu = screen.getByRole("menu", { name: "Open" });
    expect(menu).toHaveTextContent("me@example.com");
    expect(menu).toHaveClass("bg-surface", "border-rule-strong");

    await user.click(screen.getByRole("menuitem", { name: "New workspace" }));
    expect(onPick).toHaveBeenCalled();
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });

  it("closes on Escape", async () => {
    const user = userEvent.setup();
    render(<Menu onPick={() => {}} />);
    await user.click(screen.getByRole("button", { name: "Open" }));
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("menu")).not.toBeInTheDocument();
  });
});

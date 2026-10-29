import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { Button } from "./button";

describe("Button", () => {
  it("is a non-submitting secondary button by default", () => {
    render(<Button>Discard</Button>);
    const button = screen.getByRole("button", { name: "Discard" });
    expect(button).toHaveAttribute("type", "button");
    expect(button).toHaveClass("bg-chip", "text-ink", "rounded-full");
  });

  it("takes the variants of .btn-*", () => {
    render(
      <>
        <Button variant="primary">Save</Button>
        <Button variant="outline">Cancel</Button>
        <Button variant="danger-solid">Delete</Button>
      </>,
    );
    expect(screen.getByRole("button", { name: "Save" })).toHaveClass(
      "bg-primary",
      "text-on-primary",
    );
    expect(screen.getByRole("button", { name: "Cancel" })).toHaveClass(
      "border-rule-strong",
    );
    expect(screen.getByRole("button", { name: "Delete" })).toHaveClass(
      "bg-danger",
    );
  });

  it("renders its child as the button with asChild", () => {
    render(
      <Button asChild variant="outline">
        <a href="/logout">Log out</a>
      </Button>,
    );
    const link = screen.getByRole("link", { name: "Log out" });
    expect(link).toHaveAttribute("href", "/logout");
    expect(link).not.toHaveAttribute("type");
    expect(link).toHaveClass("border-rule-strong");
  });

  it("can submit when asked", () => {
    render(<Button type="submit">Go</Button>);
    expect(screen.getByRole("button")).toHaveAttribute("type", "submit");
  });

  it("shows a write in flight with busy: a spinner, and disabled", () => {
    const { rerender } = render(<Button busy>Save</Button>);
    const button = screen.getByRole("button", { name: "Save" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
    expect(button.querySelector("[data-slot=spinner]")).not.toBeNull();

    rerender(<Button>Save</Button>);
    expect(button).toBeEnabled();
    expect(button).not.toHaveAttribute("aria-busy");
    expect(button.querySelector("[data-slot=spinner]")).toBeNull();
  });

  it("stays disabled when asked, busy or not", () => {
    render(<Button disabled>Save</Button>);
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });
});

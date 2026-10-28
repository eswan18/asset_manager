import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  Card,
  CardGroupHead,
  CardHead,
  CardRow,
  CardTitle,
  CardTotal,
} from "./card";

describe("Card", () => {
  it("lays out a titled card with a total, colored by kind", () => {
    render(
      <Card kind="liability" aria-label="Liabilities card">
        <CardHead>
          <CardTitle>Liabilities</CardTitle>
          <CardTotal>$500.00</CardTotal>
        </CardHead>
        <CardGroupHead label="Credit cards" total="$500.00" />
        <CardRow>Card</CardRow>
      </Card>,
    );
    const card = screen.getByRole("region", { name: "Liabilities card" });
    expect(card).toHaveClass("bg-surface", "rounded-card");
    expect(card.className).toContain("[--section:var(--liability)]");
    expect(
      screen.getByRole("heading", { level: 2, name: "Liabilities" }),
    ).toBeInTheDocument();
    expect(screen.getAllByText("$500.00")).toHaveLength(2);
    expect(screen.getByText("Credit cards")).toBeInTheDocument();
  });

  it("has an ink rule without a kind", () => {
    render(<Card aria-label="Plain" />);
    expect(
      screen.getByRole("region", { name: "Plain" }).className,
    ).not.toContain("--section");
  });
});

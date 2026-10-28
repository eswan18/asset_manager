import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { renderWithProviders } from "@/test/utils";

import { EmptyCard } from "./empty-card";

describe("EmptyCard", () => {
  it("offers one way to add the first thing", () => {
    renderWithProviders(
      <EmptyCard
        title="No cash flows yet"
        text="Add your income and expenses."
        action={{
          label: "+ Add cash flow",
          to: "/workspaces/1/cash-flows/new",
        }}
        viewerNote="unused"
      />,
    );
    expect(
      screen.getByRole("heading", { level: 1, name: "No cash flows yet" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "+ Add cash flow" }),
    ).toHaveAttribute("href", "/workspaces/1/cash-flows/new");
    expect(screen.queryByText("unused")).not.toBeInTheDocument();
  });

  it("tells a viewer instead", () => {
    renderWithProviders(
      <EmptyCard
        title="No accounts yet"
        text="Accounts hold balances."
        viewerNote="An editor hasn't added any yet."
      />,
    );
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(
      screen.getByText("An editor hasn't added any yet."),
    ).toBeInTheDocument();
  });
});

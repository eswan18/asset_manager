import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ComputedTag, EstimateTag } from "./tag";

describe("tags", () => {
  it("marks an estimate with ≈", () => {
    render(<EstimateTag />);
    const tag = screen.getByTitle("Estimate");
    expect(tag).toHaveTextContent("≈");
    expect(tag).toHaveClass("bg-estimate-bg", "text-estimate-fg");
  });

  it("says computed", () => {
    render(<ComputedTag />);
    expect(screen.getByText("computed")).toHaveClass("bg-chip", "text-muted");
  });
});

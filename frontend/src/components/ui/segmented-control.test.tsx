import { useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SegmentedControl } from "./segmented-control";

const RANGES = [
  { value: "6m", label: "6M" },
  { value: "1y", label: "1Y" },
  { value: "all", label: "All" },
] as const;

function Range({ onChange }: { onChange: (value: string) => void }) {
  const [value, setValue] = useState<"6m" | "1y" | "all">("1y");
  return (
    <SegmentedControl
      label="Range"
      options={RANGES}
      value={value}
      onValueChange={(next) => {
        setValue(next);
        onChange(next);
      }}
    />
  );
}

describe("SegmentedControl", () => {
  it("marks the chosen option and changes on click", async () => {
    const onChange = vi.fn();
    render(<Range onChange={onChange} />);
    expect(
      screen.getByRole("radiogroup", { name: "Range" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "1Y" })).toHaveAttribute(
      "data-state",
      "on",
    );

    await userEvent.click(screen.getByRole("radio", { name: "All" }));

    expect(onChange).toHaveBeenCalledWith("all");
    expect(screen.getByRole("radio", { name: "All" })).toHaveAttribute(
      "data-state",
      "on",
    );
    expect(screen.getByRole("radio", { name: "1Y" })).toHaveAttribute(
      "data-state",
      "off",
    );
  });

  it("never clears: clicking the chosen option does nothing", async () => {
    const onChange = vi.fn();
    render(<Range onChange={onChange} />);
    await userEvent.click(screen.getByRole("radio", { name: "1Y" }));
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole("radio", { name: "1Y" })).toHaveAttribute(
      "data-state",
      "on",
    );
  });
});

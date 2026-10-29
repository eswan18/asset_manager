import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { toast } from "sonner";
import { afterEach, describe, expect, it } from "vitest";

import { flash, Toaster } from "./toaster";

afterEach(() => {
  act(() => {
    toast.dismiss();
  });
});

describe("flash", () => {
  it("shows a success as a status with the asset tint", async () => {
    render(<Toaster />);
    act(() => {
      flash.success("Saved the snapshot.");
    });
    const status = await screen.findByRole("status");
    expect(status).toHaveTextContent("Saved the snapshot.");
    expect(status).toHaveClass("bg-asset-tint");
  });

  it("shows an error as an alert, dismissed by its ×", async () => {
    render(<Toaster />);
    act(() => {
      flash.error("Couldn't save.");
    });
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveClass("bg-danger-tint", "text-danger");

    await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));

    await waitFor(
      () =>
        expect(screen.queryByText("Couldn't save.")).not.toBeInTheDocument(),
      { timeout: 3000 },
    );
  });
});

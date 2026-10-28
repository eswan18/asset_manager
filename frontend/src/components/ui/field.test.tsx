import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  Check,
  Field,
  FormError,
  Input,
  MoneyInput,
  Select,
  Textarea,
} from "./field";

describe("fields", () => {
  it("label their controls and are 16px on phones", () => {
    render(
      <>
        <Field label="Name">
          <Input defaultValue="Checking" />
        </Field>
        <Field label="Amount">
          <Input num inputMode="decimal" />
        </Field>
        <Field label="Unit">
          <Select defaultValue="month">
            <option value="month">month</option>
          </Select>
        </Field>
        <Field label="Notes">
          <Textarea />
        </Field>
      </>,
    );
    const name = screen.getByLabelText("Name");
    expect(name).toHaveValue("Checking");
    expect(name).toHaveClass("min-h-11", "phone:text-[16px]", "bg-input");
    expect(screen.getByLabelText("Amount")).toHaveClass("text-right");
    expect(screen.getByLabelText("Unit")).toHaveValue("month");
    expect(screen.getByLabelText("Notes").tagName).toBe("TEXTAREA");
  });

  it("checks by its label", () => {
    render(<Check label="Estimate" defaultChecked />);
    expect(screen.getByRole("checkbox", { name: "Estimate" })).toBeChecked();
  });

  it("marks an edited amount", () => {
    render(
      <>
        <MoneyInput aria-label="Checking" edited />
        <MoneyInput aria-label="Savings" />
      </>,
    );
    const edited = screen.getByRole("textbox", { name: "Checking" });
    expect(edited).toHaveAttribute("inputmode", "decimal");
    expect(edited).toHaveAttribute("data-edited");
    expect(edited).toHaveClass("border-asset", "bg-asset-tint");
    expect(
      screen.getByRole("textbox", { name: "Savings" }),
    ).not.toHaveAttribute("data-edited");
  });

  it("shows a refusal as an alert", () => {
    render(<FormError>That name is taken</FormError>);
    expect(screen.getByRole("alert")).toHaveTextContent("That name is taken");
  });
});

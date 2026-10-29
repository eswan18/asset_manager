import { describe, expect, it } from "vitest";

import {
  amountIn,
  formatAmount,
  formatChange,
  formatDollars,
  formatMoney,
  money,
  normalized,
  readAmount,
  shortDate,
  snapshotLine,
} from "./amounts";
import { toFixedText } from "./decimal";

describe("readAmount", () => {
  it.each([
    ["1500", "1500"],
    ["$1,234.56", "1234.56"],
    [" -17.44 ", "-17.44"],
    ["+5", "5"],
    ["(17.44)", "-17.44"],
    ["(1,000)", "-1000"],
    [".5", ".5"],
  ])("reads %j as %s", (raw, text) => {
    const reading = readAmount(raw);
    expect(reading.kind).toBe("number");
    if (reading.kind === "number") expect(reading.text).toBe(text);
  });

  it("tells blank from not a number", () => {
    expect(readAmount("  ")).toEqual({ kind: "blank" });
    expect(readAmount("abc")).toEqual({ kind: "invalid" });
    expect(readAmount("1.2.3")).toEqual({ kind: "invalid" });
    expect(amountIn("abc")).toBeNull();
    expect(toFixedText(amountIn("$2")!)).toBe("2");
  });
});

describe("normalized", () => {
  it("compares amounts, not text", () => {
    expect(normalized("1500")).toBe(normalized("1,500.00"));
    expect(normalized("500.00")).toBe(normalized("$500"));
    expect(normalized("1000.005")).toBe("1000.01");
    expect(normalized(" abc ")).toBe("abc");
    expect(normalized("")).toBe("");
  });
});

describe("formatting", () => {
  it("formats fields, money, changes and dollars", () => {
    expect(formatAmount(money("1500"))).toBe("1,500.00");
    expect(formatAmount(money("-1234567.8"))).toBe("-1,234,567.80");
    expect(formatMoney(money("165233.26"))).toBe("$165,233.26");
    expect(formatMoney(money("-17.44"))).toBe("-$17.44");
    expect(formatMoney(money("0"))).toBe("$0.00");
    expect(formatChange(money("500"))).toBe("+$500.00");
    expect(formatChange(money("-500"))).toBe("-$500.00");
    expect(formatChange(money("0"))).toBe("$0.00");
    expect(formatDollars(money("82386.74"))).toBe("$82,387");
    expect(formatDollars(money("-0.5"))).toBe("-$1");
  });
});

describe("dates", () => {
  it("shows the year unless it is this year's", () => {
    expect(shortDate("2026-09-01")).toBe("Sep 1, 2026");
    expect(shortDate("2026-09-01", "2026-10-28")).toBe("Sep 1");
    expect(shortDate("2025-12-31", "2026-01-02")).toBe("Dec 31, 2025");
  });

  // test_web.py's test_snapshot_line.
  it("says what a save writes and when one last ran", () => {
    const head = "Saving writes today's snapshot, Oct 26, 2026.";
    expect(snapshotLine("2026-10-26", null)).toBe(`${head} Nothing saved yet.`);
    expect(snapshotLine("2026-10-26", "2026-10-26")).toBe(
      `${head} Last saved today; saving again replaces it.`,
    );
    expect(snapshotLine("2026-10-26", "2026-10-24")).toBe(
      `${head} Last saved Oct 24.`,
    );
    expect(snapshotLine("2026-10-26", "2025-12-31")).toBe(
      `${head} Last saved Dec 31, 2025.`,
    );
    expect(snapshotLine("2027-01-02", "2026-09-01")).toBe(
      "Saving writes today's snapshot, Jan 2, 2027. Last saved Sep 1, 2026.",
    );
  });
});

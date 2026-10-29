import { describe, expect, it } from "vitest";

import {
  axisMoney,
  dateDomain,
  dateTicks,
  dayValue,
  longDate,
  money,
  moneyScale,
  shortDate,
  signedMoney,
  signedPercent,
} from "./dashboard";

// The vectors are tests/test_dashboard.py's, for the same helpers.

describe("money", () => {
  it.each([
    ["412380", "$412,380"],
    ["412380.49", "$412,380"],
    ["412380.50", "$412,381"],
    ["0", "$0"],
    ["-0.4", "$0"],
    ["-1200", "−$1,200"],
    ["1234567.89", "$1,234,568"],
    // As the API sends them: two places, and half up away from zero.
    ["12300.25", "$12,300"],
    ["-0.50", "−$1"],
    ["999.50", "$1,000"],
  ])("%s -> %s", (amount, expected) => {
    expect(money(amount)).toBe(expected);
  });
});

describe("signedMoney", () => {
  it.each([
    ["6140", "+$6,140"],
    ["-1200", "−$1,200"],
    ["0", "$0"],
    ["0.4", "$0"],
    ["-0.4", "$0"],
    ["1500.25", "+$1,500"],
  ])("%s -> %s", (amount, expected) => {
    expect(signedMoney(amount)).toBe(expected);
  });
});

describe("signedPercent", () => {
  it.each([
    ["1.5", "+1.5%"],
    ["1.46", "+1.5%"],
    ["-0.3", "−0.3%"],
    ["0", "0.0%"],
    ["0.04", "0.0%"],
    ["-0.04", "0.0%"],
    ["12", "+12.0%"],
    ["13.9", "+13.9%"],
    ["0.0", "0.0%"],
  ])("%s -> %s", (percent, expected) => {
    expect(signedPercent(percent)).toBe(expected);
  });
});

describe("dates", () => {
  it("are short, with the year only when it differs", () => {
    expect(shortDate("2026-09-04", "2026-10-24")).toBe("Sep 4");
    expect(shortDate("2025-09-24", "2026-10-24")).toBe("Sep 24, 2025");
    expect(longDate("2026-10-04")).toBe("Oct 4, 2026");
  });
});

describe("the chart's axes", () => {
  it("spans the snapshots, or the month before a lone one", () => {
    expect(dateDomain(["2026-01-01", "2026-10-24"])).toEqual([
      dayValue("2026-01-01"),
      dayValue("2026-10-24"),
    ]);
    expect(dateDomain(["2026-09-27"])).toEqual([
      dayValue("2026-08-28"),
      dayValue("2026-09-28"),
    ]);
  });

  it("puts dollar ticks on round steps from zero", () => {
    expect(moneyScale([410700, 184950, 225750]).ticks).toEqual([
      0, 100000, 200000, 300000, 400000,
    ]);
    expect(moneyScale([180265, 15032]).ticks).toEqual([
      0, 50000, 100000, 150000,
    ]);
    const { domain } = moneyScale([410700]);
    expect(domain[0]).toBe(0);
    expect(domain[1]).toBeGreaterThan(410700);
    // Below zero, the range starts at the lowest value.
    const negative = moneyScale([-20000, 50000]);
    expect(negative.domain[0]).toBe(-20000);
    expect(negative.ticks[0]).toBe(-20000);
    expect(moneyScale([0, 0]).ticks).toEqual([0]);
  });

  it.each([
    [0, "$0"],
    [50000, "$50k"],
    [1500000, "$1.5M"],
    [400000, "$400k"],
    [2500, "$2.5k"],
    [-20000, "−$20k"],
    [750, "$750"],
  ])("labels %d as %s", (value, expected) => {
    expect(axisMoney(value)).toBe(expected);
  });

  it("ticks month starts over months", () => {
    const year: [number, number] = [
      dayValue("2025-12-14"),
      dayValue("2026-10-24"),
    ];
    expect(dateTicks(year, 6).map((t) => t.label)).toEqual([
      "Jan 2026",
      "Mar 2026",
      "May 2026",
      "Jul 2026",
      "Sep 2026",
    ]);
    expect(dateTicks(year, 4).map((t) => t.label)).toEqual([
      "Jan 2026",
      "Apr 2026",
      "Jul 2026",
      "Oct 2026",
    ]);
  });

  it("ticks Sundays over a few weeks, the first with its year", () => {
    const ticks = dateTicks(dateDomain(["2026-09-27"]), 6);
    expect(ticks.map((t) => t.label)).toEqual([
      "Aug 30",
      "Sep 6",
      "Sep 13",
      "Sep 20",
      "Sep 27",
    ]);
    expect(ticks.map((t) => t.sub)).toEqual([
      "2026",
      undefined,
      undefined,
      undefined,
      undefined,
    ]);
  });

  it("ticks every day over a few days", () => {
    const ticks = dateTicks(
      [dayValue("2026-10-20"), dayValue("2026-10-24")],
      6,
    );
    expect(ticks.map((t) => t.label)).toEqual([
      "Oct 20",
      "Oct 21",
      "Oct 22",
      "Oct 23",
      "Oct 24",
    ]);
  });
});

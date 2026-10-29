import { describe, expect, it } from "vitest";

import {
  amountCents,
  categoryMeta,
  deleteWhy,
  flowEyebrow,
  formRates,
  money,
  parseFlowForm,
  parsePeriod,
  type FlowForm,
} from "./cash-flows";

describe("money", () => {
  // tests/test_cash_flows_page.py's test_money.
  it.each([
    ["1234.5", {}, "$1,234.50"],
    ["-1234.5", {}, "−$1,234.50"],
    ["0", { sign: true }, "$0.00"],
    ["6853.33", { sign: true }, "+$6,853.33"],
    ["-12", { sign: true }, "−$12.00"],
    ["82239.5", { cents: false }, "$82,240"],
    ["-0.4", { cents: false }, "$0"],
    ["-101284.29", { cents: false }, "−$101,284"],
    ["0.00", {}, "$0.00"],
  ])("%s %o -> %s", (amount, options, text) => {
    expect(money(amount, options)).toBe(text);
  });
});

describe("parsePeriod", () => {
  it.each([
    ["day", "day"],
    ["month", "month"],
    ["year", "year"],
    ["fortnight", "month"],
    ["", "month"],
    [null, "month"],
  ])("%s -> %s", (value, period) => {
    expect(parsePeriod(value)).toBe(period);
  });
});

describe("formRates", () => {
  const dashes = null;

  // TestFormRates in tests/test_cash_flow_drawers.py.
  it("matches rates()", () => {
    expect(formRates("100", "1", "week")).toEqual({
      perDay: "$14.29",
      perMonth: "$434.52",
      perYear: "$5,214.29",
    });
  });

  it("rounds the amount to cents first, as a save does", () => {
    // 0.005 a day saves as 0.01, so a year is 3.65, not 1.83.
    expect(formRates("0.005", "1", "day")?.perYear).toBe("$3.65");
  });

  it("takes money text", () => {
    expect(formRates("$1,200", "2", "year")?.perYear).toBe("$600.00");
  });

  it("shows the largest amounts", () => {
    expect(formRates("9999999999999.99", "1000", "month")).not.toBeNull();
  });

  // tests/browser/test_spa_cash_flows.py's cases, which it checks against
  // the service's arithmetic.
  it.each([
    ["100", "1", "week", ["$14.29", "$434.52", "$5,214.29"]],
    ["5100", "2", "week", ["$364.29", "$11,080.36", "$132,964.29"]],
    ["$1,200", "2", "year", ["$1.64", "$50.00", "$600.00"]],
    ["1234567.89", "1", "year", ["$3,382.38", "$102,880.66", "$1,234,567.89"]],
    ["0.005", "1", "day", ["$0.01", "$0.30", "$3.65"]],
    ["0.004", "1", "day", ["$0.00", "$0.00", "$0.00"]],
    ["0.06", "1", "year", ["$0.00", "$0.01", "$0.06"]],
    [".5", "1", "year", ["$0.00", "$0.04", "$0.50"]],
    ["5.", "1", "year", ["$0.01", "$0.42", "$5.00"]],
    [
      "9999999999999.99",
      "1000",
      "day",
      ["$10,000,000,000.00", "$304,166,666,666.67", "$3,650,000,000,000.00"],
    ],
    ["", "1", "month", dashes],
    ["abc", "1", "month", dashes],
    ["-5", "1", "month", dashes],
    ["1e3", "1", "month", dashes],
    ["NaN", "1", "month", dashes],
    [".", "1", "month", dashes],
    ["10000000000000", "1", "month", dashes],
    ["5", "0", "month", dashes],
    ["5", "1001", "month", dashes],
    ["5", "1.5", "month", dashes],
    ["5", "", "month", dashes],
    ["5", "1", "fortnight", dashes],
  ])("%s every %s %s", (amount, every, unit, want) => {
    const rates = formRates(amount, every, unit);
    expect(
      rates && [rates.perDay, rates.perMonth, rates.perYear],
    ).toStrictEqual(want);
  });

  // The browser test's random cases (random.Random(20261026)), with what
  // the server's arithmetic answered for each.
  it.each([
    ["29.689", "3", "year", ["$0.03", "$0.82", "$9.90"]],
    [
      "9092469.091",
      "1",
      "year",
      ["$24,910.87", "$757,705.76", "$9,092,469.09"],
    ],
    ["346304.349", "6", "month", ["$1,897.56", "$57,717.39", "$692,608.70"]],
    [
      "45850850.708",
      "12",
      "day",
      ["$3,820,904.23", "$116,219,170.20", "$1,394,630,042.43"],
    ],
    ["6118.508", "1000", "week", ["$0.87", "$26.59", "$319.04"]],
    [
      "17325282.789",
      "13",
      "year",
      ["$3,651.27", "$111,059.51", "$1,332,714.06"],
    ],
    ["28535.772", "365", "year", ["$0.21", "$6.52", "$78.18"]],
    [
      "5411928.291",
      "2",
      "month",
      ["$88,963.20", "$2,705,964.15", "$32,471,569.74"],
    ],
    ["155537.433", "12", "month", ["$426.13", "$12,961.45", "$155,537.43"]],
    [
      "49460673.478",
      "12",
      "week",
      ["$588,817.54", "$17,909,866.89", "$214,918,402.62"],
    ],
    ["2.562", "6", "week", ["$0.06", "$1.85", "$22.25"]],
    ["7799.706", "6", "day", ["$1,299.95", "$39,540.20", "$474,482.36"]],
    [
      "6594889.114",
      "13",
      "month",
      ["$16,678.33", "$507,299.16", "$6,087,589.95"],
    ],
    [
      "11507472.686",
      "365",
      "week",
      ["$4,503.90", "$136,993.72", "$1,643,924.67"],
    ],
    ["57.689", "3", "year", ["$0.05", "$1.60", "$19.23"]],
    ["56.285", "7", "day", ["$8.04", "$244.59", "$2,935.12"]],
    ["761809.097", "1000", "month", ["$25.05", "$761.81", "$9,141.71"]],
    ["93853.735", "52", "day", ["$1,804.88", "$54,898.42", "$658,781.06"]],
    [
      "1341228.303",
      "1",
      "month",
      ["$44,095.18", "$1,341,228.30", "$16,094,739.60"],
    ],
    [
      "337597994.082",
      "1000",
      "month",
      ["$11,099.11", "$337,597.99", "$4,051,175.93"],
    ],
    ["0.514", "1", "day", ["$0.51", "$15.51", "$186.15"]],
    ["803160.664", "3", "year", ["$733.48", "$22,310.02", "$267,720.22"]],
    [
      "409961.504",
      "1",
      "week",
      ["$58,565.93", "$1,781,380.33", "$21,376,563.93"],
    ],
    ["56.292", "365", "month", ["$0.01", "$0.15", "$1.85"]],
    [
      "58485778.959",
      "3",
      "month",
      ["$640,940.04", "$19,495,259.65", "$233,943,115.84"],
    ],
    ["50145.461", "13", "year", ["$10.57", "$321.45", "$3,857.34"]],
    [
      "484856767.774",
      "2",
      "week",
      ["$34,632,626.27", "$1,053,409,049.02", "$12,640,908,588.29"],
    ],
    [
      "349434.979",
      "2",
      "day",
      ["$174,717.49", "$5,314,323.65", "$63,771,883.85"],
    ],
    [
      "49805074.729",
      "12",
      "week",
      ["$592,917.56", "$18,034,575.67", "$216,414,908.05"],
    ],
    ["39606.762", "365", "month", ["$3.57", "$108.51", "$1,302.14"]],
    [
      "814377188.305",
      "3",
      "month",
      ["$8,924,681.52", "$271,459,062.77", "$3,257,508,753.24"],
    ],
    ["738867.711", "13", "year", ["$155.72", "$4,736.33", "$56,835.98"]],
    [
      "26202225.914",
      "365",
      "month",
      ["$2,360.12", "$71,786.92", "$861,443.04"],
    ],
    [
      "5390756.872",
      "3",
      "month",
      ["$59,076.79", "$1,796,918.96", "$21,563,027.48"],
    ],
    [
      "11371275.218",
      "13",
      "month",
      ["$28,757.70", "$874,713.48", "$10,496,561.74"],
    ],
    [
      "856773340.428",
      "3",
      "year",
      ["$782,441.41", "$23,799,259.46", "$285,591,113.48"],
    ],
    ["81516.460", "12", "week", ["$970.43", "$29,517.37", "$354,208.43"]],
    [
      "3671070.199",
      "3",
      "month",
      ["$40,230.91", "$1,223,690.07", "$14,684,280.80"],
    ],
    ["133640.692", "3", "month", ["$1,464.56", "$44,546.90", "$534,562.76"]],
    ["8075173.739", "365", "month", ["$727.36", "$22,123.76", "$265,485.16"]],
  ])("%s every %s %s (random)", (amount, every, unit, want) => {
    const rates = formRates(amount, every, unit);
    expect(rates && [rates.perDay, rates.perMonth, rates.perYear]).toEqual(
      want,
    );
  });

  it("reads cents as a save rounds them", () => {
    expect(amountCents("1,045.505")).toBe(104551n);
    expect(amountCents("$ 12")).toBe(1200n);
    expect(amountCents("-1")).toBeNull();
  });
});

describe("parseFlowForm", () => {
  const form = (changes: Partial<FlowForm> = {}): FlowForm => ({
    name: "Gym",
    direction: "expense",
    amount: "45",
    every: "1",
    unit: "month",
    categoryId: "",
    isEstimate: false,
    description: "",
    ...changes,
  });

  it("reads the fields", () => {
    expect(
      parseFlowForm(
        form({
          amount: "$1,045.505",
          every: " 2 ",
          unit: "week",
          categoryId: "7",
          isEstimate: true,
          description: " Monthly pass ",
        }),
      ),
    ).toEqual({
      fields: {
        name: "Gym",
        direction: "expense",
        amount: "1045.505",
        every: 2,
        unit: "week",
        category_id: 7,
        description: " Monthly pass ",
        is_estimate: true,
      },
    });
  });

  it.each([
    ["5.", "5"],
    [".5", "0.5"],
    ["-5", "-5"],
    ["-.25", "-0.25"],
    ["007", "007"],
  ])("sends %s as %s", (amount, sent) => {
    expect(parseFlowForm(form({ amount }))).toMatchObject({
      fields: { amount: sent },
    });
  });

  it("sends no category as null", () => {
    expect(parseFlowForm(form())).toMatchObject({
      fields: { category_id: null },
    });
  });

  // TestCreate's messages that come from the form rather than the service.
  it.each([
    [{ amount: "(5)" }, "Amount must be a number"],
    [{ amount: "abc" }, "Amount must be a number"],
    [{ amount: "" }, "Amount must be a number"],
    [{ amount: "NaN" }, "Amount must be a number"],
    [{ amount: "1e3" }, "Amount must be a number"],
    [{ amount: "12.345.6" }, "Amount must be a number"],
    [
      { every: "1.5" },
      "Every must be a whole number, e.g. 2 for every 2 weeks",
    ],
    [{ every: "-2" }, "Every must be a whole number, e.g. 2 for every 2 weeks"],
    [{ every: "" }, "Every must be a whole number, e.g. 2 for every 2 weeks"],
    [{ direction: "sideways" }, "Choose income or expense"],
    [{ unit: "fortnight" }, "Choose day, week, month or year"],
    [{ categoryId: "food" }, "Choose a category from the list"],
  ])("refuses %o: %s", (changes, error) => {
    expect(parseFlowForm(form(changes))).toEqual({ error });
  });

  it("checks the choices before the amount, as the server does", () => {
    expect(parseFlowForm(form({ amount: "abc", every: "x" }))).toEqual({
      error: "Every must be a whole number, e.g. 2 for every 2 weeks",
    });
  });
});

describe("flowEyebrow", () => {
  it.each([
    [true, "expense", "Food", "Edit expense · Food"],
    [true, "income", "Work", "Edit income · Work"],
    [false, "expense", undefined, "New expense"],
    [false, "income", undefined, "New income"],
  ] as const)("%s %s %s -> %s", (editing, direction, category, text) => {
    expect(flowEyebrow(editing, direction, category)).toBe(text);
  });
});

describe("categoryMeta", () => {
  // TestCategoriesDrawer's meta lines.
  it.each([
    [
      { count: 1, expenses: null, income: "11080.36" },
      "month",
      "1 flow · income $11,080.36/mo",
    ],
    [
      { count: 2, expenses: "2710.00", income: null },
      "month",
      "2 flows · $2,710.00/mo",
    ],
    [
      { count: 2, expenses: "32520.00", income: null },
      "year",
      "2 flows · $32,520.00/yr",
    ],
    [{ count: 1, expenses: "3.95", income: null }, "day", "1 flow · $3.95/day"],
    [
      { count: 3, expenses: "1132.14", income: "100.00" },
      "month",
      "3 flows · $1,132.14/mo · income $100.00/mo",
    ],
    [{ count: 0, expenses: null, income: null }, "month", "No flows yet"],
  ] as const)("%o per %s -> %s", (row, period, text) => {
    expect(categoryMeta(row, period)).toBe(text);
  });
});

describe("deleteWhy", () => {
  it.each([
    [2, "2 flows. They move to Uncategorized; nothing else is deleted."],
    [1, "1 flow. It moves to Uncategorized; nothing else is deleted."],
    [0, "It has no flows; nothing else is deleted."],
  ])("%s", (count, text) => {
    expect(deleteWhy(count)).toBe(text);
  });
});

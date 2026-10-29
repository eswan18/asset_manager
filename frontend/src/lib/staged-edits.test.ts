import { afterEach, describe, expect, it, vi } from "vitest";

import { formatMoney } from "./amounts";
import { parseDec } from "./decimal";
import {
  amountKey,
  basisKey,
  clearStaged,
  collectSnapshot,
  evaluatePage,
  isDirty,
  readStaged,
  STORAGE_KEY,
  writeStaged,
  type Field,
  type FieldKey,
  type PageAccount,
} from "./staged-edits";

// The browser tests' `seeded` workspace: Checking, Schwab, a card, and a
// 15% tax on Schwab's gain over $82,386.74.
const ACCOUNTS: PageAccount[] = [
  {
    id: 1,
    name: "Checking",
    type: "asset",
    group: "uncategorized",
    formula: null,
    inputIds: [],
  },
  {
    id: 2,
    name: "Schwab",
    type: "asset",
    group: "uncategorized",
    formula: null,
    inputIds: [],
  },
  {
    id: 3,
    name: "Card",
    type: "liability",
    group: "credit_cards",
    formula: null,
    inputIds: [],
  },
  {
    id: 4,
    name: "Cap gains tax",
    type: "liability",
    group: "tax_liability",
    formula: { rate: parseDec("0.15")!, costBasis: parseDec("82386.74")! },
    inputIds: [2],
  },
];

const FIELDS: Field[] = [
  {
    key: "amount:1",
    kind: "amount",
    accountId: 1,
    label: "Amount for Checking",
    initial: "1,000.00",
  },
  {
    key: "amount:2",
    kind: "amount",
    accountId: 2,
    label: "Amount for Schwab",
    initial: "179,265.00",
  },
  {
    key: "amount:3",
    kind: "amount",
    accountId: 3,
    label: "Amount for Card",
    initial: "500.00",
  },
  {
    key: "basis:4",
    kind: "basis",
    accountId: 4,
    label: "Cost basis for Cap gains tax",
    initial: "82,386.74",
  },
];

function valuesWith(edits: Partial<Record<FieldKey, string>> = {}) {
  return (key: FieldKey) =>
    edits[key] ?? FIELDS.find((f) => f.key === key)!.initial;
}

const money = (value: Parameters<typeof formatMoney>[0] | null | undefined) =>
  value ? formatMoney(value) : null;

describe("evaluatePage", () => {
  it("adds up the page as loaded", () => {
    const result = evaluatePage(ACCOUNTS, valuesWith());
    expect(money(result.amounts.get(4))).toBe("$14,531.74");
    expect(money(result.totals.asset)).toBe("$180,265.00");
    expect(money(result.totals.liability)).toBe("$15,031.74");
    expect(money(result.net)).toBe("$165,233.26");
    expect(money(result.subtotals.get("liability:tax_liability"))).toBe(
      "$14,531.74",
    );
  });

  it("follows an input and the basis", () => {
    // test_computed_account_follows_its_input_and_basis.
    const tax = (edits: Partial<Record<FieldKey, string>>) =>
      money(evaluatePage(ACCOUNTS, valuesWith(edits)).amounts.get(4));
    expect(tax({ "amount:2": "200000" })).toBe("$17,641.99");
    expect(tax({ "amount:2": "200000", "basis:4": "100,000" })).toBe(
      "$15,000.00",
    );
    expect(tax({ "amount:2": "200000", "basis:4": "(1,000)" })).toBe(
      "$30,150.00",
    );
    expect(tax({ "amount:2": "200000", "basis:4": "abc" })).toBeNull();
    expect(tax({ "amount:2": "200000", "basis:4": "" })).toBe("$30,000.00");
    expect(tax({ "amount:2": "" })).toBeNull();
    const result = evaluatePage(
      ACCOUNTS,
      valuesWith({ "amount:2": "200000", "basis:4": "" }),
    );
    expect(money(result.net)).toBe("$170,500.00");
    expect(money(result.totals.liability)).toBe("$30,500.00");
  });

  it("leaves out what has no amount, and rounds as a save would", () => {
    const result = evaluatePage(
      ACCOUNTS,
      valuesWith({ "amount:1": "", "amount:3": "0.005" }),
    );
    expect(result.amounts.get(1)).toBeNull();
    expect(money(result.amounts.get(3))).toBe("$0.01");
    expect(money(result.totals.asset)).toBe("$179,265.00");
  });
});

describe("isDirty", () => {
  it("compares amounts, not text", () => {
    expect(isDirty(FIELDS[0], "1000")).toBe(false);
    expect(isDirty(FIELDS[0], "$1,000.00")).toBe(false);
    expect(isDirty(FIELDS[0], "1500")).toBe(true);
    expect(isDirty(FIELDS[0], "")).toBe(true);
  });
});

describe("collectSnapshot", () => {
  it("sends every amount and basis as cleaned text", () => {
    const result = collectSnapshot(
      FIELDS,
      valuesWith({ "amount:1": "$1,234.5", "basis:4": "(100)" }),
    );
    expect(result.problem).toBeNull();
    expect(result.body).toEqual({
      values: { 1: "1234.5", 2: "179265.00", 3: "500.00" },
      cost_bases: { 4: "-100" },
    });
  });

  it("sends a blank basis as zero", () => {
    expect(
      collectSnapshot(FIELDS, valuesWith({ "basis:4": " " })).body?.cost_bases,
    ).toEqual({ 4: "0" });
  });

  it("refuses a blank amount", () => {
    expect(collectSnapshot(FIELDS, valuesWith({ "amount:2": "" }))).toEqual({
      body: null,
      problem: {
        key: "amount:2",
        message: "Every account needs an amount before saving.",
      },
    });
  });

  it("names a field that is not a number, amounts before bases", () => {
    expect(
      collectSnapshot(FIELDS, valuesWith({ "basis:4": "abc", "amount:3": "x" }))
        .problem,
    ).toEqual({ key: "amount:3", message: "Amount for Card isn't a number." });
    expect(
      collectSnapshot(FIELDS, valuesWith({ "basis:4": "abc" })).problem,
    ).toEqual({
      key: "basis:4",
      message: "Cost basis for Cap gains tax isn't a number.",
    });
  });
});

describe("storage", () => {
  afterEach(() => vi.unstubAllGlobals());

  function fakeStorage() {
    const items = new Map<string, string>();
    vi.stubGlobal("sessionStorage", {
      getItem: (k: string) => items.get(k) ?? null,
      setItem: (k: string, v: string) => items.set(k, v),
      removeItem: (k: string) => items.delete(k),
    });
    return items;
  }

  it("keeps only the dirty fields", () => {
    const items = fakeStorage();
    writeStaged(FIELDS, valuesWith({ "amount:1": "1500", "amount:3": "500" }));
    expect(JSON.parse(items.get(STORAGE_KEY)!)).toEqual({
      [amountKey(1)]: "1500",
    });
    expect(readStaged()).toEqual({ "amount:1": "1500" });
    clearStaged();
    expect(readStaged()).toEqual({});
    expect(basisKey(4)).toBe("basis:4");
  });

  it("never throws without storage", () => {
    vi.stubGlobal("sessionStorage", {
      getItem: () => {
        throw new Error("denied");
      },
      setItem: () => {
        throw new Error("denied");
      },
      removeItem: () => {
        throw new Error("denied");
      },
    });
    expect(readStaged()).toEqual({});
    expect(() => writeStaged(FIELDS, valuesWith())).not.toThrow();
    expect(() => clearStaged()).not.toThrow();
  });

  it("ignores what isn't an object", () => {
    const items = fakeStorage();
    items.set(STORAGE_KEY, "garbage");
    expect(readStaged()).toEqual({});
  });
});

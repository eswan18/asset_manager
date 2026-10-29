/** The vectors are tests/test_formulas.py's (compute_snapshot) and
 * tests/test_account_drawer.py's TestFormulaPreview (formula_preview), plus
 * the browser test's live-line cases. */
import { describe, expect, it } from "vitest";

import { parseDec, toFixedText, type Dec } from "./decimal";
import {
  computeSnapshot,
  evaluate,
  formatPercent,
  formulaPreview,
  MissingValueError,
  parseAmount,
  parseFormula,
  quantizeCents,
  type FormulaAccount,
} from "./formulas";

const d = (text: string): Dec => parseDec(text)!;
const fixed = (value: Dec | undefined) =>
  value === undefined ? undefined : toFixedText(value);

function asset(id: number, name: string): FormulaAccount {
  return { id, name, formula: null, inputIds: [] };
}

function computed(
  id: number,
  name: string,
  rate: string,
  basis: string,
  inputIds: number[],
): FormulaAccount {
  return {
    id,
    name,
    formula: { rate: d(rate), costBasis: d(basis) },
    inputIds,
  };
}

const values = (entries: [number, string][]) =>
  new Map(entries.map(([id, v]) => [id, d(v)]));

describe("computeSnapshot", () => {
  it("rounds half up to cents", () => {
    expect(fixed(quantizeCents(d("10.005")))).toBe("10.01");
    expect(fixed(quantizeCents(d("-17.436")))).toBe("-17.44");
  });

  it("passes plain values through, quantized", () => {
    const result = computeSnapshot(
      [asset(1, "Savings")],
      values([[1, "10.005"]]),
    );
    expect(fixed(result.get(1))).toBe("10.01");
  });

  it("matches the sheet: rate × (input − basis)", () => {
    const result = computeSnapshot(
      [
        asset(1, "Schwab"),
        computed(2, "Cap Gains Tax", "0.15", "70634.00", [1]),
      ],
      values([[1, "163202.77"]]),
    );
    expect(fixed(result.get(1))).toBe("163202.77");
    expect(fixed(result.get(2))).toBe("13885.32");
  });

  it("sums multiple inputs", () => {
    const result = computeSnapshot(
      [
        asset(1, "401k A"),
        asset(2, "401k B"),
        computed(3, "Deferred Tax", "0.32", "0", [1, 2]),
      ],
      values([
        [1, "100"],
        [2, "50"],
      ]),
    );
    expect(fixed(result.get(3))).toBe("48.00");
  });

  it("allows a negative result", () => {
    const result = computeSnapshot(
      [
        asset(1, "Fidelity"),
        computed(2, "Cap Gains Tax", "0.15", "1472.00", [1]),
      ],
      values([[1, "1355.76"]]),
    );
    expect(fixed(result.get(2))).toBe("-17.44");
  });

  it("names a plain account with no value", () => {
    expect(() => computeSnapshot([asset(1, "Savings")], new Map())).toThrow(
      new MissingValueError("Savings"),
    );
  });

  it("names the input a formula is missing", () => {
    expect(() =>
      computeSnapshot(
        [asset(1, "Schwab"), computed(2, "Cap Gains Tax", "0.15", "0", [1])],
        new Map(),
      ),
    ).toThrow(/Schwab/);
  });

  it("ignores extra values", () => {
    const result = computeSnapshot(
      [asset(1, "Savings")],
      values([
        [1, "5"],
        [9, "1"],
      ]),
    );
    expect([...result.keys()]).toEqual([1]);
    expect(fixed(result.get(1))).toBe("5.00");
  });

  it("matches the definition on many vectors", () => {
    // test_proportional_matches_definition, with a seeded generator:
    // rates in 0..1 to six places, amounts within ±1,000,000 to cents,
    // checked against integer arithmetic in millionths of a cent.
    let seed = 20261028;
    const next = (n: number) => {
      seed = (seed * 1103515245 + 12345) % 2 ** 31;
      return seed % n;
    };
    const cents = () => BigInt(next(200_000_001) - 100_000_000);
    for (let run = 0; run < 500; run++) {
      const rateMicro = BigInt(next(1_000_001));
      const basis = cents();
      const inputs = Array.from({ length: 1 + next(5) }, cents);
      const accounts = [
        ...inputs.map((_, i) => asset(i + 1, `A${i}`)),
        {
          id: 99,
          name: "L",
          formula: {
            rate: { n: rateMicro, s: 6 },
            costBasis: { n: basis, s: 2 },
          },
          inputIds: inputs.map((_, i) => i + 1),
        },
      ];
      const result = computeSnapshot(
        accounts,
        new Map(inputs.map((c, i) => [i + 1, { n: c, s: 2 }])),
      );
      const exact = rateMicro * (inputs.reduce((a, b) => a + b, 0n) - basis);
      const magnitude = exact < 0n ? -exact : exact;
      let rounded = magnitude / 1_000_000n;
      if ((magnitude % 1_000_000n) * 2n >= 1_000_000n) rounded += 1n;
      const expected = exact < 0n ? -rounded : rounded;
      expect(result.get(99)).toEqual({ n: expected, s: 2 });
    }
  });
});

describe("evaluate", () => {
  it("is null while an input has no amount", () => {
    const formula = { rate: d("0.15"), costBasis: d("0") };
    expect(evaluate(formula, [d("5"), null])).toBeNull();
    expect(evaluate(formula, [d("5"), undefined])).toBeNull();
    expect(fixed(evaluate(formula, [d("100"), d("50")])!)).toBe("22.50");
  });
});

describe("parseFormula", () => {
  it("reads the rate in percent and the basis as money", () => {
    const formula = parseFormula(" 15 ", "$82,386.74");
    expect(fixed(formula.rate)).toBe("0.150000");
    expect(fixed(formula.costBasis)).toBe("82386.74");
    expect(fixed(parseFormula("32.5", "").costBasis)).toBe("0");
    expect(fixed(parseFormula("10", "(1,000)").costBasis)).toBe("-1000.00");
  });

  it.each([
    ["", "", "Rate must be a number, e.g. 15 for 15%"],
    ["abc", "", "Rate must be a number, e.g. 15 for 15%"],
    ["-5", "", "Rate must be zero or more"],
    ["15", "x", "'x' is not a number"],
    ["15", "10000000000000", "10000000000000 is too large"],
  ])("refuses rate %j basis %j", (rate, basis, message) => {
    expect(() => parseFormula(rate, basis)).toThrow(message);
  });

  it("formats the rate back", () => {
    expect(formatPercent(parseFormula("15", "").rate)).toBe("15");
    expect(formatPercent(parseFormula("32.5", "").rate)).toBe("32.5");
    expect(formatPercent(parseFormula("12.3456", "").rate)).toBe("12.3456");
  });

  it("parses amounts like the service", () => {
    expect(fixed(parseAmount("$1,000.005"))).toBe("1000.01");
    expect(fixed(parseAmount("(17.44)"))).toBe("-17.44");
  });
});

describe("formulaPreview", () => {
  const amounts = (entries: [number, string][]) => values(entries);

  it("shows rate × (inputs − basis)", () => {
    expect(
      formulaPreview("15", "82,386.74", [1], amounts([[1, "179265.00"]])),
    ).toEqual({ text: "15% × ($179,265 − $82,387)", value: "$14,531.74" });
  });

  it("sums every input", () => {
    expect(
      formulaPreview(
        "10",
        "",
        [1, 2],
        amounts([
          [1, "100"],
          [2, "50.50"],
        ]),
      ),
    ).toEqual({ text: "10% × ($151 − $0)", value: "$15.05" });
  });

  it("rounds half up like a save", () => {
    // 0.5 × 0.05 = 0.025: a save stores 0.03, so the preview does too.
    expect(formulaPreview("50", "", [1], amounts([[1, "0.05"]]))?.value).toBe(
      "$0.03",
    );
  });

  it("goes negative below the basis", () => {
    expect(formulaPreview("10", "500", [1], amounts([[1, "100"]]))).toEqual({
      text: "10% × ($100 − $500)",
      value: "-$40.00",
    });
  });

  it("reads negative inputs as negative dollars", () => {
    expect(formulaPreview("10", "", [1], amounts([[1, "-50"]]))).toEqual({
      text: "10% × (-$50 − $0)",
      value: "-$5.00",
    });
  });

  it("has no value while an input has no saved amount", () => {
    expect(formulaPreview("15", "", [1, 2], amounts([[1, "5"]]))?.value).toBe(
      "—",
    );
  });

  it.each([
    ["", "", [1]],
    ["abc", "", [1]],
    ["-5", "", [1]],
    ["15", "x", [1]],
    ["15", "", []],
  ])("shows nothing for rate %j basis %j inputs %j", (rate, basis, ids) => {
    expect(formulaPreview(rate, basis, ids, amounts([[1, "5"]]))).toBeNull();
  });

  it("follows the live line in the browser test", () => {
    const schwab = amounts([
      [1, "179265.00"],
      [2, "1000.00"],
    ]);
    expect(formulaPreview("20", "82,386.74", [1], schwab)).toEqual({
      text: "20% × ($179,265 − $82,387)",
      value: "$19,375.65",
    });
    // The basis rounds to cents first.
    expect(formulaPreview("20", "$1,000.005", [1], schwab)?.value).toBe(
      "$35,653.00",
    );
    expect(formulaPreview("20", "", [1, 2], schwab)).toEqual({
      text: "20% × ($180,265 − $0)",
      value: "$36,053.00",
    });
    expect(formulaPreview("20", "(100)", [1, 2], schwab)?.text).toBe(
      "20% × ($180,265 − -$100)",
    );
  });
});

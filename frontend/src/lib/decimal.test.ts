import { describe, expect, it } from "vitest";

import {
  add,
  compare,
  mul,
  parseDec,
  quantize,
  sub,
  toFixedText,
  toPlainText,
  type Dec,
} from "./decimal";

const d = (text: string): Dec => parseDec(text, { exponent: true })!;

describe("parseDec", () => {
  it.each([
    ["12.50", "12.50"],
    ["-3", "-3"],
    [".5", "0.5"],
    ["+7.", "7"],
    ["0.000001", "0.000001"],
  ])("reads %s", (text, fixed) => {
    expect(toFixedText(parseDec(text)!)).toBe(fixed);
  });

  it.each(["", "abc", "1,000", "1.2.3", "--1", "1e3", "Infinity"])(
    "refuses %j",
    (text) => {
      expect(parseDec(text)).toBeNull();
    },
  );

  it("takes exponents only when asked", () => {
    expect(toFixedText(d("1e3"))).toBe("1000");
    expect(toFixedText(d("2.5E-1"))).toBe("0.25");
  });
});

describe("arithmetic", () => {
  it("is exact where floats are not", () => {
    expect(toFixedText(add(d("0.1"), d("0.2")))).toBe("0.3");
    expect(compare(add(d("0.1"), d("0.2")), d("0.3"))).toBe(0);
    expect(toFixedText(sub(d("1"), d("0.99")))).toBe("0.01");
    expect(toFixedText(mul(d("0.15"), d("-1.5")))).toBe("-0.225");
  });
});

describe("quantize", () => {
  // test_formulas.py's test_quantize_cents_rounds_half_up.
  it.each([
    ["10.005", "10.01"],
    ["-17.436", "-17.44"],
    ["-10.005", "-10.01"],
    ["2.5", "2.50"],
  ])("rounds %s half up to %s", (text, cents) => {
    expect(toFixedText(quantize(d(text), 2))).toBe(cents);
  });

  it("rounds half even when asked", () => {
    expect(toFixedText(quantize(d("0.125"), 2, "half-even"))).toBe("0.12");
    expect(toFixedText(quantize(d("0.135"), 2, "half-even"))).toBe("0.14");
    expect(toFixedText(quantize(d("0.1251"), 2, "half-even"))).toBe("0.13");
  });

  it("drops trailing zeros in plain text", () => {
    expect(toPlainText(d("15.0000"))).toBe("15");
    expect(toPlainText(d("32.50"))).toBe("32.5");
    expect(toPlainText(d("100"))).toBe("100");
  });
});

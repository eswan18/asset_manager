/** Exact decimal arithmetic, enough to mirror Python's `Decimal` where the
 * Accounts page computes figures a save will store (formulas.py). A value is
 * `n × 10^-s`: "1,234.5" is { n: 12345n, s: 1 }. Pure. Browser floats would
 * drift by a cent now and then; these never do. */

export interface Dec {
  readonly n: bigint;
  readonly s: number;
}

export const ZERO: Dec = { n: 0n, s: 0 };

const PLAIN = /^([+-]?)(\d+\.?\d*|\.\d+)$/;
const WITH_EXPONENT = /^([+-]?)(\d+\.?\d*|\.\d+)(?:[eE]([+-]?\d+))?$/;

/** "12.50", "-3", ".5", "+7." -> a Dec; anything else -> null. `exponent`
 * also takes "1e3" and "2.5E-1", as Python's Decimal() does. */
export function parseDec(
  text: string,
  { exponent = false }: { exponent?: boolean } = {},
): Dec | null {
  const match = (exponent ? WITH_EXPONENT : PLAIN).exec(text);
  if (!match) return null;
  const [, sign, body, exp] = match;
  const [whole, fraction = ""] = body.split(".");
  let n = BigInt((whole || "0") + fraction);
  let s = fraction.length - (exp ? Number(exp) : 0);
  if (s < 0) {
    n *= 10n ** BigInt(-s);
    s = 0;
  }
  return { n: sign === "-" ? -n : n, s };
}

function scaled(a: Dec, s: number): bigint {
  return a.n * 10n ** BigInt(s - a.s);
}

export function add(a: Dec, b: Dec): Dec {
  const s = Math.max(a.s, b.s);
  return { n: scaled(a, s) + scaled(b, s), s };
}

export function neg(a: Dec): Dec {
  return { n: -a.n, s: a.s };
}

export function sub(a: Dec, b: Dec): Dec {
  return add(a, neg(b));
}

export function mul(a: Dec, b: Dec): Dec {
  return { n: a.n * b.n, s: a.s + b.s };
}

export function sum(values: Dec[]): Dec {
  return values.reduce(add, ZERO);
}

export function compare(a: Dec, b: Dec): -1 | 0 | 1 {
  const s = Math.max(a.s, b.s);
  const x = scaled(a, s);
  const y = scaled(b, s);
  return x < y ? -1 : x > y ? 1 : 0;
}

export function equals(a: Dec, b: Dec): boolean {
  return compare(a, b) === 0;
}

export function isNegative(a: Dec): boolean {
  return a.n < 0n;
}

export function abs(a: Dec): Dec {
  return a.n < 0n ? neg(a) : a;
}

/** Round to `places` decimal places. "half-up" is Python's ROUND_HALF_UP
 * (ties away from zero, what `quantize_cents` uses); "half-even" is
 * Decimal.quantize's default. */
export function quantize(
  a: Dec,
  places: number,
  rounding: "half-up" | "half-even" = "half-up",
): Dec {
  if (a.s <= places) return { n: scaled(a, places), s: places };
  const d = 10n ** BigInt(a.s - places);
  const magnitude = a.n < 0n ? -a.n : a.n;
  let q = magnitude / d;
  const twice = (magnitude % d) * 2n;
  if (twice > d || (twice === d && (rounding === "half-up" || q % 2n === 1n))) {
    q += 1n;
  }
  return { n: a.n < 0n ? -q : q, s: places };
}

/** Digits with the point in place, every place kept: "-1234.50". */
export function toFixedText(a: Dec): string {
  const digits = (a.n < 0n ? -a.n : a.n).toString().padStart(a.s + 1, "0");
  const whole = a.s ? digits.slice(0, -a.s) : digits;
  const text = a.s ? `${whole}.${digits.slice(-a.s)}` : whole;
  return a.n < 0n ? `-${text}` : text;
}

/** Without trailing zeros: 15.0000 -> "15", 32.50 -> "32.5". */
export function toPlainText(a: Dec): string {
  const text = toFixedText(a);
  return text.includes(".") ? text.replace(/0+$/, "").replace(/\.$/, "") : text;
}

/** Thousands separators on the whole part of an unsigned digit string. */
export function grouped(digits: string): string {
  return digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

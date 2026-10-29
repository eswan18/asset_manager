/** Formula evaluation, mirroring formulas.py (and the form's parsing in
 * accounts.py), exactly: the Accounts page recomputes computed accounts as
 * amounts are typed, and the account drawer shows the computed-value line,
 * each rounding as a save will. Pure. */
import { formatDollars, formatMoney } from "./amounts";
import {
  abs,
  compare,
  isNegative,
  mul,
  neg,
  parseDec,
  quantize,
  sub,
  sum,
  toPlainText,
  ZERO,
  type Dec,
} from "./decimal";

/** rate × (sum of inputs − cost basis): the one kind there is. */
export interface Formula {
  /** A fraction: 0.15 for 15%. */
  rate: Dec;
  costBasis: Dec;
}

export interface FormulaAccount {
  id: number;
  name: string;
  formula: Formula | null;
  inputIds: number[];
}

/** Rounded half up to cents, as every stored amount is (quantize_cents). */
export function quantizeCents(amount: Dec): Dec {
  return quantize(amount, 2, "half-up");
}

/** A plain account that a snapshot needs has no value. */
export class MissingValueError extends Error {
  readonly accountName: string;

  constructor(accountName: string) {
    super(`Missing value for ${accountName}`);
    this.name = "MissingValueError";
    this.accountName = accountName;
  }
}

/** A formula's value from its inputs' amounts (unrounded, as typed), or null
 * if any input has none. */
export function evaluate(
  formula: Formula,
  inputs: readonly (Dec | null | undefined)[],
): Dec | null {
  if (inputs.some((v) => v === null || v === undefined)) return null;
  const total = sum(inputs as Dec[]);
  return quantizeCents(mul(formula.rate, sub(total, formula.costBasis)));
}

/** The amount for every account (compute_snapshot). `values` holds every
 * plain account's amount by id; throws MissingValueError naming the first
 * account (or formula input) without one. */
export function computeSnapshot(
  accounts: readonly FormulaAccount[],
  values: ReadonlyMap<number, Dec>,
): Map<number, Dec> {
  const byId = new Map(accounts.map((a) => [a.id, a]));
  const result = new Map<number, Dec>();
  for (const account of accounts) {
    if (account.formula === null) {
      const value = values.get(account.id);
      if (value === undefined) throw new MissingValueError(account.name);
      result.set(account.id, quantizeCents(value));
      continue;
    }
    for (const id of account.inputIds) {
      if (!values.has(id)) {
        throw new MissingValueError(byId.get(id)?.name ?? `account ${id}`);
      }
    }
    result.set(
      account.id,
      evaluate(
        account.formula,
        account.inputIds.map((id) => values.get(id)),
      )!,
    );
  }
  return result;
}

/** Comfortably above any real balance (accounts.MAX_AMOUNT). */
const MAX_AMOUNT: Dec = { n: 10_000_000_000_000n, s: 0 };

/** A refusal with the service's message. */
export class FormulaError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "FormulaError";
  }
}

/** "$1,234.56", "-17.44" or "(17.44)" as an amount in cents (parse_amount). */
export function parseAmount(text: string): Dec {
  let cleaned = text.replace(/[$, ]/g, "").trim();
  const negative = cleaned.startsWith("(") && cleaned.endsWith(")");
  if (negative) cleaned = cleaned.slice(1, -1);
  const amount = parseDec(cleaned.trim(), { exponent: true });
  if (amount === null) {
    throw new FormulaError(`'${text.trim()}' is not a number`);
  }
  const result = quantizeCents(negative ? neg(amount) : amount);
  if (compare(abs(result), MAX_AMOUNT) >= 0) {
    throw new FormulaError(`${text.trim()} is too large`);
  }
  return result;
}

/** A formula from the form's rate in percent ("15") and cost basis (blank
 * for zero), as accounts.parse_formula reads them. */
export function parseFormula(ratePercent: string, costBasis: string): Formula {
  const percent = parseDec(ratePercent.trim(), { exponent: true });
  if (percent === null) {
    throw new FormulaError("Rate must be a number, e.g. 15 for 15%");
  }
  const rate = quantize(
    mul(percent, { n: 1n, s: 2 }), // ÷ 100
    6,
    "half-even",
  );
  if (isNegative(rate)) throw new FormulaError("Rate must be zero or more");
  return {
    rate,
    costBasis: costBasis.trim() ? parseAmount(costBasis) : ZERO,
  };
}

/** 0.15 -> "15", 0.325 -> "32.5" (format_percent). */
export function formatPercent(rate: Dec): string {
  return toPlainText(mul(rate, { n: 100n, s: 0 }));
}

export const PREVIEW_HINT = "rate × (sum of inputs − cost basis)";

/** The drawer's computed-value line (formula_preview): "15% × ($179,265 −
 * $82,387)" and "$14,531.74", from the form's fields and the inputs' amounts
 * on the latest snapshot. Null when there is nothing to show: no inputs, or
 * a rate or basis that does not parse. */
export function formulaPreview(
  ratePercent: string,
  costBasis: string,
  inputIds: readonly number[],
  amounts: ReadonlyMap<number, Dec>,
): { text: string; value: string } | null {
  if (inputIds.length === 0) return null;
  let formula: Formula;
  try {
    formula = parseFormula(ratePercent, costBasis);
  } catch (error) {
    if (error instanceof FormulaError) return null;
    throw error;
  }
  if (inputIds.some((id) => !amounts.has(id))) {
    return { text: "Needs a saved amount for every input", value: "—" };
  }
  const total = sum(inputIds.map((id) => amounts.get(id)!));
  const value = evaluate(
    formula,
    inputIds.map((id) => amounts.get(id)),
  )!;
  return {
    text:
      `${formatPercent(formula.rate)}% × ` +
      `(${formatDollars(total)} − ${formatDollars(formula.costBasis)})`,
    value: formatMoney(value),
  };
}

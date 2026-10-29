/** The Cash flows page's pure pieces: its money text, the cash flow
 * drawer's rates strip (exact BigInt-cents arithmetic, which
 * tests/browser/test_spa_cash_flows.py checks against the service's
 * `rates()`), the drawer's form parsing, and the categories drawer's meta
 * line. Ported from the Jinja page's view code, which went at the cutover. */

export type Period = "day" | "month" | "year";
export type Direction = "income" | "expense";
export type Unit = "day" | "week" | "month" | "year";

export const PERIODS: readonly Period[] = ["day", "month", "year"];
export const UNITS: readonly Unit[] = ["day", "week", "month", "year"];

/** The `?per=` value as a period; anything unknown is month (parse_period). */
export function parsePeriod(value: string | null | undefined): Period {
  return PERIODS.includes(value as Period) ? (value as Period) : "month";
}

const MINUS = "−";

/** "1234567" -> "1,234,567". */
function grouped(whole: bigint): string {
  return whole.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

/** Decimal text ("1215.48", "-50", "0.005") as a sign and its magnitude in
 * units of 10^-`places`, rounded half up (away from zero, as Decimal's
 * ROUND_HALF_UP). Null if it isn't decimal text. */
function scaled(
  text: string,
  places: number,
): { negative: boolean; units: bigint } | null {
  const m = /^(-?)(\d*)(?:\.(\d*))?$/.exec(text.trim());
  if (!m || (m[2] === "" && !m[3])) return null;
  const frac = (m[3] ?? "").padEnd(places + 1, "0");
  let units =
    BigInt(m[2] || "0") * 10n ** BigInt(places) +
    BigInt(frac.slice(0, places) || "0");
  if (Number(frac[places]) >= 5) units += 1n;
  return { negative: m[1] === "-", units };
}

/** "$1,234.56"; negatives get a minus sign (−), and `sign` adds "+" to
 * positives. Without cents it rounds half up to whole dollars. `amount` is
 * the API's decimal text. */
export function money(
  amount: string,
  { cents = true, sign = false }: { cents?: boolean; sign?: boolean } = {},
): string {
  const parsed = scaled(amount, cents ? 2 : 0);
  if (!parsed) return amount;
  const { negative, units } = parsed;
  const body = cents
    ? `$${grouped(units / 100n)}.${(units % 100n).toString().padStart(2, "0")}`
    : `$${grouped(units)}`;
  if (units === 0n) return body;
  if (negative) return MINUS + body;
  return sign ? "+" + body : body;
}

/** Drop a leading minus: an amount's size. */
export function unsigned(amount: string): string {
  return amount.startsWith("-") ? amount.slice(1) : amount;
}

// --- the rates strip ---------------------------------------------------------

/** Occurrences per year of "every 1 unit", as an exact fraction (per_year). */
const PER_YEAR: Record<Unit, readonly [bigint, bigint]> = {
  day: [365n, 1n],
  week: [365n, 7n],
  month: [12n, 1n],
  year: [1n, 1n],
};
const MAX_CENTS = 10n ** 15n; // MAX_AMOUNT, in cents
const MAX_EVERY = 1000n;

/** An amount the user typed ("$1,200", ".5", "5.") in whole cents, rounded
 * half up as a save rounds it. Null for anything else, a minus sign
 * included. */
export function amountCents(text: string): bigint | null {
  const s = text.replace(/[$,\s]/g, "");
  const m = /^(\d*)(?:\.(\d*))?$/.exec(s);
  if (!m || (m[1] === "" && !(m[2] ?? "").length)) return null;
  const frac = (m[2] ?? "") + "000";
  let c = BigInt(m[1] || "0") * 100n + BigInt(frac.slice(0, 2));
  if (Number(frac[2]) >= 5) c += 1n;
  return c;
}

function divideHalfUp(n: bigint, d: bigint): bigint {
  return (2n * n + d) / (2n * d);
}

function centsMoney(c: bigint): string {
  return `$${grouped(c / 100n)}.${(c % 100n).toString().padStart(2, "0")}`;
}

export interface Rates {
  perDay: string;
  perMonth: string;
  perYear: string;
}

/**
 * The drawer's rates strip: the amount a day, a month and a year, as the
 * server's rates() gives them (so they match the page), unsigned. The
 * amount in whole cents, then exact integer division per period, rounded
 * half up once. Null (the strip shows dashes) while the amount or the
 * frequency is not one a save would accept.
 */
export function formRates(
  amount: string,
  every: string,
  unit: string,
): Rates | null {
  const cents = amountCents(amount);
  const everyText = every.trim();
  const times = /^\d+$/.test(everyText) ? BigInt(everyText) : null;
  const perYear = PER_YEAR[unit as Unit] as (typeof PER_YEAR)[Unit] | undefined;
  if (
    cents === null ||
    cents >= MAX_CENTS ||
    times === null ||
    times < 1n ||
    times > MAX_EVERY ||
    !perYear
  ) {
    return null;
  }
  const [num, den] = perYear;
  const per = (periods: bigint) =>
    centsMoney(divideHalfUp(cents * num, den * times * periods));
  return { perDay: per(365n), perMonth: per(12n), perYear: per(1n) };
}

// --- the cash flow form --------------------------------------------------------

/** The drawer's fields as typed. */
export interface FlowForm {
  name: string;
  direction: string;
  amount: string;
  every: string;
  unit: string;
  /** "" for Uncategorized. */
  categoryId: string;
  isEstimate: boolean;
  description: string;
}

/** What the API takes: the form's text as cash flow fields. */
export interface FlowFields {
  name: string;
  direction: Direction;
  /** Decimal text; the server rounds it to cents and checks its range. */
  amount: string;
  every: number;
  unit: Unit;
  category_id: number | null;
  description: string;
  is_estimate: boolean;
}

const AMOUNT = /^-?(?:[0-9]+\.?[0-9]*|\.[0-9]+)$/;

/**
 * The form's text as fields, or the message for text that is not one of
 * the choices or not a number (`_parse_form`). The server checks
 * everything else (name, sign, size, range, category) and says why. A minus
 * sign gets through, so the server can say why it is refused.
 */
export function parseFlowForm(
  form: FlowForm,
): { fields: FlowFields } | { error: string } {
  if (form.direction !== "income" && form.direction !== "expense") {
    return { error: "Choose income or expense" };
  }
  if (!UNITS.includes(form.unit as Unit)) {
    return { error: "Choose day, week, month or year" };
  }
  const every = form.every.trim();
  if (!/^[0-9]+$/.test(every)) {
    return {
      error: "Every must be a whole number, e.g. 2 for every 2 weeks",
    };
  }
  const category = form.categoryId.trim();
  if (category && !/^[0-9]+$/.test(category)) {
    return { error: "Choose a category from the list" };
  }
  const amount = form.amount.replace(/[$,\s]/g, "");
  if (!AMOUNT.test(amount)) return { error: "Amount must be a number" };
  return {
    fields: {
      name: form.name,
      direction: form.direction,
      amount: canonical(amount),
      every: Number(every),
      unit: form.unit as Unit,
      category_id: category ? Number(category) : null,
      description: form.description,
      is_estimate: form.isEstimate,
    },
  };
}

/** "5." -> "5", ".5" -> "0.5", "-.5" -> "-0.5": the same number, in the
 * form every JSON decimal parser reads. */
function canonical(amount: string): string {
  const negative = amount.startsWith("-");
  const [whole, frac = ""] = (negative ? amount.slice(1) : amount).split(".");
  return (negative ? "-" : "") + (whole || "0") + (frac ? "." + frac : "");
}

/** The drawer's eyebrow: "Edit expense · Food", "New income". */
export function flowEyebrow(
  editing: boolean,
  direction: Direction,
  categoryName: string | undefined,
): string {
  const text = `${editing ? "Edit" : "New"} ${direction}`;
  return categoryName === undefined ? text : `${text} · ${categoryName}`;
}

// --- the categories drawer ------------------------------------------------------

const PER_SUFFIX: Record<Period, string> = {
  day: "/day",
  month: "/mo",
  year: "/yr",
};

/** A category's meta line: "4 flows · $3,376.67/mo · income $100.00/mo",
 * or "No flows yet". Income in it is shown apart from its expenses. */
export function categoryMeta(
  {
    count,
    expenses,
    income,
  }: { count: number; expenses: string | null; income: string | null },
  period: Period,
): string {
  if (!count) return "No flows yet";
  const suffix = PER_SUFFIX[period];
  const parts = [`${count} flow${count === 1 ? "" : "s"}`];
  if (expenses !== null) parts.push(money(expenses) + suffix);
  if (income !== null) parts.push("income " + money(income) + suffix);
  return parts.join(" · ");
}

/** The delete confirmation's second sentence. */
export function deleteWhy(count: number): string {
  if (!count) return "It has no flows; nothing else is deleted.";
  return `${count} flow${count === 1 ? "" : "s"}. ${
    count === 1 ? "It moves" : "They move"
  } to Uncategorized; nothing else is deleted.`;
}

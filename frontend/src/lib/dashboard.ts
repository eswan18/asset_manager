/** The dashboard's formatting and chart scales (web/dashboard.py's money,
 * signed_money, signed_percent, short_date and long_date, in TypeScript,
 * plus the axis ticks Plotly worked out for the Jinja chart). Pure.
 *
 * Amounts arrive from the API as exact decimal strings ("12400.00",
 * "-17.44") and dates as ISO dates ("2026-10-24"); nothing here goes
 * through a float until it is plotted. */

export const MINUS = "−";

/** Each side's name, in the key and on the chart's columns. */
export const COLUMN_TITLES = {
  asset: "Assets",
  liability: "Liabilities",
} as const;

const MONTHS = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

/** A decimal string rounded half up (away from zero) to `places`, as
 * [negative, digits] with the digits unsigned and unpointed: ("-1.25", 1)
 * -> [true, "13"]. A result of zero is never negative. */
function roundHalfUp(amount: string, places: number): [boolean, string] {
  const text = amount.trim();
  const negative = text.startsWith("-");
  const [whole, fraction = ""] = text.replace(/^[-+]/, "").split(".");
  const kept = (fraction + "0".repeat(places)).slice(0, places);
  let digits = BigInt((whole || "0") + kept);
  if ((fraction[places] ?? "0") >= "5") digits += 1n;
  return [negative && digits !== 0n, digits.toString()];
}

function grouped(digits: string): string {
  return digits.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
}

/** Whole dollars: $412,380, or −$1,200. */
export function money(amount: string): string {
  const [negative, digits] = roundHalfUp(amount, 0);
  return `${negative ? MINUS : ""}$${grouped(digits)}`;
}

/** +$6,140, −$1,200, or $0. */
export function signedMoney(amount: string): string {
  const [negative, digits] = roundHalfUp(amount, 0);
  const plus = !negative && digits !== "0" ? "+" : "";
  return plus + money(amount);
}

/** +1.5%, −0.3%, or 0.0%, to one decimal place. */
export function signedPercent(percent: string): string {
  const [negative, digits] = roundHalfUp(percent, 1);
  const padded = digits.padStart(2, "0");
  const text = `${padded.slice(0, -1)}.${padded.slice(-1)}%`;
  if (digits === "0") return text;
  return (negative ? MINUS : "+") + text;
}

function parts(day: string): [number, number, number] {
  const [y, m, d] = day.split("-").map(Number);
  return [y, m, d];
}

/** "Sep 24", with the year only when it differs from `reference`'s. */
export function shortDate(day: string, reference: string): string {
  const [year, month, date] = parts(day);
  const text = `${MONTHS[month - 1]} ${date}`;
  return year === parts(reference)[0] ? text : `${text}, ${year}`;
}

/** "Oct 24, 2026". */
export function longDate(day: string): string {
  const [year, month, date] = parts(day);
  return `${MONTHS[month - 1]} ${date}, ${year}`;
}

// --- the chart's axes --------------------------------------------------------

/** An ISO date as the chart's x value: UTC midnight in milliseconds. */
export function dayValue(day: string): number {
  const [year, month, date] = parts(day);
  return Date.UTC(year, month - 1, date);
}

const DAY_MS = 86_400_000;

/** With one snapshot, the x range is the month before it, with the point at
 * the right edge (charts.py's LONE_POINT_DAYS). */
export const LONE_POINT_DAYS = 30;

/** The x range of the lines: first to last snapshot, or for a lone one the
 * 30 days before it and the day after. */
export function dateDomain(days: string[]): [number, number] {
  const values = days.map(dayValue);
  if (values.length === 0) return [0, 1];
  const first = Math.min(...values);
  const last = Math.max(...values);
  if (first === last) {
    return [first - LONE_POINT_DAYS * DAY_MS, last + DAY_MS];
  }
  return [first, last];
}

/** A dollar axis's ticks and range: from zero (or the lowest value, if
 * below it) to a little over the highest, in steps of 1, 2 or 5 × 10ⁿ
 * aiming at `target` intervals, as Plotly's `rangemode: tozero` did. */
export function moneyScale(
  values: number[],
  target = 5,
): { domain: [number, number]; ticks: number[] } {
  const lo = Math.min(0, ...values);
  const hi = Math.max(0, ...values);
  if (hi === lo) return { domain: [0, 1], ticks: [0] };
  const rough = (hi - lo) / target;
  const power = 10 ** Math.floor(Math.log10(rough));
  const step =
    [1, 2, 5, 10].map((m) => m * power).find((s) => s >= rough) ?? 10 * power;
  // A little headroom over the top, as Plotly's autorange leaves.
  const domain: [number, number] = [lo, hi + (hi - lo) * 0.03];
  const ticks: number[] = [];
  for (let t = Math.ceil(lo / step) * step; t <= domain[1]; t += step) {
    ticks.push(Math.round(t));
  }
  return { domain, ticks };
}

/** A dollar tick: $0, $50k, $1.5M, −$20k (d3's "~s" with a "$"). */
export function axisMoney(value: number): string {
  const sign = value < 0 ? MINUS : "";
  const size = Math.abs(value);
  const [divisor, suffix] =
    size >= 1e9
      ? [1e9, "G"]
      : size >= 1e6
        ? [1e6, "M"]
        : size >= 1e3
          ? [1e3, "k"]
          : [1, ""];
  const number = Number((size / divisor).toPrecision(6)).toString();
  return `${sign}$${number}${suffix}`;
}

export interface DateTick {
  value: number;
  /** The label, and a second line under it (the year), if any. */
  label: string;
  sub?: string;
}

/** Date ticks across [start, end], about `target` of them, as Plotly drew
 * them: month starts ("Jan 2026", "Mar 2026") over months, or days ("Sep 6",
 * the first with its year under it) over a few weeks. */
export function dateTicks(
  [start, end]: [number, number],
  target: number,
): DateTick[] {
  const days = (end - start) / DAY_MS;
  if (days / target < 20) {
    const step = [1, 2, 7, 14].find((s) => s >= days / target) ?? 14;
    // Weekly steps fall on Sundays, as Plotly's do.
    const first = new Date(start);
    let value = Date.UTC(
      first.getUTCFullYear(),
      first.getUTCMonth(),
      first.getUTCDate(),
    );
    if (value < start) value += DAY_MS;
    if (step >= 7) {
      while (new Date(value).getUTCDay() !== 0) value += DAY_MS;
    }
    const ticks: DateTick[] = [];
    for (; value <= end; value += step * DAY_MS) {
      const d = new Date(value);
      ticks.push({
        value,
        label: `${MONTHS[d.getUTCMonth()]} ${d.getUTCDate()}`,
        sub: ticks.length === 0 ? String(d.getUTCFullYear()) : undefined,
      });
    }
    return ticks;
  }
  const months = days / 30.44;
  const step = [1, 2, 3, 6, 12, 24].find((s) => s >= months / target) ?? 24;
  const first = new Date(start);
  let year = first.getUTCFullYear();
  let month = first.getUTCMonth();
  if (Date.UTC(year, month, 1) < start) month += 1;
  // Steps of a quarter or more start on a multiple of the step (Jan, Apr…).
  if (step <= 12) month = Math.ceil(month / step) * step;
  else {
    year = Math.ceil((year + month / 12) / 2) * 2;
    month = 0;
  }
  const ticks: DateTick[] = [];
  for (;;) {
    const value = Date.UTC(year, month, 1);
    if (value > end) break;
    const d = new Date(value);
    ticks.push({
      value,
      label: `${MONTHS[d.getUTCMonth()]} ${d.getUTCFullYear()}`,
    });
    month += step;
  }
  return ticks;
}

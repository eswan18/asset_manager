/** Reading and writing amounts as the Accounts page and the account drawer
 * show them (accounts.html's script and web/accounts_routes.py's
 * formatters). Pure. */
import {
  abs,
  grouped,
  isNegative,
  parseDec,
  quantize,
  toFixedText,
  type Dec,
} from "./decimal";

/** A money string from the API ("12400.00", "-17.44") as a Dec. */
export function money(text: string): Dec {
  const value = parseDec(text);
  if (value === null) throw new Error(`Not an amount: ${text}`);
  return value;
}

export type Reading =
  | { kind: "blank" }
  | { kind: "invalid" }
  /** `text` is the cleaned decimal for a save ("-1234.5"): the server's
   * parse and rounding decide the final cent, not ours. */
  | { kind: "number"; value: Dec; text: string };

/** What someone typed in an amount or basis field: "$1,234.56", "-17.44",
 * "+5" or "(17.44)" (negative). Blank is its own case. */
export function readAmount(raw: string): Reading {
  let s = raw.replace(/[$,\s]/g, "");
  if (s === "") return { kind: "blank" };
  let negative = false;
  if (s.startsWith("(") && s.endsWith(")")) {
    negative = true;
    s = s.slice(1, -1);
  }
  if (!/^[-+]?(\d+\.?\d*|\.\d+)$/.test(s)) return { kind: "invalid" };
  if (s.startsWith("+")) s = s.slice(1);
  else if (s.startsWith("-")) {
    negative = true;
    s = s.slice(1);
  }
  const text = (negative ? "-" : "") + s;
  return { kind: "number", value: parseDec(text)!, text };
}

/** The number in a field, or null when it is blank or not a number. */
export function amountIn(raw: string): Dec | null {
  const reading = readAmount(raw);
  return reading.kind === "number" ? reading.value : null;
}

/** Two fields hold the same amount: "1500" and "1,500.00" do. Text that is
 * not a number compares as typed. */
export function normalized(raw: string): string {
  const reading = readAmount(raw);
  return reading.kind === "number"
    ? toFixedText(quantize(reading.value, 2))
    : raw.trim();
}

/** "1,234.56", "-17.44": a field's value (format_amount). */
export function formatAmount(value: Dec): string {
  const cents = quantize(value, 2);
  const text = grouped(toFixedText(abs(cents)));
  return isNegative(cents) ? `-${text}` : text;
}

/** "$1,234.56", "-$17.44" (format_money). */
export function formatMoney(value: Dec): string {
  const cents = quantize(value, 2);
  const text = `$${grouped(toFixedText(abs(cents)))}`;
  return isNegative(cents) ? `-${text}` : text;
}

/** "+$500.00", "-$17.44", "$0.00": a change in the save bar. */
export function formatChange(value: Dec): string {
  const cents = quantize(value, 2);
  return (cents.n > 0n ? "+" : "") + formatMoney(cents);
}

/** Whole dollars, rounded half up: 82386.74 -> "$82,387" (format_dollars). */
export function formatDollars(value: Dec): string {
  const whole = quantize(value, 0);
  const text = `$${grouped(toFixedText(abs(whole)))}`;
  return isNegative(whole) ? `-${text}` : text;
}

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

/** "Oct 24, 2026" from an ISO date; "Oct 24" when `today` (also ISO) is in
 * the same year (format_short_date). Calendar dates: no time zone. */
export function shortDate(iso: string, today?: string): string {
  const [year, month, day] = iso.split("-").map(Number);
  const text = `${MONTHS[month - 1]} ${day}`;
  return today !== undefined && today.slice(0, 4) === iso.slice(0, 4)
    ? text
    : `${text}, ${year}`;
}

/** The page head's line: what Save will write, and when it last ran, both
 * in the viewer's zone (snapshot_line). */
export function snapshotLine(asOf: string, lastSaved: string | null): string {
  const head = `Saving writes today's snapshot, ${shortDate(asOf)}.`;
  if (lastSaved === null) return `${head} Nothing saved yet.`;
  if (lastSaved === asOf) {
    return `${head} Last saved today; saving again replaces it.`;
  }
  return `${head} Last saved ${shortDate(lastSaved, asOf)}.`;
}

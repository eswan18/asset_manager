/** The Accounts page's staged edits as data (accounts.html's script): its
 * fields, what they add up to, the save's payload, and sessionStorage.
 * Pure apart from the storage helpers, which never throw. */
import { amountIn, normalized, readAmount } from "./amounts";
import { add, sub, ZERO, type Dec } from "./decimal";
import { evaluate, quantizeCents, type Formula } from "./formulas";

export type Side = "asset" | "liability";

/** An active account as the page computes with it. */
export interface PageAccount {
  id: number;
  name: string;
  type: Side;
  /** Its group on the page: a category key or "uncategorized". */
  group: string;
  formula: Formula | null;
  inputIds: number[];
}

/** "amount:12" (a plain account's amount) or "basis:7" (a computed
 * account's cost basis): the key a field is staged under, here and in
 * sessionStorage. */
export type FieldKey = `${"amount" | "basis"}:${number}`;

export interface Field {
  key: FieldKey;
  kind: "amount" | "basis";
  accountId: number;
  /** Its accessible name, which a "not a number" refusal quotes. */
  label: string;
  /** What the page loaded with: "1,000.00", or "" for no amount. */
  initial: string;
}

export const amountKey = (id: number): FieldKey => `amount:${id}`;
export const basisKey = (id: number): FieldKey => `basis:${id}`;

export function isDirty(field: Field, value: string): boolean {
  return normalized(value) !== normalized(field.initial);
}

/** Group subtotals are keyed "asset:bank_accounts". */
export const groupId = (type: Side, group: string) => `${type}:${group}`;

export interface Evaluation {
  /** Each active account's amount, or null when it has none yet (blank, not
   * a number, or a formula missing an input). */
  amounts: Map<number, Dec | null>;
  totals: Record<Side, Dec>;
  subtotals: Map<string, Dec>;
  net: Dec;
}

/** What the page adds up to with `valueOf(key)` in its fields, rounded as a
 * save would store it: plain amounts to cents; formulas from their inputs
 * as typed and the basis in cents. A blank basis is zero. */
export function evaluatePage(
  accounts: readonly PageAccount[],
  valueOf: (key: FieldKey) => string,
): Evaluation {
  const values = new Map<number, Dec | null>();
  for (const account of accounts) {
    if (account.formula === null) {
      values.set(account.id, amountIn(valueOf(amountKey(account.id))));
    }
  }
  const amounts = new Map<number, Dec | null>();
  const totals: Record<Side, Dec> = { asset: ZERO, liability: ZERO };
  const subtotals = new Map<string, Dec>();
  for (const account of accounts) {
    let amount: Dec | null = null;
    if (account.formula === null) {
      const value = values.get(account.id);
      amount = value ? quantizeCents(value) : null;
    } else {
      const basis = readAmount(valueOf(basisKey(account.id)));
      if (basis.kind !== "invalid") {
        amount = evaluate(
          {
            rate: account.formula.rate,
            costBasis:
              basis.kind === "blank" ? ZERO : quantizeCents(basis.value),
          },
          account.inputIds.map((id) => values.get(id)),
        );
      }
    }
    amounts.set(account.id, amount);
    if (amount !== null) {
      totals[account.type] = add(totals[account.type], amount);
      const id = groupId(account.type, account.group);
      subtotals.set(id, add(subtotals.get(id) ?? ZERO, amount));
    }
  }
  return {
    amounts,
    totals,
    subtotals,
    net: sub(totals.asset, totals.liability),
  };
}

export type SaveProblem = { key: FieldKey; message: string };

/** The save's body from the fields, or the first thing stopping it: amounts
 * are checked before bases, each in page order. A blank amount blocks the
 * save; a blank basis is zero. Amounts go as the cleaned text typed, so the
 * server's parse and rounding decide the final cent. */
export function collectSnapshot(
  fields: readonly Field[],
  valueOf: (key: FieldKey) => string,
):
  | {
      body: {
        values: Record<number, string>;
        cost_bases: Record<number, string>;
      };
      problem: null;
    }
  | { body: null; problem: SaveProblem } {
  const body = {
    values: {} as Record<number, string>,
    cost_bases: {} as Record<number, string>,
  };
  const ordered = [
    ...fields.filter((f) => f.kind === "amount"),
    ...fields.filter((f) => f.kind === "basis"),
  ];
  for (const field of ordered) {
    const reading = readAmount(valueOf(field.key));
    if (reading.kind === "invalid") {
      return {
        body: null,
        problem: { key: field.key, message: `${field.label} isn't a number.` },
      };
    }
    if (reading.kind === "blank") {
      if (field.kind === "basis") {
        body.cost_bases[field.accountId] = "0";
        continue;
      }
      return {
        body: null,
        problem: {
          key: field.key,
          message: "Every account needs an amount before saving.",
        },
      };
    }
    if (field.kind === "amount") body.values[field.accountId] = reading.text;
    else body.cost_bases[field.accountId] = reading.text;
  }
  return { body, problem: null };
}

/** Where staged edits wait across reloads (the Jinja page's key, so edits
 * staged there before the cutover survive it). */
export const STORAGE_KEY = "sensibility:staged-edits";

export function readStaged(): Record<string, string> {
  try {
    const staged: unknown = JSON.parse(
      sessionStorage.getItem(STORAGE_KEY) || "{}",
    );
    return staged && typeof staged === "object"
      ? (staged as Record<string, string>)
      : {};
  } catch {
    return {};
  }
}

/** Store the dirty fields' values, and only those. */
export function writeStaged(
  fields: readonly Field[],
  valueOf: (key: FieldKey) => string,
): void {
  const staged: Record<string, string> = {};
  for (const field of fields) {
    const value = valueOf(field.key);
    if (isDirty(field, value)) staged[field.key] = value;
  }
  try {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(staged));
  } catch {
    // Storage unavailable: the edits still live in the page.
  }
}

export function clearStaged(): void {
  try {
    sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // Nothing to clear.
  }
}

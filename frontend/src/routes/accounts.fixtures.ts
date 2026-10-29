/** Test data for the Accounts page and the account drawer: the browser
 * tests' `seeded` workspace (Checking, Schwab, a card, and a 15% tax on
 * Schwab's gain over $82,386.74, saved Sep 27), plus a retired account. */
import type {
  AccountDetail,
  AccountOut,
  AccountsOverview,
} from "@/api/accounts";

export const CATEGORIES = [
  { key: "bank_accounts", label: "Bank Accounts" },
  { key: "investment_accounts", label: "Investment Accounts" },
  { key: "credit_cards", label: "Credit Cards" },
  { key: "tax_liability", label: "Tax Liability" },
];

export function plain(
  id: number,
  name: string,
  type: "asset" | "liability",
  amount: string | null,
  category: string | null = null,
  retired_at: string | null = null,
): AccountOut {
  return {
    id,
    name,
    type,
    category,
    amount,
    computed: false,
    formula: null,
    retired_at,
  };
}

export const CHECKING = plain(
  1,
  "Checking",
  "asset",
  "1000.00",
  "bank_accounts",
);
export const SCHWAB = plain(
  2,
  "Schwab",
  "asset",
  "179265.00",
  "investment_accounts",
);
export const CARD = plain(3, "Card", "liability", "500.00", "credit_cards");
export const TAX: AccountOut = {
  id: 4,
  name: "Cap gains tax",
  type: "liability",
  category: "tax_liability",
  amount: "14531.74",
  computed: true,
  formula: {
    kind: "proportional",
    rate: "0.15",
    rate_percent: "15",
    cost_basis: "82386.74",
    inputs: [{ id: 2, name: "Schwab" }],
    text: "15% × (Schwab − basis)",
  },
  retired_at: null,
};
export const OLD = plain(
  5,
  "Old savings",
  "asset",
  null,
  "bank_accounts",
  "2026-09-01",
);

export function overview(
  overrides: Partial<AccountsOverview> = {},
): AccountsOverview {
  return {
    as_of: "2026-10-28",
    last_saved: "2026-09-27",
    snapshot_is_today: false,
    net_worth: "165233.26",
    retired_count: 1,
    can_edit: true,
    categories: CATEGORIES,
    sections: [
      {
        kind: "asset",
        title: "Assets",
        total: "180265.00",
        groups: [
          {
            key: "bank_accounts",
            label: "Bank Accounts",
            subtotal: "1000.00",
            retired: false,
            accounts: [CHECKING, OLD],
          },
          {
            key: "investment_accounts",
            label: "Investment Accounts",
            subtotal: "179265.00",
            retired: false,
            accounts: [SCHWAB],
          },
        ],
      },
      {
        kind: "liability",
        title: "Liabilities",
        total: "15031.74",
        groups: [
          {
            key: "credit_cards",
            label: "Credit Cards",
            subtotal: "500.00",
            retired: false,
            accounts: [CARD],
          },
          {
            key: "tax_liability",
            label: "Tax Liability",
            subtotal: "14531.74",
            retired: false,
            accounts: [TAX],
          },
        ],
      },
    ],
    ...overrides,
  };
}

export const EMPTY = overview({
  last_saved: null,
  net_worth: "0.00",
  retired_count: 0,
  sections: [
    { kind: "asset", title: "Assets", total: "0.00", groups: [] },
    { kind: "liability", title: "Liabilities", total: "0.00", groups: [] },
  ],
});

export function detail(
  account: AccountOut,
  overrides: Partial<AccountDetail> = {},
): AccountDetail {
  return {
    account,
    can_edit: true,
    eligible_inputs: [
      {
        kind: "asset",
        label: "Assets",
        accounts: [CHECKING, SCHWAB]
          .filter((a) => a.id !== account.id)
          .map(({ id, name, amount }) => ({ id, name, amount })),
      },
      {
        kind: "liability",
        label: "Liabilities",
        accounts: [CARD]
          .filter((a) => a.id !== account.id)
          .map(({ id, name, amount }) => ({ id, name, amount })),
      },
    ],
    retire_blocker: null,
    retire_warning: null,
    history: account.amount
      ? [{ date: "2026-09-27", amount: account.amount }]
      : [],
    ...overrides,
  };
}

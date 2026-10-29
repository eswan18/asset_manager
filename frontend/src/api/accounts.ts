/** The Accounts page and the account drawer: types, fetchers and hooks
 * (web/api_accounts.py, and `POST .../snapshots` in web/api_routes.py).
 * Money is a two-place decimal string ("12400.00"), dates ISO. */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import { queryKeys } from "./queryKeys";

export type AccountType = "asset" | "liability";

export interface InputRef {
  id: number;
  name: string;
}

/** A computed account's value: rate × (sum of inputs − cost basis). */
export interface FormulaOut {
  kind: "proportional";
  /** A fraction: "0.15". */
  rate: string;
  /** In percent: "15", "32.5". */
  rate_percent: string;
  cost_basis: string;
  inputs: InputRef[];
  /** "15% × (Schwab + Fidelity − basis)". */
  text: string;
}

export interface AccountOut {
  id: number;
  name: string;
  type: AccountType;
  /** A category key; null is Uncategorized. */
  category: string | null;
  /** On the workspace's latest snapshot date; null if it has no row there. */
  amount: string | null;
  computed: boolean;
  formula: FormulaOut | null;
  /** Null while active. */
  retired_at: string | null;
}

export interface OverviewGroup {
  /** A category key, or "uncategorized". */
  key: string;
  label: string;
  subtotal: string;
  /** Every account in it is retired. */
  retired: boolean;
  /** Active first, then retired; by name within each. */
  accounts: AccountOut[];
}

export interface OverviewSection {
  kind: AccountType;
  title: string;
  total: string;
  groups: OverviewGroup[];
}

export interface CategoryOption {
  key: string;
  label: string;
}

/** `GET .../accounts/overview`. */
export interface AccountsOverview {
  /** Today in the viewer's zone: the date a save now would carry. */
  as_of: string;
  last_saved: string | null;
  /** A save now replaces today's snapshot. */
  snapshot_is_today: boolean;
  net_worth: string;
  /** Retired accounts, listed or not. */
  retired_count: number;
  can_edit: boolean;
  categories: CategoryOption[];
  /** Assets, then Liabilities. */
  sections: OverviewSection[];
}

export interface InputOption {
  id: number;
  name: string;
  amount: string | null;
}

export interface InputGroup {
  kind: AccountType;
  label: string;
  accounts: InputOption[];
}

/** `GET .../accounts/{id}`: the drawer. */
export interface AccountDetail {
  account: AccountOut;
  can_edit: boolean;
  /** Active, plain, not this one; empty groups left out. */
  eligible_inputs: InputGroup[];
  retire_blocker: string | null;
  retire_warning: string | null;
  /** Newest first. */
  history: { date: string; amount: string }[];
}

/** Text as typed in the form; the service parses it. */
export interface FormulaIn {
  rate_percent: string;
  cost_basis: string;
  input_ids: number[];
}

export interface AccountCreate {
  name: string;
  type: AccountType;
  category: string | null;
  formula: FormulaIn | null;
}

/** Only the fields sent change; `formula: null` makes it plain. */
export interface AccountUpdate {
  name?: string;
  category?: string | null;
  formula?: FormulaIn | null;
}

/** `POST .../snapshots`: amounts as cleaned decimal strings, by id. */
export interface SnapshotIn {
  values: Record<number, string>;
  cost_bases: Record<number, string>;
}

export interface SnapshotSaved {
  date: string;
  count: number;
  accounts: {
    id: number;
    type: AccountType;
    amount: string | null;
    source: "updated" | "carried_forward" | "computed";
  }[];
}

const base = (workspaceId: number) => `/api/workspaces/${workspaceId}/accounts`;

/** Always with the retired accounts: Show retired is the page's own toggle,
 * as on the Jinja page, so flipping it neither refetches nor disturbs
 * staged edits. */
export const getAccountsOverview = (workspaceId: number) =>
  api.get<AccountsOverview>(`${base(workspaceId)}/overview`, {
    query: { retired: true },
  });

export const getAccount = (workspaceId: number, accountId: number) =>
  api.get<AccountDetail>(`${base(workspaceId)}/${accountId}`);

export const createAccount = (workspaceId: number, body: AccountCreate) =>
  api.post<AccountOut>(base(workspaceId), body);

export const updateAccount = (
  workspaceId: number,
  accountId: number,
  body: AccountUpdate,
) => api.patch<AccountOut>(`${base(workspaceId)}/${accountId}`, body);

export const retireAccount = (workspaceId: number, accountId: number) =>
  api.post<AccountOut>(`${base(workspaceId)}/${accountId}/retire`);

export const unretireAccount = (workspaceId: number, accountId: number) =>
  api.post<AccountOut>(`${base(workspaceId)}/${accountId}/unretire`);

/** Dated today in the viewer's zone: the client sends `X-Timezone`. */
export const saveSnapshot = (workspaceId: number, body: SnapshotIn) =>
  api.post<SnapshotSaved>(`/api/workspaces/${workspaceId}/snapshots`, body);

export function useAccountsOverview(workspaceId: number) {
  return useQuery({
    queryKey: queryKeys.accountsOverview(workspaceId, true),
    queryFn: () => getAccountsOverview(workspaceId),
  });
}

export function useAccount(workspaceId: number, accountId: number | null) {
  return useQuery({
    queryKey: queryKeys.account(workspaceId, accountId ?? 0),
    queryFn: () => getAccount(workspaceId, accountId!),
    enabled: accountId !== null,
  });
}

/** A write in the workspace that resolves once the workspace's queries
 * have refetched: the dashboard reads these figures too, and the page
 * should show the new ones before it unlocks. */
function useWorkspaceWrite<A, R>(
  workspaceId: number,
  write: (args: A) => Promise<R>,
) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (args: A) => {
      const result = await write(args);
      await queryClient.invalidateQueries({
        queryKey: queryKeys.workspace(workspaceId),
      });
      return result;
    },
  });
}

/** Every account write and the snapshot save. */
export function useAccountWrites(workspaceId: number) {
  return {
    create: useWorkspaceWrite(workspaceId, (body: AccountCreate) =>
      createAccount(workspaceId, body),
    ),
    update: useWorkspaceWrite(
      workspaceId,
      ({ id, body }: { id: number; body: AccountUpdate }) =>
        updateAccount(workspaceId, id, body),
    ),
    retire: useWorkspaceWrite(workspaceId, (id: number) =>
      retireAccount(workspaceId, id),
    ),
    unretire: useWorkspaceWrite(workspaceId, (id: number) =>
      unretireAccount(workspaceId, id),
    ),
    save: useWorkspaceWrite(workspaceId, (body: SnapshotIn) =>
      saveSnapshot(workspaceId, body),
    ),
  };
}

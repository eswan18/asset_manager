/** The Cash flows page and its two drawers: the overview, cash flow writes,
 * and category writes (web/api_cash_flows.py, web/api_routes.py). */
import {
  keepPreviousData,
  queryOptions,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useSearchParams } from "react-router";

import {
  parsePeriod,
  type Direction,
  type FlowFields,
  type Period,
  type Unit,
} from "@/lib/cash-flows";

import { api } from "./client";
import { queryKeys } from "./queryKeys";

export type { Direction, Period, Unit };

/** Money is decimal text with two places ("1215.48"); only `net` and
 * `other_net` can be negative. Colors are CSS values naming the tokens
 * ("var(--liability-2)"). Shares are display text ("28%", "<1%"). */

/** A cash flow as a card lists it, with every field its drawer edits. */
export interface FlowRow {
  id: number;
  name: string;
  direction: Direction;
  /** Each time it happens, as entered. */
  amount: string;
  every: number;
  unit: Unit;
  /** "every month", "every 2 weeks". */
  every_text: string;
  /** Unsigned, in the overview's period. */
  per_period: string;
  category_id: number | null;
  description: string | null;
  is_estimate: boolean;
}

/** Income first, then each expense category with flows in position order,
 * then Uncategorized. */
export interface FlowCard {
  direction: Direction;
  /** Null for Income and Uncategorized. */
  category_id: number | null;
  name: string;
  color: string;
  total: string;
  /** An expense card's share of income; null for Income, or with no income. */
  share: string | null;
  flows: FlowRow[];
}

/** One piece of the "Where income goes" bar, in order. */
export interface BarSlice {
  label: string;
  color: string;
  /** Unrounded percentage of the bar's width. */
  weight: string;
  amount: string;
  share: string | null;
  category_id: number | null;
  left_over: boolean;
}

/** A category as the drawers show it, in display order. */
export interface CategoryRow {
  id: number;
  name: string;
  position: number;
  /** The categories drawer's swatch. */
  color: string;
  /** The cash flow drawer's color for an expense in it. */
  expense_color: string;
  flow_count: number;
  expenses: string | null;
  income: string | null;
}

export type BarState = "normal" | "over" | "no_income";

/** `GET /api/workspaces/{id}/cash-flows/overview?per=`. */
export interface CashFlowsOverview {
  period: Period;
  can_edit: boolean;
  /** No cash flows at all. */
  empty: boolean;
  /** "Short each …" (expenses exceed income) rather than "Left over each …". */
  short: boolean;
  net: string;
  income: string;
  expenses: string;
  expenses_share: string | null;
  /** The headline's second figure: year, or month when the period is year. */
  other_period: Period;
  other_net: string;
  estimates: number;
  bar_state: BarState;
  slices: BarSlice[];
  over_by: string | null;
  over_share: string | null;
  /** Over income: where income runs out, an unrounded percentage. */
  marker: string | null;
  cards: FlowCard[];
  categories: CategoryRow[];
  income_color: string;
  uncategorized_color: string;
}

/** A saved cash flow (`cash_flow_json`): its rates are signed, expenses
 * negative. */
export interface SavedFlow {
  id: number;
  name: string;
  direction: Direction;
  amount: string;
  every: number;
  unit: Unit;
  category_id: number | null;
  description: string | null;
  is_estimate: boolean;
  per_day: string;
  per_month: string;
  per_year: string;
}

export interface Category {
  id: number;
  name: string;
  position: number;
}

const base = (workspaceId: number) => `/api/workspaces/${workspaceId}`;

export const getCashFlowsOverview = (workspaceId: number, per: Period) =>
  api.get<CashFlowsOverview>(`${base(workspaceId)}/cash-flows/overview`, {
    query: { per },
  });

export const createCashFlow = (workspaceId: number, fields: FlowFields) =>
  api.post<SavedFlow>(`${base(workspaceId)}/cash-flows`, fields);

export const updateCashFlow = (
  workspaceId: number,
  flowId: number,
  fields: FlowFields,
) => api.patch<SavedFlow>(`${base(workspaceId)}/cash-flows/${flowId}`, fields);

export const deleteCashFlow = (workspaceId: number, flowId: number) =>
  api.delete<unknown>(`${base(workspaceId)}/cash-flows/${flowId}`);

export const createCategory = (workspaceId: number, name: string) =>
  api.post<Category>(`${base(workspaceId)}/cash-flow-categories`, { name });

export const renameCategory = (
  workspaceId: number,
  categoryId: number,
  name: string,
) =>
  api.patch<Category>(
    `${base(workspaceId)}/cash-flow-categories/${categoryId}`,
    { name },
  );

export const moveCategory = (
  workspaceId: number,
  categoryId: number,
  direction: "up" | "down",
) =>
  api.post<{ categories: Category[] }>(
    `${base(workspaceId)}/cash-flow-categories/${categoryId}/move`,
    { direction },
  );

export const deleteCategory = (workspaceId: number, categoryId: number) =>
  api.delete<unknown>(
    `${base(workspaceId)}/cash-flow-categories/${categoryId}`,
  );

/** The period in the URL (`?per=`), month when it is missing or unknown,
 * and the page's link in that period (`base` is the workspace's): where
 * the drawers close to. */
export function useCashFlowsPeriod(base: string): {
  period: Period;
  pageHref: string;
} {
  const [params] = useSearchParams();
  const period = parsePeriod(params.get("per"));
  return { period, pageHref: `${base}/cash-flows?per=${period}` };
}

/** The page's query for one period (its drawers read it too): what
 * `useCashFlowsOverview` reads and a link to the page prefetches
 * (api/prefetch.ts). */
export const cashFlowsOverviewQuery = (workspaceId: number, per: Period) =>
  queryOptions({
    queryKey: queryKeys.cashFlowsOverview(workspaceId, per),
    queryFn: () => getCashFlowsOverview(workspaceId, per),
  });

/** The page's model for one period. Switching periods keeps showing the
 * last one until the next arrives, so the page doesn't blank. */
export function useCashFlowsOverview(workspaceId: number, per: Period) {
  return useQuery({
    ...cashFlowsOverviewQuery(workspaceId, per),
    placeholderData: keepPreviousData,
  });
}

/** Invalidate (and refetch) each key prefix a write changed. The writes
 * below return this from `onSuccess`, so each resolves once the fresh data
 * has arrived and a drawer closes onto the page as it now is. */
function useRefresh() {
  const queryClient = useQueryClient();
  return (...keys: (readonly unknown[])[]) =>
    Promise.all(
      keys.map((queryKey) => queryClient.invalidateQueries({ queryKey })),
    );
}

/** Create, update and delete a cash flow. */
export function useCashFlowWrites(workspaceId: number) {
  const refresh = useRefresh();
  const onSuccess = () => refresh(queryKeys.cashFlows(workspaceId));
  return {
    create: useMutation({
      mutationFn: (fields: FlowFields) => createCashFlow(workspaceId, fields),
      onSuccess,
    }),
    update: useMutation({
      mutationFn: ({ id, fields }: { id: number; fields: FlowFields }) =>
        updateCashFlow(workspaceId, id, fields),
      onSuccess,
    }),
    remove: useMutation({
      mutationFn: (flowId: number) => deleteCashFlow(workspaceId, flowId),
      onSuccess,
    }),
  };
}

/** Add, rename, move and delete a category. Each changes the overview
 * (cards, bar and drawers follow the categories) and the category list. */
export function useCategoryWrites(workspaceId: number) {
  const refresh = useRefresh();
  const onSuccess = () =>
    refresh(
      queryKeys.cashFlows(workspaceId),
      queryKeys.cashFlowCategories(workspaceId),
    );
  return {
    create: useMutation({
      mutationFn: (name: string) => createCategory(workspaceId, name),
      onSuccess,
    }),
    rename: useMutation({
      mutationFn: ({ id, name }: { id: number; name: string }) =>
        renameCategory(workspaceId, id, name),
      onSuccess,
    }),
    move: useMutation({
      mutationFn: ({
        id,
        direction,
      }: {
        id: number;
        direction: "up" | "down";
      }) => moveCategory(workspaceId, id, direction),
      onSuccess,
    }),
    remove: useMutation({
      mutationFn: (categoryId: number) =>
        deleteCategory(workspaceId, categoryId),
      onSuccess,
    }),
  };
}

/** The dashboard's data: `GET /api/workspaces/{id}/dashboard?range=`
 * (web/api_dashboard.py, whose Pydantic models these types mirror). */
import {
  keepPreviousData,
  queryOptions,
  useQuery,
} from "@tanstack/react-query";

import { api } from "./client";
import { queryKeys } from "./queryKeys";

/** A decimal string with two places: "12400.00", "-17.44". */
export type Money = string;
/** An ISO date: "2026-10-24". */
export type IsoDate = string;
export type Kind = "asset" | "liability";

export const RANGE_KEYS = ["6m", "1y", "all"] as const;
export type RangeKey = (typeof RANGE_KEYS)[number];
export const DEFAULT_RANGE: RangeKey = "1y";

/** A valid `?range=`; anything else is the default (dashboard.parse_range). */
export function parseRange(value: string | null): RangeKey {
  return (RANGE_KEYS as readonly string[]).includes(value ?? "")
    ? (value as RangeKey)
    : DEFAULT_RANGE;
}

export interface RangeOption {
  key: RangeKey;
  /** "6M", "1Y" or "All". */
  label: string;
}

/** Net worth now minus at the snapshot closest to 30 days before. */
export interface Change {
  since: IsoDate;
  amount: Money;
  /** One place, rounded half up ("1.5", "-0.3"); null when the earlier net
   * worth was zero. */
  percent: string | null;
}

export interface Point {
  date: IsoDate;
  assets: Money;
  liabilities: Money;
  net_worth: Money;
}

/** One category's share of the latest snapshot. `color` is a CSS color
 * naming tokens ("var(--asset)", "color-mix(…)"), for the current theme. */
export interface CategoryTotal {
  key: string;
  label: string;
  amount: Money;
  color: string;
}

/** A phone's stacked-bar segment; `share` is percent of the track. */
export interface BarSegment {
  key: string;
  label: string;
  color: string;
  share: string;
}

export interface CardAccount {
  id: number;
  name: string;
  /** Null (shown as —) with no row on the latest snapshot. */
  amount: Money | null;
  /** "15% of gains, computed", or null. */
  computed: string | null;
}

export interface CardGroup {
  key: string;
  label: string;
  total: Money;
  accounts: CardAccount[];
}

/** A button, for editors. `path` is relative to the workspace's base:
 * "/accounts" or "/accounts/new?type=asset". */
export interface Action {
  label: string;
  path: string;
}

export interface DashboardCard {
  kind: Kind;
  title: string;
  /** Null (shown as —) only before the first snapshot, over listed accounts. */
  total: Money | null;
  groups: CardGroup[];
  /** Before the first snapshot: an empty card's text and add button. */
  empty?: string | null;
  add?: Action | null;
}

export interface Step {
  title: string;
  text: string;
  done: boolean;
  action: Action | null;
}

/** The getting-started state (board Y). */
export interface Onboarding {
  steps: Step[];
  has_accounts: boolean;
}

export interface Dashboard {
  has_data: boolean;
  can_edit: boolean;
  range: RangeKey;
  ranges: RangeOption[];
  net_worth: Money | null;
  last_snapshot: IsoDate | null;
  change: Change | null;
  /** Oldest first, within the range counted back from the latest snapshot. */
  history: Point[];
  categories: Record<Kind, CategoryTotal[]>;
  bars: Record<Kind, BarSegment[]>;
  /** Assets, then Liabilities. */
  cards: DashboardCard[];
  onboarding: Onboarding | null;
}

export const getDashboard = (workspaceId: number, range: RangeKey) =>
  api.get<Dashboard>(`/api/workspaces/${workspaceId}/dashboard`, {
    query: { range },
  });

/** The dashboard's query for a range: what `useDashboard` reads and a link
 * to the dashboard prefetches (api/prefetch.ts). */
export const dashboardQuery = (workspaceId: number, range: RangeKey) =>
  queryOptions({
    queryKey: queryKeys.dashboard(workspaceId, range),
    queryFn: () => getDashboard(workspaceId, range),
  });

/** The dashboard for a range. Changing the range keeps the last one's data
 * on screen (`isPlaceholderData`) until the new one arrives; another
 * workspace's never stands in. */
export function useDashboard(workspaceId: number, range: RangeKey) {
  return useQuery({
    ...dashboardQuery(workspaceId, range),
    placeholderData: (previous, previousQuery) =>
      previousQuery?.queryKey[1] === workspaceId
        ? keepPreviousData(previous)
        : undefined,
  });
}

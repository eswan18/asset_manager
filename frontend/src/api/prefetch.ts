/** Prefetch on intent: a link starts loading what its destination needs
 * as the pointer reaches it (or focus, or a finger), so that by the click
 * there is usually nothing to wait for.
 *
 * Each area's query options (`accountQuery`, `dashboardQuery`, …) live in
 * its own `api/<area>.ts` and are what its hook reads, so a prefetch fills
 * exactly the cache entry the destination will read. Within the default
 * `staleTime` (30s, api/queryClient.ts) the destination reuses it rather
 * than refetching, and a prefetch of something already fresh, or already
 * in flight, sends nothing. */
import {
  useQueryClient,
  type FetchQueryOptions,
  type QueryClient,
  type QueryKey,
} from "@tanstack/react-query";

import { parsePeriod } from "@/lib/cash-flows";

import { accountsOverviewQuery } from "./accounts";
import { cashFlowsOverviewQuery } from "./cash-flows";
import { DEFAULT_RANGE, dashboardQuery } from "./dashboard";
import { settingsQuery } from "./settings";

/** One query to prefetch. Make it with `prefetching(options)`. */
export type Prefetch = (queryClient: QueryClient) => Promise<void>;

/** A prefetch of one area's query options (`prefetching(accountQuery(…))`). */
export function prefetching<
  TQueryFnData,
  TError,
  TData,
  TQueryKey extends QueryKey,
>(
  options: FetchQueryOptions<TQueryFnData, TError, TData, TQueryKey>,
): Prefetch {
  return (queryClient) => queryClient.prefetchQuery(options);
}

/** The handlers to spread on a link (or any element) that run `prefetches`
 * on pointerenter, focus and touchstart:
 *
 *   <Link to={…} {...usePrefetch(prefetching(accountQuery(ws, id)))}>
 */
export function usePrefetch(...prefetches: Prefetch[]) {
  const queryClient = useQueryClient();
  const prefetch = () => {
    for (const run of prefetches) void run(queryClient);
  };
  return {
    onPointerEnter: prefetch,
    onFocus: prefetch,
    onTouchStart: prefetch,
  };
}

/** What a workspace section's page reads first, as its bare link (no
 * search params) opens it: the dashboard's default range, Cash flows by
 * the month. `section` as in components/shell/sections.ts. */
export function pagePrefetch(workspaceId: number, section: string): Prefetch[] {
  switch (section) {
    case "":
      return [prefetching(dashboardQuery(workspaceId, DEFAULT_RANGE))];
    case "accounts":
      return [prefetching(accountsOverviewQuery(workspaceId))];
    case "cash-flows":
    case "cash-flow-categories":
      return [
        prefetching(cashFlowsOverviewQuery(workspaceId, parsePeriod(null))),
      ];
    case "settings":
      return [prefetching(settingsQuery(workspaceId))];
    default:
      return [];
  }
}

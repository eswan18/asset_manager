import { QueryClient } from "@tanstack/react-query";

import { ApiError } from "./client";

/** A failed read is retried twice, unless the server answered with a 4xx:
 * that answer won't change on a retry (and a 401 has already navigated). */
function retry(failures: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status < 500) return false;
  return failures < 2;
}

export function makeQueryClient(): QueryClient {
  return new QueryClient({
    defaultOptions: {
      queries: {
        // Fresh for 30s: switching tabs within that reuses what's loaded;
        // after it, data refetches on mount and when the window regains
        // focus (someone else may have saved in the meantime).
        staleTime: 30_000,
        refetchOnWindowFocus: true,
        retry,
      },
      mutations: { retry: false },
    },
  });
}

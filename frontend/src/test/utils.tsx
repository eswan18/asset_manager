/** Test helpers: a fake API and the app's router in memory. */
import type { ReactElement } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  render,
  screen,
  waitFor,
  type ByRoleOptions,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  createMemoryRouter,
  RouterProvider,
  type RouteObject,
} from "react-router";
import { expect, vi } from "vitest";

import type { Me, MyInvite } from "@/api/shell";
import { Toaster } from "@/components/ui/toaster";
import { routes as appRoutes } from "@/router";

export interface FakeResponse {
  status?: number;
  body?: unknown;
}

type Handler = (request: {
  url: URL;
  init: RequestInit;
  body: unknown;
}) => FakeResponse | Promise<FakeResponse>;

/** Stub `fetch` with handlers keyed "METHOD /path" (no query string). An
 * unhandled request fails the test loudly. Returns the mock, whose calls
 * are `[url, init]`. */
export function mockApi(handlers: Record<string, Handler | FakeResponse>) {
  const fetchMock = vi.fn(
    async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = new URL(String(input), "http://localhost");
      const method = init?.method ?? "GET";
      const handler = handlers[`${method} ${url.pathname}`];
      if (!handler) throw new Error(`Unexpected request: ${method} ${url}`);
      const body =
        typeof init?.body === "string" ? JSON.parse(init.body) : undefined;
      const answer =
        typeof handler === "function"
          ? await handler({ url, init: init ?? {}, body })
          : handler;
      return new Response(
        answer.body === undefined ? null : JSON.stringify(answer.body),
        {
          status: answer.status ?? 200,
          headers: { "Content-Type": "application/json" },
        },
      );
    },
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

export const ME: Me = {
  id: 1,
  email: "me@example.com",
  name: "Ethan Swan",
  is_admin: false,
  workspaces: [
    { id: 1, name: "Household", role: "owner" },
    { id: 2, name: "Lake house", role: "viewer" },
  ],
};

export function invite(overrides: Partial<MyInvite> = {}): MyInvite {
  return {
    id: 7,
    workspace_id: 3,
    workspace_name: "Jordan's",
    email: ME.email,
    role: "editor",
    invited_by: 2,
    sender_name: "Jordan Swan",
    acceptable: true,
    created_at: "2026-10-20T15:00:00+00:00",
    expires_at: "2026-11-03T15:00:00+00:00",
    ...overrides,
  };
}

/** The shell's two reads, answered. */
export function shellApi(
  me: Me = ME,
  invites: MyInvite[] = [],
): Record<string, FakeResponse> {
  return {
    "GET /api/me": { body: me },
    "GET /api/invites": { body: { invites } },
  };
}

/** Render the app's routes (or `routes`) at `path`, with a fresh query
 * client and the toaster. */
export function renderRoute(
  path: string,
  { routes = appRoutes }: { routes?: RouteObject[] } = {},
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  const user = userEvent.setup();
  const result = render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
      <Toaster />
    </QueryClientProvider>,
  );
  return { ...result, router, queryClient, user };
}

/** The open drawer (`name` and the like as for `findByRole("dialog")`) once
 * it has loaded: a drawer opens at once, busy, and its form replaces the
 * skeleton when the data lands. */
export async function findSheet(options?: ByRoleOptions) {
  await screen.findByRole("dialog", options);
  await waitFor(() => {
    const sheet = screen.getByRole("dialog", options);
    expect(sheet).not.toHaveAttribute("aria-busy");
    expect(sheet.querySelector("[aria-busy=true]")).toBeNull();
  });
  return screen.getByRole("dialog", options);
}

/** A request the test answers when it chooses: `handler` for `mockApi`,
 * and `release()` to let the response through. */
export function held(answer: FakeResponse = {}) {
  let release: () => void = () => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  const calls = { count: 0 };
  const handler: Handler = async () => {
    calls.count += 1;
    await gate;
    return answer;
  };
  return { handler, release: () => release(), calls };
}

/** Render one element with a query client and a router around it. */
export function renderWithProviders(ui: ReactElement, path = "/") {
  return renderRoute(path, { routes: [{ path: "*", element: ui }] });
}

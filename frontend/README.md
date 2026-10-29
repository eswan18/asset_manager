# Sensibility frontend

The web dashboard: every page but `/login`
(`docs/superpowers/specs/2026-10-28-react-frontend-design.md`). Vite, React
19, TypeScript (strict), React Router 7 (library mode), TanStack Query 5,
Tailwind 4 with the design tokens, Radix primitives copied in shadcn-style,
sonner for flashes, Vitest + Testing Library. The stack and versions match
footstrike-dashboard (its lockfile seeded this one; versions are pinned
exactly).

FastAPI serves the build from the root (`src/sensibility/web/spa.py`):
`/assets/…` cached for a year, and `index.html` (never cached) for every GET
no server route claims, so `/`, `/welcome` and `/workspaces/…` are this app's.
The server keeps `/api/…`, `/login`, `/auth/…`, `/logout`, `/health`, `/mcp`,
`/.well-known/…` and the API docs. `/app/…`, where the app lived while it was
built, redirects permanently to the same path without the prefix.

## Commands

```bash
npm ci                # install (Node 24)
npm run dev           # Vite on :5173, proxying /api, /auth, /login, /logout, /health to :8000
npm run lint          # eslint + prettier --check
npm run format        # prettier --write
npm run typecheck     # tsc -b
npm test              # vitest run (npm run test:watch to watch)
npm run build         # tsc -b && vite build -> dist/
```

### Local development

1. `ENV=dev uv run sensibility serve` (the API, on :8000).
2. Log in at <http://localhost:8000/login>. The session cookie is per host,
   not per port, so it also covers Vite's port.
3. `npm run dev` here and open <http://localhost:5173/>.

Or `npm run build` and open <http://localhost:8000/> (no hot reload).
Point the proxy elsewhere with `SENSIBILITY_BACKEND=http://host:port`.

## Layout

```
src/
  main.tsx, App.tsx        providers (QueryClient, router, toaster)
  router.tsx               every route (each page and drawer lazy), preloading
  page-routes.json         the router's page paths, for the phone sweep
  index.css                Tailwind + the token theme + the phone/desk variants
  styles/tokens.css        the design tokens, light + dark (from base.html)
  api/
    client.ts              api.get/post/patch/put/delete, ApiError
    queryClient.ts         defaults (30s fresh, refetch on focus, no 4xx retries)
    queryKeys.ts           every query key
    shell.ts               /api/me and your invites (types, fetchers, hooks)
    prefetch.ts            usePrefetch, prefetching, pagePrefetch
  components/ui/           primitives: Button, Card, SegmentedControl, Sheet,
                           DropdownMenu, Field/Input/Select/Textarea/Check/
                           MoneyInput, Tag, EmptyCard, Toaster + flash,
                           Loading + Skeleton*
  components/shell/        AppShell, header + tab bar, picker, account menu,
                           invite strip, workspace context
  routes/                  one module per page and drawer
  lib/                     pure helpers (node test environment)
  test/                    setup, mockApi/renderRoute helpers, the token rule
```

## Conventions

- **Routes** live in `router.tsx`, one component per page or drawer in
  `routes/`, each loaded lazily as its own chunk through the `load` table;
  `preloadRoutes()` fetches them all in idle time after the first render, so
  a click never waits for one. A new page or drawer goes in `load`, in
  `routes`, and in `page-routes.json` (`router.test.tsx` checks it matches;
  `tests/browser/test_mobile_sweep.py` then needs a phone screen for it).
  Paths keep the Jinja pages' URLs. A drawer is a child route of its page
  under a pathless layout route: the page renders `<Outlet />` and stays
  mounted. Drawers render `<RouteSheet closeTo=…>` and keep the page's search
  params (`?per=`) in `closeTo`. Inside a workspace, `useWorkspace()` gives
  `{id, name, role, base, canEdit, isOwner}`; build links from `base`.
  `useDocumentTitle()` sets the tab title.
- **API**: only through `api` in `api/client.ts`. It sends the session cookie,
  `X-Timezone`, and on mutations `X-Requested-With: sensibility` (the server
  refuses API writes without it). Errors are `ApiError` with the server's
  message; a 401 goes to `/login`. Put each area's types, fetchers and hooks
  in its own `api/<area>.ts` and its keys in `api/queryKeys.ts`; keys inside a
  workspace start `["workspaces", id]`. After a mutation, invalidate the
  narrowest prefix that covers it.
- **Tokens only**: colors come from `styles/tokens.css` by name
  (`bg-surface`, `text-ink`, `text-muted`, `border-rule-strong`, `text-asset`,
  `bg-liability-2`, `bg-danger/10`, `shadow-pill`, `rounded-card`,
  `font-display`, …). Tailwind's palette is removed, and
  `src/test/tokens.test.ts` fails on a hex, `rgb()`, `hsl()` or `oklch()`
  anywhere else.
- **Phones**: one breakpoint. `phone:` is `max-width: 600px`, `desk:` wider;
  Tailwind's `sm:`/`md:` are removed. 44px targets, 16px fields (the
  primitives do both), nothing sideways, `bottom: var(--tabbar-h)` for
  anything fixed to the bottom, `px-gutter` for side padding.
- **Flashes**: `flash.success(text)` / `flash.error(text)` from
  `components/ui/toaster`.
- **Loading** (see below): a route never renders nothing while its data is
  on its way, every write's button is `busy`, and links prefetch.
- **Tests**: Vitest + Testing Library beside the code (`*.test.tsx`);
  `mockApi` and `renderRoute` in `src/test/utils.tsx`. End-to-end tests are
  the Python Playwright suite (`tests/browser/test_spa_*.py`), which builds
  this app if `dist/` is missing or stale.

## Loading

A click always does something at once, usually there is nothing to wait
for, and what does wait says so.

- **Skeletons** (`components/ui/skeleton.tsx`): while a page's data loads it
  shows a skeleton in its own layout (headline, cards with a few rows, the
  chart at its height), never nothing; a page's error state is unchanged.
  Wrap skeleton blocks in `<Loading label="Loading …">`: it is `aria-busy`,
  names what is coming for screen readers, and **fades in only after
  150ms**, so a quick answer never flashes a skeleton. That delay is the one
  flash-avoidance rule, for pages and drawers alike. Blocks are `Skeleton`
  (chip-colored; `on="bg"` straight on the page background), `SkeletonText`
  (a line, sized like its text), `SkeletonRow`, `SkeletonField`,
  `SkeletonButton`. They pulse, except under reduced motion. The shell
  (`ShellSkeleton`) covers the first paint, before `/api/me`.
- **Drawers open at once.** A drawer route renders its `RouteSheet`
  straight away with a `busy` `SheetContent` (`aria-busy`): the header as
  far as it is known (a new account's type and a new flow's direction come
  from the URL; an unknown title is `SheetTitleLoading`), and the form's
  shape. When the data lands, the same `RouteSheet` renders the real
  `SheetContent`, which takes focus as an opening sheet does (the
  `data-autofocus` field) and does not slide in again. Escape, the scrim and
  ✕ close it throughout.
- **The account drawer is seeded from the page's overview**, which has
  every field the form needs (and its inputs: active, plain, not this one),
  so over the page it opens with the form ready and focused; only the
  history and Retire wait for `GET …/accounts/{id}`. The form's state is set
  once, keyed on the account: the detail landing, or any refetch, never
  resets what was typed. An account the overview doesn't have (another
  tab's) waits for its detail. Cash flow drawers read everything from the
  overview, so over the page they have nothing to wait for.
- **Prefetch on intent** (`api/prefetch.ts`): spread
  `usePrefetch(prefetching(query), …)` on a link and it prefetches on
  pointerenter, focus and touchstart. Each area exports its query options
  (`accountQuery`, `accountsOverviewQuery`, `dashboardQuery`,
  `cashFlowsOverviewQuery`, `settingsQuery`) and its hook reads the same
  ones, so they can't drift; `pagePrefetch(workspaceId, section)` is what a
  section's bare link opens. Used by account rows (the detail), the tab bar
  and the gear (their page), the workspace picker (the same section in your
  other workspaces), and Update balances. The default `staleTime` (30s)
  means a prefetch just before the click is reused, not refetched. Cash flow
  rows and Manage categories need nothing the page hasn't loaded.
- **In place**: data being replaced (a new range or period, a snapshot
  save, a category write) keeps the old figures, dimmed, with `aria-busy`
  and the `updating` utility (index.css; the dim also waits 150ms). The
  controls (the toggles) stay live.
- **Writes**: every button that writes takes `busy` (a spinner, and
  disabled) while its write runs; `disabled` stays for "another write is
  running". In tests, `held()` (`src/test/utils.tsx`) holds a response
  until `release()`, and `findSheet()` waits for a drawer to finish
  loading; `src/routes/loading.test.tsx` and
  `tests/browser/test_spa_loading.py` cover the states.

Where you still wait: a page's first visit in a session (or after 30s)
with nothing prefetched, which shows its skeleton; a deep link or reload
into a drawer (the drawer opens at once over the page's skeleton); the
dashboard chart's own code on its first view; and writes, which resolve only
once the refetch they cause has landed.

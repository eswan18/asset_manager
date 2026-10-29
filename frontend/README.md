# Sensibility frontend

The React app that is replacing the Jinja pages
(`docs/superpowers/specs/2026-10-28-react-frontend-design.md`). Vite, React
19, TypeScript (strict), React Router 7 (library mode), TanStack Query 5,
Tailwind 4 with the design tokens, Radix primitives copied in shadcn-style,
sonner for flashes, Vitest + Testing Library. The stack and versions match
footstrike-dashboard (its lockfile seeded this one; versions are pinned
exactly).

During the build-out FastAPI serves the build under **`/app`**
(`src/sensibility/web/spa.py`); the Jinja pages keep the canonical URLs.

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
3. `npm run dev` here and open <http://localhost:5173/app/>.

Or `npm run build` and open <http://localhost:8000/app/> (no hot reload).
Point the proxy elsewhere with `SENSIBILITY_BACKEND=http://host:port`.

## Layout

```
src/
  main.tsx, App.tsx        providers (QueryClient, router, toaster)
  router.tsx               every route, basename /app
  index.css                Tailwind + the token theme + the phone/desk variants
  styles/tokens.css        the design tokens, light + dark (from base.html)
  api/
    client.ts              api.get/post/patch/put/delete, ApiError
    queryClient.ts         defaults (30s fresh, refetch on focus, no 4xx retries)
    queryKeys.ts           every query key
    shell.ts               /api/me and your invites (types, fetchers, hooks)
  components/ui/           primitives: Button, Card, SegmentedControl, Sheet,
                           DropdownMenu, Field/Input/Select/Textarea/Check/
                           MoneyInput, Tag, EmptyCard, Toaster + flash
  components/shell/        AppShell, header + tab bar, picker, account menu,
                           invite strip, workspace context
  routes/                  one module per page and drawer
  lib/                     pure helpers (node test environment)
  test/                    setup, mockApi/renderRoute helpers, the token rule
```

## Conventions

- **Routes** live in `router.tsx`, one component per page or drawer in
  `routes/`. Paths keep the Jinja URLs. A drawer is a child route of its page
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
- **Tests**: Vitest + Testing Library beside the code (`*.test.tsx`);
  `mockApi` and `renderRoute` in `src/test/utils.tsx`. End-to-end tests are
  the Python Playwright suite (`tests/browser/test_spa_*.py`), which builds
  this app if `dist/` is missing or stale.

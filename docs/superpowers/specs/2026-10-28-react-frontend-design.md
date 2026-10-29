# React Frontend

**Date:** 2026-10-28
**Status:** Done. Approved in conversation ("we should do this… parallelize
as much as possible"); Phase A (foundation and API), Phase B (every page
under `/app`) and Phase C (the cutover: the SPA at the canonical URLs, the
Jinja pages and their tests deleted) are all built.

## Why

The Jinja pages make every interaction a full navigation: changing tabs,
the chart's range, the cash-flow period, opening or closing a drawer. The
server re-renders everything and the browser re-parses it, re-runs the scripts
and redraws the chart. It doesn't feel like an app, and the app is becoming
one: the Accounts page is already a hand-written client-side state machine.
The rest of the fleet is React (footstrike-dashboard is a Vite SPA, haruspex
is Next.js), so Sensibility moves to the same stack rather than to htmx.

## Goals

- Interactions that don't reload the page: tabs, toggles, drawers, saves.
- **The same product:** the design system, both themes, the mobile layouts and
  every behavior built in the redesign and mobile pass carry over 1:1. This
  is a re-platforming, not a redesign.
- **The fleet's stack** (footstrike-dashboard), so one set of patterns.
- The JSON API becomes the only interface the browser uses, which also serves
  scripts and the MCP tools' neighbors.

Non-goals: server-side rendering (no Node server; no SEO need), offline
support, changing auth, redesigning anything.

## Stack (matches footstrike-dashboard)

| Concern | Choice |
|---|---|
| Build | Vite, TypeScript (strict), npm, ESLint + Prettier |
| UI | React 19 |
| Routing | React Router 7 (data/"library" mode, no framework mode) |
| Server state | TanStack Query 5 |
| Primitives | Radix UI (shadcn/ui-style components copied in, not a dependency) |
| Styling | Tailwind 4, with the design tokens from `base.html` as CSS variables (light and dark), so components name tokens exactly as the templates do |
| Drawers | Radix Dialog as a sheet (bottom sheet on phones, side drawer on desktop); vaul was considered and not needed |
| Toasts (flashes) | `sonner` |
| Icons | `lucide-react` |
| Charts | Recharts (as footstrike-dashboard; replaces Plotly in the browser) |
| Tests | Vitest + Testing Library; Playwright end to end (the existing Python harness) |

Versions are pinned exactly, matching footstrike-dashboard's lockfile where it
has the package.

## Layout in the repo

`frontend/` at the repo root: its own `package.json`, Vite config, `src/`.
FastAPI serves the built app; there is still one image and one deploy.

```
frontend/src/
  main.tsx, App.tsx        # providers, router
  api/                     # fetch client, typed endpoints, query keys
  components/ui/           # primitives (Button, Card, SegmentedControl, Sheet, …)
  components/shell/        # top bar, picker, tab bar, user menu, invite strip
  routes/                  # one module per page and drawer
  lib/                     # money formatting, formulas, cash-flow rates (pure)
  styles/tokens.css        # the design tokens, light + dark
```

## Serving, routing and auth

- **During the build-out** the SPA lives at **`/app/…`** (router `basename`
  `/app`). The Jinja pages keep serving the canonical URLs, so main stays
  shippable and staging can be compared side by side.
- **At cutover** the SPA takes the canonical paths (`/`,
  `/workspaces/{id}/…`, `/welcome`), the Jinja page routes and templates are
  deleted, and `/app/*` redirects to the same path without the prefix.
- FastAPI serves `frontend/dist`: hashed assets under `/assets/` with long
  caching, and `index.html` (no-cache) for any SPA route. Unknown `/api/…`
  stays a JSON 404, never the SPA.
- URLs keep their shapes: `/workspaces/{id}`, `…/accounts`,
  `…/accounts/new`, `…/accounts/{id}/edit`, `…/cash-flows?per=month`,
  `…/cash-flows/new`, `…/cash-flows/{id}/edit`, `…/cash-flow-categories`,
  `…/settings`, `/welcome`, and `?range=` on the dashboard. **Drawers are
  routes** nested over their page, so opening one is a client navigation and
  closing it (✕, Cancel, Escape, the scrim) goes back to the page without a
  fetch.
- **Auth is unchanged:** the same signed session cookie; `/login`,
  `/auth/*` and `/logout` stay server-side, and `login.html` (with its refused
  states) stays a Jinja page — it is the OAuth boundary and has no
  interactivity. The SPA treats any API 401 as "go to `/login`" (full
  navigation).
- **CSRF:** with cookie auth, every mutating `/api/` request (POST, PATCH,
  PUT, DELETE) must carry `X-Requested-With: sensibility` (a custom header a
  cross-site form can't send and a cross-site `fetch` can't send without a
  CORS preflight, which is never allowed). The server refuses mutations
  without it (403). MCP's bearer-token endpoint is separate and unaffected.
- **Today is the viewer's day:** the client sends `X-Timezone` (from `Intl`)
  on every request; the API already honors it.

## API: what exists and what's added

Exists and is enough: `/api/me`, workspaces (create, get, rename, delete),
members (list, role, remove/leave), invites (create, list, revoke, mine,
accept, decline), cash flows (list with per-period amounts and totals,
create, update, delete), cash-flow categories (list, create, update incl.
position, delete), `GET …/accounts` and `POST …/snapshots`.

Added (each returns exactly what a page renders, computed by the same Python
the Jinja pages use today, so the numbers can't drift):

1. **`GET /api/workspaces/{id}/dashboard?range=6m|1y|all`**: net worth, its
   change over ~30 days, last snapshot date, the history series (date,
   assets, liabilities, net worth), latest category totals per side with each
   category's color token, the account cards (groups and subtotals), and the
   getting-started state for a workspace with no snapshot.
2. **`GET /api/workspaces/{id}/accounts/overview?retired=true|false`**: the
   Accounts page model: groups by category with subtotals, each account's
   latest amount, computed accounts' formula (rate, cost basis, input names)
   and description, retired accounts when asked, the last saved date, the
   date a save would be dated (viewer's today).
3. **Account CRUD:** `GET /api/workspaces/{id}/accounts/{aid}` (the drawer:
   the account, eligible formula inputs, retire warning and blocker, recent
   history), `POST …/accounts`, `PATCH …/accounts/{aid}`,
   `POST …/accounts/{aid}/retire`, `POST …/accounts/{aid}/unretire`, with the
   service's validation messages as `{"error": …}`.
4. **`GET /api/workspaces/{id}/cash-flows/overview?per=day|month|year`**:
   the Cash flows page model: headline (left over or short), the bar's
   slices with shares and colors, the expenses-above-income marker, cards
   (income first, categories, Uncategorized last) with rows and amounts.
5. **`POST /api/workspaces/{id}/cash-flow-categories/{cid}/move`**
   (`direction: up|down`).
6. Whatever settings, welcome and the shell turn out to need beyond the
   existing endpoints (e.g. `can_leave`, sender names on invites); the API
   stream audits and adds them.

Live calculations that must respond per keystroke stay client-side, in pure
TypeScript with tests: the Accounts page's computed values and net worth
(mirroring `formulas.py`), and the cash-flow drawer's rates strip (the
existing exact BigInt-cents logic). Their tests use the same vectors as the
Python tests.

## Pages

Each page is a 1:1 port of today's page and its drawers, desktop and phone,
light and dark, including: the shell (top bar, workspace picker as the
phone title, bottom tab bar on phones, account menu, invite strip, flashes
as toasts), Dashboard (range toggle; chart lines plus category columns on
desktop, lines plus stacked bars on phones; cards; getting-started state),
Accounts (staged edits with "was $X", the save bar with live net worth,
sessionStorage across reloads, Discard, computed accounts recomputing, show
retired, the account drawer in every state), Cash flows (period toggle,
headline, bar, cards, the cash-flow drawer with its rates strip, the
categories drawer with move/rename/delete/add), Settings (owner, editor,
viewer; confirms in place), Welcome.

Mobile rules from `2026-10-26-mobile-design.md` hold unchanged: one 600px
breakpoint, 44px targets, 16px fields, nothing scrolls sideways, safe areas.

## Testing

- **API:** pytest against the container, as today, for every new endpoint
  (including another workspace's ids being 404 and the role rules) and the
  CSRF header rule. The automatic route sweeps keep covering new routes.
- **Frontend unit:** Vitest + Testing Library for components and the pure
  `lib/` code.
- **End to end:** the existing Python Playwright harness (`tests/browser`),
  which runs the app under uvicorn against the test container, pointed at the
  built SPA. The phone-layout helper (`assert_fits_phone`) and the page sweep
  carry over. CI builds the frontend once and runs these as today.
- At cutover, the Jinja page tests are deleted with the templates; the
  behavior they covered must already be covered by API or browser tests.

## Build and CI

- Dockerfile: a Node build stage (`npm ci && npm run build`) whose `dist/`
  is copied into the Python image.
- CI: a frontend job (npm ci, lint, typecheck, Vitest, build) in parallel
  with the Python jobs; the browser-test job builds (or downloads) the
  frontend first.
- Local dev: `npm run dev` (Vite, with `/api`, `/auth`, `/login`, `/logout`
  proxied to uvicorn) next to `uv run sensibility serve`.

## Workstreams

| Phase | Stream | Depends on |
|---|---|---|
| A | **Foundation:** scaffold, tokens, primitives, shell, router skeleton under `/app`, API client and query setup, FastAPI serving + CSRF rule, Dockerfile, CI, Playwright harness | — |
| A | **API 1:** dashboard, accounts overview, account CRUD and detail | — |
| A | **API 2:** cash-flows overview, category move, settings/welcome/shell gaps | — |
| B | **Dashboard** page | Foundation, API 1 |
| B | **Accounts** page + account drawer | Foundation, API 1 |
| B | **Cash flows** page + both drawers | Foundation, API 2 |
| B | **Settings + Welcome** | Foundation, API 2 |
| C | **Cutover** (done): canonical routes, delete Jinja pages and their tests, docs | all of B |

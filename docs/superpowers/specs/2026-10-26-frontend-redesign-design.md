# Frontend Redesign

**Date:** 2026-10-26
**Status:** The three main pages (Dashboard, Accounts, Cash flows) are
approved as mockups in light and dark. The workspace-in-URL and dark mode
decisions are made, so building can start. The three pages and the account
form are built, and so are the cash flow form, category management,
workspace settings and the welcome page. Login, the empty states and
expenses above income (boards X, Y, AA) are built too, and so are the
invite strip and the flash restyle (board Z). Every approved board is
built.

**Mockups:** [Design canvas](https://claude.ai/artifact/BMRjmDM7b239Ro2SbBtvsR)
(private; share it from its Share menu). The chosen boards are **H**
(dashboard), **Accounts I**, **Cash flows N**, **Account form Q** (drawer
over Accounts), **Cash flow form R** (drawer over Cash flows),
**Categories T** (drawer over Cash flows), **Settings V** (workspace
settings, two columns), **Welcome W** (no workspace yet), **Login X**,
**Empty workspace Y**, **Invite strip Z** and **Expenses over income AA**. The other boards are the
alternatives we rejected, kept for reference. Every number in the mockups is
sample data.

## Goal

A cleaner, lighter UI for the app now that it has workspaces and cash
flows. The visual language is shared across pages, so the three pages can be
built in parallel once the shell exists. Nothing here changes the data model.

## Non-goals (this iteration)

- A single-page app. Pages stay server-rendered Jinja with a little JS, which
  means one build and one deploy, and the JSON API already serves agents.
- The app's name. Every mockup shows `[App name]`, and the name lives in one
  place in the templates (see the MCP spec: the rename is pending).
- New data. Every page is built from data the service layer already has,
  apart from the small helpers noted under each page.

## Visual language

Taken from mockup direction C. It is the app's own look, not the Footstrike
design system.

### Brand

The brand assets (Oct 2026) are a silver coin with a deep green serif S
(`#053C32`) and an outlined serif wordmark. They live in `frontend/public/`:
`favicon.svg`/`.ico`, `apple-touch-icon.png`, `icon-192`/`512.png` and
`site.webmanifest`, and `wordmark.svg` (the wordmark alone, cut from the
lockup). The header's lockup is the favicon coin beside the wordmark, drawn
as a mask filled with `--ink` so it follows the theme (`Logo` in
`components/shell/logo.tsx`; `login.html` draws the same). The palette took
its green from the coin and its warm neutrals from the brand's paper ground.

### Tokens

| Token | Light | Dark | Use |
|---|---|---|---|
| `--bg` | `#F4F3EE` | `#0D1412` | Page background |
| `--surface` | `#FFFFFF` | `#161F1C` | Cards, inactive toggle segment |
| `--ink` | `#13211D` | `#E9EEEB` | Text, active nav pill (with `--surface` text), net worth line |
| `--muted` | `#4C5753` | `#9AA6A1` | Secondary text (passes 4.5:1 on both `--bg` and `--surface`) |
| `--rule` | `#EFEEE9` | `#212B28` | Row dividers |
| `--rule-strong` | `#D9D9D1` | `#374440` | Input borders, axes, dashed dividers |
| `--grid` | `#EAE9E3` | `#24302C` | Chart gridlines |
| `--chip` | `#F4F3EE` | `#212B28` | Secondary buttons (+ Add), toggle track, tag background |
| `--input` | `#FFFFFF` | `#111816` | Input background |
| `--asset` | `#17694F` | `#5EC29B` | Assets, income, links, focus/edited border |
| `--asset-2` | `#8CC4AC` | `#2B6A53` | Second asset category |
| `--asset-tint` | `#EAF3EE` | `#16302A` | Edited input background |
| `--primary` / `--on-primary` | `#053C32` / `#FFFFFF` | `#5EC29B` / `#0D1412` | Primary buttons |
| `--liability` | `#B4530F` | `#F08C4A` | Liabilities, expenses |
| `--liability-2` | `#D9772E` | `#C46A2C` | More liability / expense categories |
| `--liability-3` | `#E9A066` | `#8F4F24` | |
| `--liability-4` | `#F3C79E` | `#5E3A20` | |
| `--leftover` | `#D9ECE2` | `#1F3B31` | "Left over" slice on Cash flows |
| `--estimate-bg` / `--estimate-fg` | `#FFF4E5` / `#8A4B0C` | `#3A2A12` / `#F5C27A` | `≈` estimate tag |
| `--danger` | `#B42318` | `#F97066` | Delete, short each month |
| `--danger-tint` | `#FDECEA` | `#3A1C1A` | Behind danger text ("Access is invite-only for now.") |
| `--bar-bg` / `--bar-fg` | `#13211D` / `#FFFFFF` | `#25302C` / `#E9EEEB` | Sticky save bar |
| `--bar-muted` / `--bar-border` | `#B5BEBA` / `#13211D` | `#A8B3AE` / `#3F4C47` | Save bar secondary text, its border and the Discard outline |
| `--shadow` | `rgba(0,0,0,.06)` | `rgba(0,0,0,.4)` | Nav, picker and toggle shadows |
| `--scrim` | `rgba(19,33,29,.35)` | `rgba(0,0,0,.55)` | Over the page behind a drawer |

Each category takes a color from its ramp, strongest first in order of
size, so the largest segment of a bar is the strongest color. Assets and
income are always green; liabilities and expenses are always orange. In both
themes the ramps fade toward the page background, and two colors that must
be told apart also differ in lightness.

### Type

- **Source Serif 4** (500–700) for headings and the large figures, to sit
  with the serif wordmark (it replaced Space Grotesk with the brand assets,
  Oct 2026).
- **Inter** (400–600) for everything else.
- Every number uses `font-variant-numeric: tabular-nums`.
- Scale: hero figure 64px, card titles 20px, body 15px, labels 13px,
  footnotes 12px.

### Shape and spacing

- Cards are `--surface` with a 20px radius and 28–32px padding, with 16px between
  cards. The content column is at most 1160px wide.
- Buttons, nav and toggles are pills (radius 999px). Inputs have a 10px
  radius.
- Every touch target is at least 44px. Inputs are at least 40px tall, inside
  rows at least 52px tall.
  A control may look smaller than its target: the category move arrows
  are 40×26 chips, each inside a 44×44 button that reaches into the row's
  padding.

### Light and dark

Both themes ship at launch, as the current app does, following the system
setting (`prefers-color-scheme`). The tokens are defined once on `:root` for
light and overridden for dark, so the templates name only tokens and never
a hex value. On the canvas, every chosen board has a **theme** tweak, and the
"Dark mode" row shows each page in dark. New screens are designed the same
way, in both themes.

## Shell (every page)

- **Header:** wordmark on the left, pill nav in the middle (Dashboard /
  Accounts / Cash flows; the active one is ink-filled), workspace picker on
  the right (`<select>` with a visible "Workspace" label), then a round gear
  button to the workspace's settings (ink-filled, `aria-current`, when on
  them), then the user menu: an avatar button opening your name and email,
  **New workspace** (to `/welcome`) and **Log out** (which ends identity's
  session too; see Login). The settings button is a cog outline
  (`currentColor`, `aria-hidden`).
- **Invite strip and flashes** (board Z) sit at the top of the content,
  strips first; see "Invite strip and flashes" below. Pages outside a
  workspace (welcome) show only the wordmark and the user menu.
- **Workspace picker:** lists your live workspaces. Choosing one goes to the
  same page in that workspace. See "Workspace in the URL" below.
- **Narrow screens:** the header wraps, and any two-column card grid
  (`repeat(auto-fit, minmax(min(100%, 420px), 1fr))`) drops to one column.
  Wide grids scroll inside their own box, never the page.

### Workspace in the URL (decided)

Every page names its workspace in its path, using the API's own prefix: a
page's path is the matching API path without `/api` (`/api/workspaces/1/accounts`
is the data behind `/workspaces/1/accounts`).

| Page | Path |
|---|---|
| Dashboard | `/workspaces/{workspace_id}` (like `GET /api/workspaces/{workspace_id}`) |
| Accounts | `/workspaces/{workspace_id}/accounts` |
| Account forms | `/workspaces/{workspace_id}/accounts/new`, `/workspaces/{workspace_id}/accounts/{id}/edit`, and their POSTs (including retire and unretire) |
| Save snapshot | `POST /workspaces/{workspace_id}/snapshots` |
| Cash flows | `/workspaces/{workspace_id}/cash-flows` |
| Cash flow form | `/workspaces/{workspace_id}/cash-flows/new` (`?direction=`, `?category_id=`), `/workspaces/{workspace_id}/cash-flows/{id}/edit`, and POSTs `.../cash-flows`, `.../cash-flows/{id}`, `.../cash-flows/{id}/delete` |
| Categories | `/workspaces/{workspace_id}/cash-flow-categories` (`?confirm={id}`, `?add=1`), and POSTs to it (create), `.../{id}` (rename), `.../{id}/move` (`direction=up\|down`), `.../{id}/delete` |
| Workspace settings | `/workspaces/{workspace_id}/settings` (`?confirm=member-{user_id}\|invite-{id}\|leave\|delete`), and POSTs `.../settings` (rename), `.../delete`, `.../members/{user_id}` (role), `.../members/{user_id}/remove` (remove, or leave when it is you), `.../invites` (create), `.../invites/{id}/revoke` |
| Welcome | `/welcome`, and POSTs `/workspaces` (create), `/invites/{id}/accept`, `/invites/{id}/decline` (the API's paths without `/api`; no workspace in them) |

- **Access:** page routes get the same access checks as the API: **404** if
  you are not a live member of that workspace (its existence is not
  revealed), **403** if your role is too low. Path-based page dependencies
  replace `PageViewer` / `PageEditor`, whose "oldest membership" rule goes
  away.
- **Bare paths:** `/` and the old bare paths (`/accounts`, …) redirect to the
  same page in your oldest live workspace, so bookmarks keep working.
  Remembering the last-used workspace (a cookie) can come later.
- **No workspace:** bare paths send a user with no live workspace to the
  welcome page (board W, below), which offers their invites and a form to
  create one. (This replaced a `NoWorkspace` 403.)
- **Why:** this matches the API, a link works when shared, there is no
  hidden state, and two tabs can show two workspaces at once.

## Shared components

| Component | Notes |
|---|---|
| Card | Title row with a 2px bottom rule in the section color (blue for assets, orange for liabilities and expenses) and the total on the right |
| Category group | Muted 13px semibold label with the subtotal on the right, then rows separated by `--rule` |
| Account / flow row | Name (links to its edit page) on the left, value or input on the right |
| Money input | Right-aligned, tabular, `inputmode="decimal"`. **Edited** state: 1.5px `--asset` border, `--asset-tint` background, and "was $X" under the name |
| Computed tag | Formula text and the cost basis input sit under the name. The value shows read-only with a "computed" label |
| Estimate tag | `≈` pill in the estimate colors |
| Segmented toggle | Pill group with `aria-pressed`; 1Y/6M/All on the dashboard, Day/Month/Year on Cash flows |
| Stacked bar | Horizontal; segments separated by a 2px gap; a key below with amounts |
| Sticky save bar | `--bar-bg` bar stuck to the bottom: unsaved count, live net worth and change, Discard, Save snapshot. Near-black in light, a raised grey with a border in dark |

## Pages

### Dashboard: board **H**

**Top card:**
- **Headline:** "Net worth" label; the 64px figure; the change over the
  last ~30 days ("+$6,140 (+1.5%) since Sep 24"); the last snapshot date;
  an **Update balances** button that goes to Accounts.
- **Chart, on one shared dollar scale:**
  - three lines over time: assets (blue), net worth (ink, thicker),
    liabilities (orange), with a key and a 6M / 1Y / All range toggle
  - to the right of the lines, past a dashed divider, two stacked columns
    for today's assets and liabilities split by category
  - each column lines up with where its line ends
- **Category key:** below the chart, with amounts.

**Below the top card:**
- Two half-width cards, **Assets** and **Liabilities**, listing every active
  account under its category with category subtotals and a card total.
- No net worth total at the bottom: it is already the headline.

**Data:**
- Everything comes from `get_all_records` + `get_accounts` (what
  `build_chart_html` uses today).
- **New:** the net worth on the snapshot date closest to 30 days before the
  latest one, for the change line.
- **New:** a per-category latest total, for the columns and key.
- The latest snapshot date is per workspace (never a global `MAX(date)`).

**Chart:**
- Plotly 2.27 is already loaded on this page. Build both the lines and the
  columns as one figure with a shared y-axis (two x-axis domains), so they
  keep the same scale and the lines keep hover.
- Theme the figure from the tokens, and re-theme it when the system theme
  changes, as the dashboard's JS does today, reading the new token names.

### Accounts: board **Accounts I**

- **Page head:** title, then "Saving writes today's snapshot, <date>. Last
  saved <date>." (in the viewer's time zone), then the **Show retired (n)**
  toggle.
- **Cards:**
  - two half-width cards, Assets and Liabilities, each with **+ Add** and the
    card total in its title row
  - rows grouped by category, one money input per plain account
  - computed accounts show the formula, an inline **basis** input, and the
    value computed live in the browser
- **Edits:** an edited input switches to the edited state, and its row shows
  "was $X".
- **Sticky save bar:** "N unsaved changes · Net worth $X (+$Y)", **Discard**
  and **Save snapshot**.

Behavior is unchanged from today (`accounts.html` and `POST /snapshots`):
- edits stay in the page and in `sessionStorage` until saved
- a save is all-or-nothing
- saving again on the same day replaces that day's snapshot
- retired accounts are hidden unless the toggle is on

Unequal card heights are fine: the user chose to keep the empty space under
Liabilities.

The mockup has 14 assets and 9 liabilities, the real account count. Real
data puts a house, crypto and a mortgage under "Uncategorized". New account
categories (Real estate, Crypto, Loans) would each be one value in
`AccountCategory` plus a migration widening the CHECK. They are a separate
backend task, not part of this design.

### Cash flows: board **Cash flows N** (new page)

**Top card:**
- **Headline:** "Left over each month" (the net), "of $X income · $Y a year
  · ≈ N estimates", the **Day / Month / Year** toggle (changes every figure
  on the page), and **+ Add cash flow**.
- **"Where income goes":** one bar, 100% = income, split into each expense
  category plus a pale **Left over** slice, with a key giving each slice's
  amount and share of income.

**Category cards:**
- A grid of category cards, Income first, then each expense category in its
  `position` order, with **Uncategorized** last if it has any flows.
- Each card shows: a color chip, the name, the total for the period, its
  share of income, and rows reading "name ≈ / $amount every N unit /
  per-period value".
- Each card has its own **+ Add**, and a dashed **+ New category** card
  closes the grid.

**Data:**
- Everything comes from `repo.get_cash_flows` and the category list.
- **New:** per-category totals. Sum `per_year` unrounded and round once, the
  way `cashflows.totals()` does, so the categories add up to the total.
- Shares of income are display-rounded; the slices' widths use unrounded
  values.
- Income with no flows: show the bar empty with a prompt to add income,
  never a divide-by-zero.
- Expenses above income: board **AA**, below.

**Editing** (built): each row links to its drawer (board R, below); each
card has a **+ Add** that starts a flow in that card (the Income card's is
income); the head has **Manage categories** and **+ Add cash flow**; the
dashed **+ New category** card opens the categories drawer (board T) with
focus in its add field. Viewers see the page with none of these.

### Expenses above income: board **AA** (built)

- **Headline:** "Short each month" (day / month / year with the toggle), the
  negative net in `--danger`, and "Expenses $X vs income $Y · −$Z a year".
- **Bar:** 100% is total expenses. A vertical ink marker sits at income's
  share of expenses with "▲ Income runs out" under it (kept inside the bar's
  width on phones); the part past it is hatched in `--danger`
  (`repeating-linear-gradient` over `color-mix`). The key gives each slice's
  amount (no shares) and a "Past income $X" entry.
- **Header line:** "Expenses exceed income by $X (N%)", N% of income.
- **Cards** keep "N% of income", so they can add past 100%.
- **Data:** `cash_flows_view` adds `headline`, `marker` (unrounded, like the
  slices' widths) and `over_share` (display-rounded); `over_by` was there.
  Zero income with expenses is still the "no income" state.

### Cash flow form: board **Cash flow form R** (drawer over Cash flows)

Chosen over Cash flows M's inline form. Built the way the account form is:
the drawer's own routes render the real Cash flows page underneath, in its
period (`?per=`), inert behind the scrim; Close, Cancel and Escape go back to
it, and a save or delete redirects to it with a flash.

- **Header:** eyebrow "Edit expense · Food" (direction · category; "New …"
  for a new flow), the flow's name ("New cash flow" for a new one) as the
  title, and a 2px rule in the category's color on the page (income is
  always `--asset`; a category with no expenses yet takes `--liability`).
  The eyebrow and rule follow the direction and category as they change.
- **Body:** an Income / Expense segmented control (two radios); Name;
  "Amount ($) every [N] [unit]" on one row; a live rates strip (a day /
  **a month** / a year, the month larger), rendered by the server with
  `rates()` so it matches the page, and recomputed by the drawer's script
  exactly (integer cents, rounded half up once); Category; the estimate
  checkbox in the estimate colors ("≈ This is an estimate" and one line on
  what that means); an optional Note.
- **Footer:** Delete (danger text, no confirm, edit only) on the left;
  Cancel and Save on the right.
- **Prefill:** `?direction=income|expense` and `?category_id=` (a category
  of this workspace; anything else is ignored), so each card's + Add starts
  in that card.
- **Errors:** every rule is the service's (`cashflows.py`); the form only
  turns its text into numbers and choices. An error re-renders the drawer
  (400) with the user's input and the message at its top.

### Categories: board **Categories T** (drawer over Cash flows)

- A "Categories" drawer (eyebrow "Cash flows", a plain rule) listing every
  category in order. Each row: up / down buttons (disabled at the ends),
  the category's color swatch (blue for a category holding only income, a
  neutral swatch for an empty one), its name in an input, a meta line ("4
  flows · $3,376.67/mo", "1 flow · income $11,080.36/mo", "No flows yet", in
  the page's period), and a delete button.
- **Saves right away:** a rename saves on Enter or when its field loses
  focus; a move saves on click. Each comes back to the drawer, with a short
  status ("Moved Food up") in the footer beside **Done**, where it does not
  shift the list.
- **Delete** confirms in the row (`?confirm={id}`, so no JS is needed):
  "Delete Transport? 2 flows. They move to Uncategorized; nothing else is
  deleted." with Keep and **Delete category**.
- **Add:** a "New category name" field and **+ Add** at the bottom; the new
  category goes last and focus returns to the field for the next one.
- A new category has no card on the page until it has an expense.

### Account form: board **Account form Q** (drawer over Accounts)

Chosen over a stacked page and a split layout. Built.

- **How it opens:** the form's own routes (`.../accounts/new`,
  `.../accounts/{id}/edit`, and a save's 400 re-render) render the Accounts
  page with the drawer open. The links on Accounts stay ordinary links, so
  no JS opens it. The page behind is `inert` (focus and screen readers stay
  in the drawer), sits under a `--scrim`, and stops scrolling. Close, Cancel
  and Escape go back to `.../accounts`. Clicking the scrim does nothing, so a
  stray click can't throw away typing.
- **Staged balances survive:** the page underneath is the real Accounts page,
  script included, so balance edits staged in `sessionStorage` show (dimmed)
  under the drawer and are still there after it closes.
- **Drawer:** right side, at most 500px, full width on phones. Header: a
  small "Edit liability" / "New account" eyebrow, the account's name (or
  "New asset"), a 2px bottom rule in the type's color, and a round 44px close
  button. The body scrolls; the footer (Cancel, Save) stays pinned.
- **Body:** Name; Type as two pills (new accounts only; it recolors the
  header live); Category; "Computed from other accounts", which shows Rate (%)
  and Cost basis ($) side by side, the Inputs as checkable pills (checked =
  `--asset-tint` fill and `--asset` border; under Assets / Liabilities
  subheadings when both kinds exist), and the computed-value line
  ("15% × ($179,265 − $82,387)" → "$14,531.74"). The line uses the inputs'
  amounts on the latest snapshot and rounds as a save would; the server renders
  it and the drawer's script recomputes it as the fields change.
- **History:** a collapsed `<details>`, "History (12 snapshots)", with date and
  amount, newest first. The old change column is gone.
- **Retire:** the warning (a non-zero last value) with an outline danger
  **Retire anyway**; plain **Retire** when there is nothing to warn about; a
  blocker (an input to an active computed account) shows only the reason,
  with no button; a retired account shows when it was retired and
  **Unretire**.
- **Errors:** a validation error re-renders the drawer (400) with the user's
  input and the message at the top of the drawer, not behind the scrim.
- **Viewers** see the same drawer as editors, as they saw the old form; its
  writes are refused (403). The new-account drawer is editor-only, as before.

### Workspace settings: board **Settings V**

Chosen over a single stacked column. Reached from the header's gear button,
for every member.

- **Head:** "{Workspace} settings" and "You're an owner of this workspace."
  (your role, with its article).
- **Two columns** (5 : 7; one column below 860px):
  - **Left:** a **General** card (Name and Save; the time zone was removed
    in #55), then an outlined card with **Leave {name}** and **Delete
    {name}**. Leave explains whether you can ("Another owner stays, so you
    can leave"; the only owner gets "You're its only owner, so you can't
    leave…" and no button). Delete is a danger outline: "Removes it for all
    N members. Its data is kept and can be restored by an admin." (it is a
    soft delete).
  - **Right:** one **People** card: "N members · M invited"; an invite form
    (email, role select defaulting to Editor, **Invite**); then members
    (initials avatar, name and "(you)", email, a role select, × to remove;
    your own × means Leave) and pending invites in the same list (dashed
    avatar, the email as the name, an **Invited** tag, "Sent by you Oct 20
    · expires Nov 3", the role as text, × to revoke). An invite whose sender
    is no longer an owner says "lapsed: X is no longer an owner" instead of
    the expiry. Footnote: no email is sent, tell them yourself, they see it
    when they log in with that address; invites expire after 14 days; one
    line on what each role can do.
- **Role select:** submits on change (a small script); a Save button beside
  it is the no-JS fallback and is hidden by the script.
- **Confirms** are inline, via `?confirm=`: removing a member, revoking an
  invite, leaving, deleting. Each replaces its row or section with the
  question, **Keep** and a solid danger button.
- **Editors and viewers** get the same page read-only: no General card, no
  Delete, no invite form, roles as text, and no pending invites (the API
  lists invites to owners only). They keep Leave, in the left card and as
  the × on their own row, and the footnote says only owners invite or change
  roles. This mirrors the API's roles exactly; nothing new is exposed.
- **After** leaving or deleting, redirect to `/` (your oldest remaining
  workspace, or the welcome page). Every other write comes back to settings
  with a flash; a refusal (a blank name, a bad or duplicate invite, demoting
  or removing the last owner) re-renders it with a 400, the service's
  message beside the control, and the user's input kept.

### Welcome: board **Welcome W**

Where a logged-in user with no live workspace lands, and where "New
workspace" in the user menu leads for everyone.

- **Header:** the wordmark and the user menu only (no nav, picker or gear).
- **Head:** "Welcome, {first name}" (the email's local part with no name);
  "New workspace" for someone who already has one. Then "A workspace holds
  a set of accounts and cash flows that you track, alone or with others."
- **Invites for you:** each pending invite you could accept now: the
  workspace's name, "{inviter} invited you as an editor · expires Nov 3",
  **Decline** and **Join**. Join goes into that workspace's dashboard with a
  flash; Decline comes back here. Lapsed invites are left out. With no
  invites, this card and the "or" divider are hidden.
- **Start your own workspace:** Name and **Create workspace** (an outline
  button when there are invites, the primary one when there are none);
  creating goes into the new workspace.
- The mockup's footnote about a strip on the dashboard is a note for the
  canvas, not page text; the strip itself is board Z.

### Login: board **X** (built)

- **Logged out** (`/login`): a centered card, no shell. The wordmark
  (`APP_NAME`), "What you own, what you owe.", a one-line pitch, **Log in**,
  and "You'll sign in with your {identity host} account and come straight
  back." The host comes from identity's discovery document; if identity is
  unreachable the footnote drops it.
- **Email not allowed** (the callback, **403**): "This account isn't on the
  list yet", the email, "Ask the person who invited you to check the
  address, or log in with a different account.", an "Access is invite-only
  for now." note on `--danger-tint`, and **Log in with a different
  account**.
- **Email not verified** (403, same page): "Verify your email first", the
  email, open the verification link and log in again; **Log in again** and
  **Log in with a different account**.
- **Switching accounts** (`/auth/switch`): RP-initiated logout at identity
  (its `end_session_endpoint`), returning to our callback, which starts a
  fresh login. Logging out only here would sign straight back in as the
  same account, since identity keeps its own session.
- **Log out** (`/logout`): the same trip, but the callback sends it on to
  `/login` rather than into a login, so logging out reads as logged out
  and the next Log in asks identity which account. Both trips return to
  our callback because it is the only redirect URI identity has
  registered for us, and identity accepts a `post_logout_redirect_uri`
  only on an exact match; a value in our signed session, read once and
  only ever `/auth/start` or `/login`, says which trip it was. With no
  `end_session_endpoint`, or identity unreachable, both clear our session
  and go to `/login`.
- `login.html` extends `base.html` with the `shell_header` block emptied.

### Empty states: board **Y** (built)

- **New workspace dashboard:** a top card with the eyebrow "{Workspace} is
  new", "Let's get your first net worth on the board.", and three numbered
  steps (add your accounts; enter today's balances; come back now and then);
  beside it a placeholder chart (dashed line and a dot, `aria-hidden`).
  Below, empty Assets and Liabilities cards with **+ Add an asset** / **+ Add
  a liability**.
- **Accounts but no snapshot yet:** step 1 shows done ("Done: 3 accounts
  added."), and step 2 carries the button, **Enter balances**, to Accounts.
  The cards list the accounts with "—" for amounts; an empty type keeps its
  add button. The first snapshot ends the onboarding.
- **Viewers** get no buttons, and a line under the steps: "An editor hasn't
  added any accounts yet." (or "…entered any balances yet.").
- **Accounts and Cash flows, empty:** one card saying what goes there, and
  one button for editors (**+ Add an account**; **+ Add income**, since the
  drawer can switch it to an expense), or the viewer's line instead.

### Invite strip and flashes: board **Z** (built)

- **Strip:** on every page with the shell, one per invite the viewer could
  accept now (lapsed ones left out), newest first, above the page's
  content: a mail icon in an `--asset-tint` circle, "**{inviter}** invited
  you to **{workspace}** as an editor.", "Expires Nov 3" (viewer's zone),
  **Decline** (outline) and **Join {workspace}** (primary), with a 4px
  `--primary` inset bar on the left. Join posts to `/invites/{id}/accept`
  and goes into that workspace with a flash. Decline posts to
  `/invites/{id}/decline` with `next`, the page it was on (a refused POST's
  re-render sends its page's GET path), and returns there with a flash;
  `next` must be a path on this site (no `//`, backslash, scheme or
  control characters), else Decline goes to `/welcome`.
- **Not shown** on `/welcome` (it lists invites itself), on login (no
  shell), or under an open drawer (the page is inert).
- **Data:** one query per page (`acceptable_invites`, which joins the
  sender's ownership and name), in `shell_context`.
- **Flashes:** one at a time, under the strips. Success is `--asset-tint`
  with an `--asset` check (`role="status"`); errors are `--danger-tint`
  with `--danger` text and an alert icon (`role="alert"`). 14px radius, and
  a × that a few lines of script remove (without JS the flash stays until
  the next page). Under a drawer, the drawer shows the flash. The page's
  `.error` (a load failure, the Accounts save error) takes the error look.
- **Texts** say what happened: "Saved today's snapshot: 23 accounts, net
  worth $357,918.", "Added Rent: $1,850.00 a month.", "Added Schwab to
  assets."

## Decisions made

1. **The workspace is in the URL** (`/workspaces/{workspace_id}/…`), not a cookie.
   See "Workspace in the URL".
2. **Dark mode ships at launch**, designed alongside light. See "Light and
   dark".
3. **The account form is a drawer over Accounts** (board Q), rendered by the
   form's own routes, not opened by JS. See "Account form".
4. **Cash flows are edited in drawers over Cash flows** (boards R and T),
   built the same way. The drawers are editor-only, since they exist only to
   write; viewers get the page without the controls.
5. **Workspace settings is one page for every member** (board V): owners
   get every control, editors and viewers a read-only view plus Leave.
6. **A user with no workspace lands on the welcome page** (board W) rather
   than a 403; it is also where anyone starts a new workspace.

## Build plan

1. **Shell first** (blocks the rest; small): light and dark tokens as CSS
   custom properties, fonts, the header, nav, the workspace picker and the
   `/workspaces/{workspace_id}` routes with their access checks and redirects, the
   user menu, and the shared components above. Jinja macros for card, group
   and row.
2. **Then in parallel:**
   - **Dashboard:** new layout, the combined Plotly figure, the 30-day
     change, the category totals.
   - **Accounts:** restyle, the edited state with "was $X", and the sticky
     save bar. The save logic is unchanged.
   - **Cash flows:** new route and template, per-category totals, the
     period toggle.
   - **Design:** the "Still to design" screens.
3. **Tests:** every new page route joins the existing sweeps automatically
   (login, allowlist, isolation, roles). The sweeps read the OpenAPI schema,
   so routes must not set `include_in_schema=False`. Add page tests for:
   - the dashboard's 30-day change and category totals
   - per-category cash flow totals adding up to `totals()`
   - the workspace in the URL refusing non-members with 404
   - bare paths redirecting to the oldest live workspace

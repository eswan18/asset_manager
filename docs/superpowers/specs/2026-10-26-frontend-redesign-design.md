# Frontend Redesign

**Date:** 2026-10-26
**Status:** The three main pages (Dashboard, Accounts, Cash flows) are
approved as mockups. The smaller screens are still to be designed. The
open decisions listed below need answers before building starts.

**Mockups:** [Design canvas](https://claude.ai/artifact/BMRjmDM7b239Ro2SbBtvsR)
(private; share it from its Share menu). The chosen boards are **H**
(dashboard), **Accounts I** and **Cash flows N**. The other boards are the
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

### Tokens

| Token | Value | Use |
|---|---|---|
| `--bg` | `#F2F3F5` | Page background |
| `--surface` | `#FFFFFF` | Cards |
| `--ink` | `#15171A` | Text, active nav pill, net worth line |
| `--muted` | `#4A505A` | Secondary text (passes 4.5:1 on both backgrounds) |
| `--rule` | `#F0F1F3` | Row dividers |
| `--rule-strong` | `#DADDE2` | Input borders, axes |
| `--asset` | `#2457C5` | Assets, primary buttons, focus/edited state |
| `--asset-2` | `#8FB0EE` | Second asset category |
| `--asset-tint` | `#EEF3FC` | Edited input background |
| `--liability` | `#B4530F` | Liabilities, expenses |
| `--liability-2..4` | `#D9772E`, `#E9A066`, `#F3C79E` | More expense / liability categories |
| `--leftover` | `#DCE6F8` | "Left over" slice on Cash flows |
| `--estimate-bg` / `--estimate-fg` | `#FFF4E5` / `#8A4B0C` | `≈` estimate tag |
| `--danger` | `#B42318` | Delete |

Categories get their colors in display order, from the asset ramp or the
liability ramp. Assets are always blue and liabilities and expenses always
orange, and two colors that must be told apart also differ in lightness.

### Type

- **Space Grotesk** (500–700) for headings, the wordmark and the large figures.
- **Inter** (400–600) for everything else.
- Every number uses `font-variant-numeric: tabular-nums`.
- Scale: hero figure 64px, card titles 20px, body 15px, labels 13px,
  footnotes 12px.

### Shape and spacing

- Cards are white with a 20px radius and 28–32px padding, with 16px between
  cards. The content column is at most 1160px wide.
- Buttons, nav and toggles are pills (radius 999px). Inputs have a 10px
  radius.
- Every touch target is at least 44px. Inputs are at least 40px tall, inside
  rows at least 52px tall.

### Light only, for now

The current app follows the system's dark/light setting. The redesign ships
light only. Every color is a token, so a dark theme can come later. **Open
decision 2** asks whether to keep dark mode at launch.

## Shell (every page)

- **Header:** wordmark on the left, pill nav in the middle (Dashboard /
  Accounts / Cash flows; the active one is ink-filled), workspace picker on
  the right (`<select>` with a visible "Workspace" label). A user menu
  (logout) still needs a home; a small avatar button after the picker is the
  likely spot.
- **Workspace picker:** pages currently act in the user's oldest membership
  (`PageViewer` / `PageEditor`). The picker needs a real mechanism; see
  **Open decision 1**.
- **Narrow screens:** the header wraps, and any two-column card grid
  (`repeat(auto-fit, minmax(min(100%, 420px), 1fr))`) drops to one column.
  Wide grids scroll inside their own box, never the page.

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
| Sticky save bar | Ink bar stuck to the bottom: unsaved count, live net worth and change, Discard, Save snapshot |

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
- Theme the figure from the tokens. The current re-theming JS goes away
  if the redesign is light only.

### Accounts: board **Accounts I**

- **Page head:** title, then "Saving writes today's snapshot, <date>. Last
  saved <date>." (in the workspace's time zone), then the **Show retired (n)**
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
- Expenses above income: the bar is 100% expenses, with an overflow note
  ("Expenses exceed income by $X"). This still needs a mockup.

**Editing:**
- Not designed yet (see "Still to design").
- Cash flows **M**'s inline form is the reference: name, amount, every N +
  unit, category, income/expense, estimate checkbox, note, a live
  "= $X a month", and Delete / Cancel / Save.

## Still to design

These can be designed on the canvas while the three pages above are built:

1. **Account form:** new / edit, type, category, the computed toggle with
   rate, basis and inputs, retire and unretire with warnings and blockers,
   and history.
2. **Cash flow form:** inline (M) or a separate page or modal, plus
   category management (rename, reorder, delete).
3. **Workspace settings:** name, time zone, members and roles, pending
   invites, leave and delete. Also **My invites** (accept / decline).
4. **Login**, **empty states** (a new workspace, no snapshots, no cash
   flows), and error and flash messages.
5. **Expenses above income** on Cash flows.

## Open decisions

1. **How a page knows its workspace.** Recommended: put it in the URL,
   `/w/{workspace_id}/`, `/w/{id}/accounts`, `/w/{id}/cash-flows`. This
   matches the API, links work when shared, there is no hidden state, and
   each page route can use the API's 404/403 access checks. `/` redirects to
   the last-used or oldest workspace. The alternative is a cookie holding the
   current workspace.
2. **Dark mode at launch:** drop it for now (recommended), or carry the
   tokens over to dark before launch.

## Build plan

1. **Shell first** (blocks the rest; small): tokens as CSS custom
   properties, fonts, the header, nav, workspace picker (decision 1), the
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

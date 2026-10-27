# Mobile

**Date:** 2026-10-26
**Status:** First pass, planned and built without mockups (Ethan reviews the
result rather than boards). The desktop layout stays exactly as built from the
frontend redesign; everything here applies at phone width only.

## Goal

Every page and drawer works one-handed on a phone: nothing scrolls sideways,
every control is big enough to hit with a thumb, typing never makes iOS zoom
the page, and the main actions (update balances, add a cash flow, switch
pages) are within reach.

## Where things stood (audit, 390px iPhone 13 emulation)

- The header wrapped to three rows and still ran 37px past the right edge on
  every page in a workspace, which made the whole page wider than the screen.
  The account menu was off screen, and the settings gear covered it.
- Because of that overflow, every drawer was cut off on the right (its close
  button and the ends of its fields).
- Text fields are 15px, so iOS zooms in on every focus.
- Many controls are under 44px: nav pills and the picker (40px), range and
  period toggles (36px), the basis input on computed accounts (28px), role
  selects, checkboxes, account-name links (23px tall).
- The dashboard chart squeezes lines and category columns into ~300px.

## Rules (every page)

1. **One breakpoint: `@media (max-width: 600px)`** is "phone". The codebase
   already used 600px; other widths (480, 520, 860) are folded into it where a
   page is touched. Between 600px and desktop the desktop layout must still
   not scroll sideways (checked at 768px).
2. **No sideways scrolling** at 320px and 390px.
3. **Tap targets at least 44×44 CSS px** (Apple HIG). A checkbox or radio
   counts by its label. Links inside running text are exempt.
4. **Text fields, selects and textareas at least 16px** on phones (iOS zooms
   on focus below that). Numeric fields keep `inputmode="decimal"`.
5. **Tokens only** (no hex in templates), light and dark, as before.
6. **Hover-only styling** goes under `@media (hover: hover)` where it would
   otherwise stick after a tap. Nothing may be reachable only by hover.
7. **Safe areas:** the viewport has `viewport-fit=cover`; anything fixed to
   the bottom pads by `env(safe-area-inset-bottom)`.
8. **No new JS framework.** Phone behavior is CSS first; a page script may
   check `matchMedia('(max-width: 600px)')` (the chart does).

Layout tokens in `base.html`'s `:root`: `--gutter` (24px, 16px on phones) is
the page's side padding; `--tabbar-h` is the height of the bottom tab bar on
phones and `0px` elsewhere. **Anything fixed to the bottom of the screen sits
at `bottom: var(--tabbar-h)`** (the Accounts save bar).

## Shell (base.html)

- **Top bar (phones).** One row: the workspace switcher on the left (the
  native select, styled as the page title: display font, 17px, semibold,
  ellipsis when long, with a chevron; its "Workspace" label is visually
  hidden but still labels it), then the settings gear and the avatar (44px
  each) on the right. The wordmark is hidden on phones in a workspace, since
  the workspace name is the title; on `/welcome` (no workspace) the wordmark
  and avatar stay. The top bar scrolls away with the page.
- **Bottom tab bar (phones).** The existing `<nav class="main-nav">` (same
  markup, one landmark) restyled with CSS into a bar fixed to the bottom: three
  equal tabs, each a 24px stroke icon over a 12px label, `--surface`
  background, a `--rule-strong` hairline on top, `--ink` and 600 weight for
  the current tab (`aria-current="page"`), `--muted` for the others. Height
  56px plus the bottom safe area; that sum is `--tabbar-h`. The icons are
  inline SVG in the markup and hidden on desktop. Under a drawer the bar is
  covered (the drawer is full screen).
- **Account menu (phones).** The panel opens as a full-width card under the
  top bar (left and right at the gutter), its buttons 44px tall.
- `main` pads its bottom by `--tabbar-h` so the last card clears the bar.
- The tab bar **stays put while a field has focus**. (The first build hid it
  then, to rest the save bar on the keyboard. But the tap that blurs the
  field brought the bar back and moved the save bar under the finger, so
  Discard and Save missed; and the keyboard covers fixed bars on iOS and
  Android anyway.)
- **Invite strip and flash (phones).** The strip's text sits above its
  buttons, which share the row equally. The flash's × is a 44px target.
- **Shared controls on phones:** `.btn` at least 44px tall; `.toggle`
  segments 44px tall; all fields 16px.
- **Drawers (phones)** become full-screen sheets: full width, `100dvh` tall
  (so iOS's toolbars do not hide the footer), sliding up instead of in from
  the right. The head stays at the top, the body scrolls, the footer stays at
  the bottom with the safe area below it, and its buttons share the row
  equally. The close button is 44px.

## Dashboard

- The net worth card: the "Update balances" button spans the card.
- Range toggle: 44px segments.
- **Chart on phones:** lines only, full width, 240px tall; the category
  columns move out of the figure into two thin stacked bars under it (Assets,
  Liabilities), each segment a category in the same token colors as the
  columns, above the existing category legend, which keeps the amounts. The
  page script re-lays the figure when the phone media query changes (as it
  already does for the color scheme). The chart must not trap touch: no drag
  to zoom (`dragmode: false`, fixed ranges), so a swipe over it scrolls the
  page; a tap still shows the hover label.
- The account cards: rows at least 44px.
- *As built:* the range toggle also spans the card (three equal segments).
  Each bar sits directly above its own part of the key (Assets bar, Assets
  key, Liabilities bar, Liabilities key), so the key's group titles are
  hidden visually on phones (the bar's title stands for them; screen readers
  still get them, the bars being `aria-hidden`). Both bars share one scale,
  as the columns do. The column traces and their axis are removed from the
  phone figure, not hidden, since an empty subplot still catches taps.

## Accounts

- Rows keep name left and amount field right. Fields 16px, `inputmode`
  decimal, at least 44px tall, including the cost basis field on computed
  accounts. The account name link is a 44px-tall target.
- "Show retired" is a 44px label.
- The card head (title, + Add, total) stays on one line at 320px.
- **Save bar:** fixed at `bottom: var(--tabbar-h)` with the bottom safe area,
  full width less the gutters. Two lines: the count and the net worth on the
  first, Discard and Save snapshot sharing the second.
- The account drawer: field pairs stay two columns down to 320px; the formula
  input chips wrap, each a 44px label; the computed-value line wraps instead
  of clipping.

## Cash flows

- The headline card: the period toggle spans the card (three equal
  segments, 44px); "Manage categories" and "+ Add cash flow" share a row.
- The "Where income goes" bar and its legend fit; legend rows wrap cleanly.
- Flow rows are whole-row links for editors, at least 44px tall; the
  card "+ Add" is 44px.
- **Cash flow drawer:** the amount / every / unit row fits at 320px (the
  amount takes the remaining width); the rates strip's three cells stay in
  one row; the estimate check is a 44px label.
- **Categories drawer:** each row (move arrows, swatch, name field, delete)
  fits at 320px with 44px targets; the delete confirm's buttons share a row;
  the add row's field and button fit.

## Settings, welcome, login

- **Settings:** one column on phones (it is two from 860px). People rows: the
  avatar, name and email, then the role select (44px) and the × (44px)
  together under them. The invite form stacks: email full width, then role
  and Invite sharing a row. Leave and Delete, and the in-page confirms, keep
  their buttons at 44px and share rows.
- **Welcome and login:** fields 16px, buttons 44px, nothing sideways.

## Testing

- `open_page(path, phone=390)` (tests/browser/conftest.py) opens a page as a
  phone: touch, a mobile viewport of that width, 2x pixels.
- `tests/browser/mobile.py` has `assert_fits_phone(page)`, which checks rules
  2-4 (no sideways scroll, 44px targets, 16px fields), and `PHONE_WIDTHS`
  (320, 390). Every page and drawer is checked at both widths, in the
  states that change its layout (staged edits, confirms, a computed account,
  expenses above income, empty), by the test file for its area:
  `test_mobile_shell.py`, `test_mobile_dashboard.py`,
  `test_mobile_accounts.py`, `test_mobile_cash_flows.py`,
  `test_mobile_settings.py`.
- Behavior tests for what phones do differently: the tab bar shows and
  marks the current page, the account menu opens on screen, the chart drops
  its columns and re-lays when the width changes, the save bar sits above the
  tab bar, the tab bar stays put while a field is focused.
- The desktop browser tests keep passing unchanged.

## Workstreams

Built in parallel, one PR each, all starting from the same base commit (this
spec, the test harness, and a stopgap that keeps the old header from
overflowing). Only the shell touches `base.html` and `_components.html`;
other pages adjust shared pieces from their own `{% block styles %}`.

| Stream | Owns |
|---|---|
| Shell | `base.html` (top bar, tab bar, menu, strip, flash, shared controls, drawer frame), `_components.html` |
| Dashboard | `dashboard.html`, `charts.py`, `dashboard.py` |
| Accounts | `accounts.html`, `account_form.html`, `accounts_routes.py` |
| Cash flows | `cash_flows.html`, `cash_flow_form.html`, `cash_flow_categories.html`, `cash_flows_routes.py` |
| Settings | `settings.html`, `settings_routes.py`, `welcome.html`, `login.html` |

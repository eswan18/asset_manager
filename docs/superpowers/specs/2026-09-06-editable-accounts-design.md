# Editable Accounts with Formula Liabilities

**Date:** 2026-09-06
**Status:** Approved design, awaiting implementation plan

## Goal

Replace the Google Sheet as the place where values are entered. The Accounts tab
becomes editable: the user types current amounts, formula-driven liabilities
recompute live, and an explicit Save writes a complete snapshot for today.
Accounts become first-class entities that can be added and retired without
breaking history.

## Non-goals (this iteration)

- Time-driven values (condo appreciation, mortgage amortization). Designed for,
  not built. See "Future formula kinds".
- Floor-at-zero on formulas. Negative results are allowed; across accounts this
  is correct netting (a loss in one taxable account offsets a gain in another).
- Precision (+/-) and Accessible/liquidity columns from the sheet. Dropped.
- Removing the Sheets `fetch` command. It keeps working through the cutover and
  is deleted in a later PR.
- Picking a snapshot date. Save always writes today.
- Merging two accounts whose sheet descriptions differed over time.

## Data model

### Schema

```sql
CREATE TABLE accounts (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    type        VARCHAR(10) NOT NULL CHECK (type IN ('asset', 'liability')),
    formula     JSONB,                      -- NULL means a plain account
    retired_at  DATE,                       -- NULL means active
    created_at  TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (type, name)
);

CREATE TABLE formula_inputs (
    account_id  INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    input_id    INTEGER NOT NULL REFERENCES accounts(id),
    PRIMARY KEY (account_id, input_id),
    CHECK (account_id <> input_id)
);
CREATE INDEX idx_formula_inputs_input ON formula_inputs(input_id);

-- snapshots gains account_id and loses type + description
-- new unique index: (date, account_id); new index: (account_id, date)
```

Identity is the integer id. Names are labels and can change without touching
history or formulas.

### Migration (`db/migrations/<timestamp>_create_accounts.sql`)

Up, in one transaction (dbmate's default):

1. Create `accounts` and `formula_inputs`.
2. Backfill one account per distinct `(type, description)` in `snapshots`,
   ordered by first appearance (`ORDER BY MIN(date), MIN(id)`) so ids roughly
   follow the sheet's row order.
3. Add `snapshots.account_id`, populate it by joining on `(type, description)`,
   set `NOT NULL`.
4. Drop `idx_snapshots_unique` and `idx_snapshots_type_date`; drop `type` and
   `description`; create `idx_snapshots_unique (date, account_id)` and
   `idx_snapshots_account_date (account_id, date)`.

Down reverses it: re-add `type` and `description`, fill them from `accounts`,
set `NOT NULL` and the type check, restore the old indexes, drop `account_id`,
drop `formula_inputs`, drop `accounts`. Formulas and retirement flags are lost
on down; snapshot amounts are not.

Nothing is auto-retired and no formulas are auto-created. The user configures
those in the UI after migrating.

### Formula document

`accounts.formula` holds a JSON object validated by a Pydantic discriminated
union on `kind`. One kind exists today:

```json
{"kind": "proportional", "rate": "0.15", "cost_basis": "70634.00"}
```

- `rate`: Decimal fraction, `>= 0`, at most 6 decimal places. The UI shows
  and accepts a percent and converts.
- `cost_basis`: Decimal, default `0`. Editable inline on the accounts page.
- Decimals are serialized as strings.

Value: `rate × (Σ inputs − cost_basis)`, quantized to cents with
`ROUND_HALF_UP`.

Input accounts are the rows in `formula_inputs` for this account. They are
relational rather than inside the JSON so the database enforces referential
integrity and "what depends on X" is a plain query.

### Rules

- **Plain vs computed.** An account is computed iff `formula` is not null.
  Either type may be computed. All of today's computed accounts are
  liabilities, but nothing depends on that.
- **A proportional formula needs a rate and at least one input.**
- **Inputs must be plain, active accounts**, and never the account itself.
  Because inputs are plain, evaluation is a single pass with no dependency
  graph.
- **A current input cannot be made computed.** Editing an account to add a
  formula is rejected while any other account lists it as an input.
- **Type is fixed after creation.** Changing it would reclassify history.
- **Name is unique within a type**, matching the old unique index semantics and
  guaranteeing the backfill cannot collide.

### Pydantic models (`models.py`)

```python
class ProportionalFormula(BaseModel):
    kind: Literal["proportional"] = "proportional"
    rate: Decimal
    cost_basis: Decimal = Decimal("0")

Formula = ProportionalFormula          # becomes a discriminated Union when a
                                       # second kind exists

class Account(BaseModel):
    id: int | None = None
    name: str
    type: RecordType
    formula: Formula | None = None
    input_ids: list[int] = []
    retired_at: date | None = None
    created_at: datetime | None = None

    is_computed -> formula is not None
    is_active   -> retired_at is None

class Record(BaseModel):               # existing, plus account_id
    id, date, account_id, type, description, amount, created_at
```

`Record.type` and `Record.description` are populated by joining `accounts`, so
`report.py`, the dashboard charts, and the CLI report do not change.

## Evaluation (`formulas.py`)

Pure module, no database access.

```python
def compute_snapshot(
    accounts: list[Account],        # active accounts, plain and computed
    values: dict[int, Decimal],     # amount for every active plain account
    as_of: date,
) -> dict[int, Decimal]:            # amount for every active account
```

- Plain accounts pass their value through, quantized to cents.
- Computed accounts evaluate their formula over `values` at their `input_ids`.
- A missing value for any plain account, or any input, raises
  `MissingValueError` naming the account. Never a silent zero.
- `as_of` is unused by the proportional kind. It exists so a time-driven kind
  can be added without changing the signature.

## Account service (`accounts.py`)

Owns the rules above and the save transaction. Raises `AccountError` (a
`ValueError`) with user-facing messages. The repository stays a thin SQL layer.

- `create_account(conn, name, type, formula, input_ids) -> Account`
- `update_account(conn, id, name, formula, input_ids) -> Account`
- `retire_account(conn, id, on: date)`
- `unretire_account(conn, id)`
- `save_snapshot(conn, values, cost_bases, as_of) -> int`

### Retire

Allowed only when both hold:

1. The account's own latest snapshot row (max date for that account, not the
   global latest date) has amount zero, or the account has no rows at all.
2. No active computed account lists it as an input. The error names the
   dependents.

The flow is therefore: set to zero, Save, Retire. It applies to computed
accounts too. To retire a cap-gains liability whose asset was emptied: set the
asset to zero and the basis to zero, Save (the liability evaluates to zero),
retire the liability, then retire the asset.

Sets `retired_at` to the given date. Unretire clears it; the account reappears
with a blank amount for the next snapshot.

### Save snapshot

All in one transaction; any failure rolls back everything, including basis
updates.

1. Load active accounts.
2. `values` keys must be exactly the set of active plain account ids. Extra,
   missing, retired, or computed ids are errors naming the account.
3. `cost_bases` keys must be active computed accounts whose formula has a
   `cost_basis`. Update each account's formula document.
4. `compute_snapshot` for every active account.
5. Upsert `snapshots (date, account_id, amount)` on conflict
   `(date, account_id)` update amount.
6. Commit. Return the row count.

Retired accounts get no row; their series simply end. A second Save on the
same date replaces that date's rows. A row written earlier today for an account
retired later today is left in place.

## Web

### Auth changes (`web/auth.py`)

- A shared `require_user` dependency replaces the copy-pasted session check.
  HTML routes redirect to `/login`; the JSON route returns 401.
- Optional `ALLOWED_EMAILS` env var (comma-separated, compared
  case-insensitively). When set, `handle_callback` refuses any user whose
  email is not listed with a 403 page.
  When unset, behavior is unchanged: anyone identity authenticates may log in
  and, now, edit.
- No CSRF tokens. The session cookie is `SameSite=Lax` and `httponly`, which
  blocks cross-site form POSTs and cross-origin fetches.
- Flash messages ride in the existing Starlette `SessionMiddleware` session as
  `{"kind": "error" | "success", "text": ...}`. `base.html` pops and renders
  one per page load.

### Routes

| Route | Kind | Behavior |
|---|---|---|
| `GET /accounts` | page | Editable accounts page |
| `GET /accounts/new?type=asset\|liability` | page | Create form, type preset |
| `GET /accounts/{id}/edit` | page | Edit form |
| `POST /accounts` | form | Create, redirect to `/accounts` |
| `POST /accounts/{id}` | form | Update, redirect to `/accounts` |
| `POST /accounts/{id}/retire` | form | Redirect with flash |
| `POST /accounts/{id}/unretire` | form | Redirect with flash |
| `POST /snapshots` | JSON | Save |

Form validation failures re-render the form with the error and the submitted
values, status 400. Retire failures redirect to `/accounts` with the error as
a flash.

Chart-building code moves from `web/app.py` to `web/charts.py` so `app.py` is
routes only.

### `POST /snapshots`

Request:

```json
{
  "values":      {"3": "1531.32", "4": "2060.09"},
  "cost_bases":  {"18": "70634.00"}
}
```

Amounts are decimal strings; the client normalizes them before sending. The
server parses with `Decimal`, rejects NaN and infinity, quantizes to cents.

Responses:

- `200 {"date": "2026-09-06", "count": 21}`
- `400 {"error": "Missing value for Savings Account (PNC VW)"}`
- `401` when not logged in

### Accounts page (`accounts.html`)

Same dark theme and two-table layout as today, with these changes.

- **Header.** Latest snapshot date and a "Show retired (n)" toggle.
- **Prefill.** Amounts come from the latest snapshot date (the global most
  recent date). An account with no row on that date shows blank: a newly
  added or just-unretired account, or one that was dropped from the sheet
  before the last fetch. Every blank plain amount must be filled before Save.
- **Plain rows.** Name (links to the edit page) and a text input for the
  amount. Accepts `$`, commas, negatives, and parentheses for negatives;
  reformats on blur.
- **Computed rows.** Name with a formula badge; the formula spelled out on
  hover, e.g. "15% × (Charles Schwab Trading Account − basis)"; an inline
  editable cost basis; the amount read-only and always the live evaluation of
  the current inputs, shown as a dash while any input is blank.
- **Live recompute.** The page embeds the active accounts as JSON:
  `[{id, name, type, formula, input_ids, amount}]`. Any edit recomputes
  computed rows, both totals, and net worth, rounding to cents. This is for
  display; the server's evaluation is authoritative on Save.
- **Sticky footer.** Unsaved-change count, Save (primary), Discard. Save is
  always enabled so an unchanged day can be recorded. The client blocks Save
  and highlights the field if any plain amount is blank or unparseable.
- **Staged edits survive round trips.** Every edit is mirrored to
  `sessionStorage` keyed by account id and restored on load if that account is
  still active. Adding or editing an account reloads the page and keeps typed
  values. Cleared on successful Save or Discard.
- **Add** buttons in each table header link to the create form with the type
  preset. This fills the existing `.table-actions` placeholder.
- **Retired rows** are hidden until toggled, then shown muted with no input.
  Retire and Unretire are on the edit page only.
- **Save** posts the payload; on 200 it clears storage and reloads; on 400 it
  shows the error in a banner above the tables; on 401 it goes to `/login`.
- **Empty state** tells the user to add an asset rather than to run fetch.

### Account form (`account_form.html`)

One template for create and edit.

- Name.
- Type: radio on create, shown locked on edit.
- "Computed" checkbox revealing: rate as a percent, cost basis, and a checkbox
  list of eligible inputs (active plain accounts, grouped by type, excluding
  the account itself).
- Save button.
- On edit: a separate Retire or Unretire button (its own small form) and a
  note of the rule when retire is not possible.

### Dashboard

Breakdown lists under the summary cards exclude retired accounts so they do
not sit at $0 forever. Charts are unchanged; a retired account's line ends at
its last snapshot.

## Sheets fetch during cutover (`sheets.py`)

- Parsing is unchanged. Parsed rows carry `(type, description, amount)`.
- `fetch_and_save` resolves each row to an account by `(type, name)`, creating
  a plain account for any unknown description.
- Rows for retired accounts are skipped. If the sheet shows a non-zero amount
  for one, print a warning naming it.
- Formulas are not evaluated. The sheet's own computed cells are written as-is.
- Dry run marks rows that would create a new account.

## Testing

- **`tests/test_formulas.py`.** Unit tests for the proportional kind, plus a
  Hypothesis property: for any rate, basis, and inputs, the result equals the
  quantized `rate × (Σ − basis)`. A missing value raises.
- **`tests/test_repository.py`** (extended) and the service layer. Account
  create and update, unique name per type, input persistence, each retire rule
  (non-zero blocked, dependent blocked, allowed), an input cannot be made
  computed, snapshot save writes every active account and nothing for retired
  ones, same-day save replaces, a bad payload writes nothing.
- **`tests/test_migration.py`.** On a throwaway database in the same container:
  apply the first migration, insert legacy rows, apply the new one, assert
  accounts were backfilled in first-appearance order and every row is linked.
  Apply down and assert the old columns are back with their values. The test
  splits each migration file on the `-- migrate:up` / `-- migrate:down`
  markers and executes the SQL directly.
- **`tests/test_web.py`.** FastAPI `TestClient` with a session cookie signed by
  the app's own serializer. Redirect when logged out; accounts page renders
  rows and embeds the JSON; a full Save writes computed rows; a Save missing a
  value returns 400 and writes nothing; account creation; a blocked retire
  surfaces its flash. `get_settings.cache_clear()` per test so the container's
  `DATABASE_URL` wins over `.env.dev`.
- `conftest.py` truncates `snapshots`, `formula_inputs`, `accounts` with
  `RESTART IDENTITY CASCADE`.
- CI already installs dbmate and runs database tests. No change.

## Rollout

1. One PR. CI green, merge. Staging auto-deploys and serves 500s until the
   migration runs, so immediately:
   ```
   uv run dotenv -f .env.dev run dbmate up
   ```
2. On staging: configure both formulas, retire the zero-balance accounts,
   Save, check the dashboard.
3. Prod: create a Neon branch as a restore point. Migrate first, then promote,
   so a failed migration fails before dependent code ships:
   ```
   uv run dotenv -f .env.prod run dbmate up
   bif promote asset-manager
   ```
   Errors last for the pod rollout, about a minute.
4. Redo formula and retirement setup in prod. Nothing copies from staging.
5. Stop updating the sheet. A later PR removes `sheets.py`, the Google
   dependencies, `data/config.ini`, and the credentials handling.

## Files

New:

- `db/migrations/<timestamp>_create_accounts.sql`
- `src/asset_manager/formulas.py`
- `src/asset_manager/accounts.py`
- `src/asset_manager/web/charts.py`
- `src/asset_manager/web/templates/account_form.html`
- `tests/test_formulas.py`, `tests/test_migration.py`, `tests/test_web.py`

Changed:

- `src/asset_manager/models.py`, `repository.py`, `sheets.py`
- `src/asset_manager/web/app.py`, `web/auth.py`
- `web/templates/accounts.html`, `dashboard.html`, `base.html`
- `tests/conftest.py`, `tests/test_repository.py`
- `README.md`, `CLAUDE.md` (schema, commands, env vars, the retire flow)

## Future formula kinds

The design keeps these to one Pydantic class, one evaluator branch, one form
variant, and no migration.

- **Drift** for the condo, mortgage, or a car:
  `{"kind": "drift", "anchor_amount", "anchor_date", "annual_rate"}`, evaluated
  as `anchor × (1 + rate) ^ years(anchor_date → as_of)`. Uses the `as_of`
  argument that already exists. Would be a computed account with no inputs, so
  "at least one input" becomes a per-kind rule.
- **Floor at zero** as a flag on the proportional kind, for the primary
  residence exclusion or option spreads.
- **Expression** kind with a restricted evaluator, if a shape ever appears that
  the structured kinds cannot express.

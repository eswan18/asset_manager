# Editable Accounts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Accounts tab the place where values are entered: accounts become first-class rows, liabilities can be computed by a formula, accounts can be retired, and an explicit Save writes a complete snapshot for today.

**Architecture:** A new `accounts` table becomes the identity for every asset and liability; `snapshots` rows point at it by id. Formula evaluation is a pure module; account rules and the save transaction live in a small service layer over a thin SQL repository. The web layer stays server-rendered Jinja with one inline script on the accounts page for staged edits and live recompute, plus one JSON endpoint for Save.

**Tech Stack:** Python 3.13, FastAPI, Pydantic v2, psycopg 3, dbmate migrations, Jinja2, vanilla JS, pytest + testcontainers + Hypothesis, ruff, ty.

**Spec:** `docs/superpowers/specs/2026-09-06-editable-accounts-design.md`

## Global Constraints

- All commands run through `uv run ...` from the repo root.
- Database tests need Docker (testcontainers) and `dbmate` on PATH (`brew install dbmate`).
- `uv run ruff check src tests`, `uv run ruff format src tests`, and `uv run ty check src/asset_manager` must pass before every commit.
- Repository functions never commit. Service functions and CLI code commit.
- Money is `Decimal`, quantized to cents with `ROUND_HALF_UP`. Never `float` in Python code paths that persist values.
- Formula rate is stored as a fraction (`0.15`), shown to the user as a percent (`15`).
- Running `dbmate up` (which the test fixture does) rewrites `db/schema.sql`. Commit the regenerated file with the migration task.
- Commit messages end with:
  ```
  Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_019xmQz7xUC8sPrM8sudBnTJ
  ```

---

## File Structure

| File | Responsibility |
|---|---|
| `src/asset_manager/models.py` | Pydantic models: `RecordType`, `ProportionalFormula`, `Formula`, `Account`, `Record`, `DailySummary` |
| `src/asset_manager/formulas.py` | Pure evaluation: `compute_snapshot`, `quantize_cents`, `MissingValueError` |
| `src/asset_manager/repository.py` | Thin SQL: records (joined to accounts), accounts CRUD, inputs, dependents |
| `src/asset_manager/accounts.py` | Rules and transactions: create/update/retire/unretire, `save_snapshot`, `parse_amount` |
| `src/asset_manager/sheets.py` | Sheet parsing plus `save_rows` / `describe_rows` for the cutover |
| `src/asset_manager/cli.py` | Typer CLI; `fetch --dry-run` annotates rows |
| `src/asset_manager/web/rendering.py` | `templates`, `render`, `set_flash`, `pop_flash` |
| `src/asset_manager/web/auth.py` | OIDC plus `require_user`, `CurrentUser`, `LoginRequired`, `is_email_allowed` |
| `src/asset_manager/web/charts.py` | `build_chart_html(records, accounts)` moved out of `app.py` |
| `src/asset_manager/web/accounts_routes.py` | `/accounts*` pages, forms, and `POST /snapshots` |
| `src/asset_manager/web/app.py` | App wiring, dashboard, auth routes, health |
| `src/asset_manager/web/templates/accounts.html` | Editable accounts page with inline script |
| `src/asset_manager/web/templates/account_form.html` | Create/edit form with retire/unretire |
| `src/asset_manager/web/templates/base.html` | Adds flash rendering |
| `src/asset_manager/web/templates/dashboard.html` | Empty-state copy only |
| `db/migrations/20260906120000_create_accounts.sql` | Schema change and backfill |
| `tests/test_models.py`, `test_formulas.py`, `test_migration.py`, `test_accounts.py`, `test_web.py` | New suites |
| `tests/conftest.py`, `test_repository.py`, `test_sheets.py` | Updated |

---

### Task 1: Models

**Files:**
- Modify: `src/asset_manager/models.py`
- Create: `tests/test_models.py`

**Interfaces:**
- Produces: `ProportionalFormula(kind="proportional", rate: Decimal, cost_basis: Decimal = 0)`, `Formula` (alias), `Account(id, name, type, formula, input_ids, retired_at, created_at)` with `.is_computed` and `.is_active`, `Record` gains `account_id: int | None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_models.py`:

```python
"""Tests for the Pydantic models."""

from datetime import date
from decimal import Decimal

import pytest
from pydantic import ValidationError

from asset_manager.models import Account, ProportionalFormula, Record, RecordType


def test_proportional_formula_defaults_and_json_round_trip():
    formula = ProportionalFormula(rate=Decimal("0.15"))
    assert formula.kind == "proportional"
    assert formula.cost_basis == Decimal("0")
    dumped = formula.model_dump(mode="json")
    assert dumped == {"kind": "proportional", "rate": "0.15", "cost_basis": "0"}
    assert ProportionalFormula.model_validate(dumped) == formula


def test_proportional_formula_rejects_negative_rate():
    with pytest.raises(ValidationError):
        ProportionalFormula(rate=Decimal("-0.1"))


def test_account_parses_formula_document():
    account = Account.model_validate(
        {
            "id": 7,
            "name": "Cap Gains Tax",
            "type": "liability",
            "formula": {"kind": "proportional", "rate": "0.15", "cost_basis": "70634.00"},
            "input_ids": [3],
        }
    )
    assert account.is_computed
    assert account.is_active
    assert account.formula == ProportionalFormula(
        rate=Decimal("0.15"), cost_basis=Decimal("70634.00")
    )
    assert account.input_ids == [3]


def test_account_rejects_unknown_formula_kind():
    with pytest.raises(ValidationError):
        Account.model_validate({"name": "X", "type": "asset", "formula": {"kind": "drift"}})


def test_plain_account_defaults():
    account = Account(name="Savings", type=RecordType.ASSET)
    assert not account.is_computed
    assert account.input_ids == []
    assert account.is_active


def test_retired_account_is_not_active():
    account = Account(name="Old 401k", type=RecordType.ASSET, retired_at=date(2026, 9, 1))
    assert not account.is_active


def test_record_carries_account_id():
    record = Record(
        date=date(2026, 9, 6),
        account_id=3,
        type=RecordType.ASSET,
        description="Savings",
        amount=Decimal("10"),
    )
    assert record.account_id == 3
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_models.py -v --no-cov`
Expected: ImportError, `ProportionalFormula` and `Account` do not exist.

- [ ] **Step 3: Write the models**

Replace `src/asset_manager/models.py` with:

```python
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class RecordType(str, Enum):
    ASSET = "asset"
    LIABILITY = "liability"


class ProportionalFormula(BaseModel):
    """rate × (sum of inputs − cost_basis)."""

    kind: Literal["proportional"] = "proportional"
    rate: Decimal = Field(ge=0)
    cost_basis: Decimal = Decimal("0")


# When a second kind exists this becomes
# Annotated[ProportionalFormula | OtherFormula, Field(discriminator="kind")].
Formula = ProportionalFormula


class Account(BaseModel):
    id: int | None = None
    name: str
    type: RecordType
    formula: Formula | None = None
    input_ids: list[int] = []
    retired_at: date | None = None
    created_at: datetime | None = None

    @property
    def is_computed(self) -> bool:
        return self.formula is not None

    @property
    def is_active(self) -> bool:
        return self.retired_at is None


class Record(BaseModel):
    id: int | None = None
    date: date
    account_id: int | None = None
    type: RecordType
    description: str
    amount: Decimal
    created_at: datetime | None = None


class DailySummary(BaseModel):
    date: date
    type: RecordType
    total_amount: Decimal
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_models.py tests/test_report.py -v --no-cov`
Expected: all PASS (`test_report.py` still builds `Record` without `account_id`).

- [ ] **Step 5: Lint, typecheck, commit**

```bash
uv run ruff check src tests && uv run ruff format src tests && uv run ty check src/asset_manager
git add src/asset_manager/models.py tests/test_models.py
git commit -m "Add Account and ProportionalFormula models"
```

---

### Task 2: Formula evaluation

**Files:**
- Create: `src/asset_manager/formulas.py`
- Create: `tests/test_formulas.py`

**Interfaces:**
- Consumes: `Account`, `ProportionalFormula` from Task 1.
- Produces: `CENTS`, `quantize_cents(amount) -> Decimal`, `MissingValueError(account_name)` with `.account_name`, `compute_snapshot(accounts: list[Account], values: dict[int, Decimal], as_of: date) -> dict[int, Decimal]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_formulas.py`:

```python
"""Tests for formula evaluation."""

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from asset_manager.formulas import MissingValueError, compute_snapshot, quantize_cents
from asset_manager.models import Account, ProportionalFormula, RecordType

AS_OF = date(2026, 9, 6)


def _asset(id: int, name: str) -> Account:
    return Account(id=id, name=name, type=RecordType.ASSET)


def _computed(
    id: int, name: str, rate: Decimal, basis: Decimal, input_ids: list[int]
) -> Account:
    return Account(
        id=id,
        name=name,
        type=RecordType.LIABILITY,
        formula=ProportionalFormula(rate=rate, cost_basis=basis),
        input_ids=input_ids,
    )


def test_quantize_cents_rounds_half_up():
    assert quantize_cents(Decimal("10.005")) == Decimal("10.01")
    assert quantize_cents(Decimal("-17.436")) == Decimal("-17.44")


def test_plain_values_pass_through_quantized():
    result = compute_snapshot([_asset(1, "Savings")], {1: Decimal("10.005")}, AS_OF)
    assert result == {1: Decimal("10.01")}


def test_proportional_with_basis_matches_the_sheet():
    accounts = [
        _asset(1, "Schwab"),
        _computed(2, "Cap Gains Tax", Decimal("0.15"), Decimal("70634.00"), [1]),
    ]
    result = compute_snapshot(accounts, {1: Decimal("163202.77")}, AS_OF)
    assert result == {1: Decimal("163202.77"), 2: Decimal("13885.32")}


def test_proportional_sums_multiple_inputs():
    accounts = [
        _asset(1, "401k A"),
        _asset(2, "401k B"),
        _computed(3, "Deferred Tax", Decimal("0.32"), Decimal("0"), [1, 2]),
    ]
    result = compute_snapshot(accounts, {1: Decimal("100"), 2: Decimal("50")}, AS_OF)
    assert result[3] == Decimal("48.00")


def test_negative_result_is_allowed():
    accounts = [
        _asset(1, "Fidelity"),
        _computed(2, "Cap Gains Tax", Decimal("0.15"), Decimal("1472.00"), [1]),
    ]
    result = compute_snapshot(accounts, {1: Decimal("1355.76")}, AS_OF)
    assert result[2] == Decimal("-17.44")


def test_missing_plain_value_raises():
    with pytest.raises(MissingValueError, match="Savings") as info:
        compute_snapshot([_asset(1, "Savings")], {}, AS_OF)
    assert info.value.account_name == "Savings"


def test_missing_input_value_raises_naming_the_input():
    accounts = [
        _asset(1, "Schwab"),
        _computed(2, "Cap Gains Tax", Decimal("0.15"), Decimal("0"), [1]),
    ]
    with pytest.raises(MissingValueError, match="Schwab"):
        compute_snapshot(accounts, {}, AS_OF)


def test_extra_values_are_ignored():
    result = compute_snapshot([_asset(1, "Savings")], {1: Decimal("5"), 9: Decimal("1")}, AS_OF)
    assert result == {1: Decimal("5.00")}


amounts = st.decimals(min_value=Decimal("-1000000"), max_value=Decimal("1000000"), places=2)
rates = st.decimals(min_value=Decimal("0"), max_value=Decimal("1"), places=6)


@given(rate=rates, basis=amounts, inputs=st.lists(amounts, min_size=1, max_size=5))
def test_proportional_matches_definition(rate, basis, inputs):
    assets = [_asset(i + 1, f"A{i}") for i in range(len(inputs))]
    computed = _computed(99, "L", rate, basis, [i + 1 for i in range(len(inputs))])
    values = {i + 1: v for i, v in enumerate(inputs)}
    result = compute_snapshot(assets + [computed], values, AS_OF)
    expected = (rate * (sum(inputs) - basis)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    assert result[99] == expected
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_formulas.py -v --no-cov`
Expected: ImportError, `asset_manager.formulas` does not exist.

- [ ] **Step 3: Write the module**

Create `src/asset_manager/formulas.py`:

```python
"""Evaluate account formulas. Pure functions, no database access."""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from .models import Account, Formula, ProportionalFormula

CENTS = Decimal("0.01")


def quantize_cents(amount: Decimal) -> Decimal:
    return amount.quantize(CENTS, rounding=ROUND_HALF_UP)


class MissingValueError(ValueError):
    """A plain account that a snapshot needs has no value."""

    def __init__(self, account_name: str) -> None:
        self.account_name = account_name
        super().__init__(f"Missing value for {account_name}")


def compute_snapshot(
    accounts: list[Account],
    values: dict[int, Decimal],
    as_of: date,
) -> dict[int, Decimal]:
    """Return the amount for every account.

    Args:
        accounts: the active accounts, plain and computed.
        values: the amount for every active plain account, keyed by id.
        as_of: the snapshot date. Unused by the proportional kind; a
            time-driven kind would need it.

    Raises MissingValueError if a plain account or a formula input has no value.
    """
    by_id = {a.id: a for a in accounts if a.id is not None}
    result: dict[int, Decimal] = {}
    for account in accounts:
        if account.id is None:
            raise ValueError(f"Account {account.name!r} has no id")
        if account.formula is None:
            if account.id not in values:
                raise MissingValueError(account.name)
            result[account.id] = quantize_cents(values[account.id])
        else:
            result[account.id] = _evaluate(account, account.formula, values, by_id, as_of)
    return result


def _evaluate(
    account: Account,
    formula: Formula,
    values: dict[int, Decimal],
    by_id: dict[int, Account],
    as_of: date,
) -> Decimal:
    if isinstance(formula, ProportionalFormula):
        total = Decimal("0")
        for input_id in account.input_ids:
            if input_id not in values:
                name = by_id[input_id].name if input_id in by_id else f"account {input_id}"
                raise MissingValueError(name)
            total += values[input_id]
        return quantize_cents(formula.rate * (total - formula.cost_basis))
    raise TypeError(f"Unsupported formula kind: {formula.kind}")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_formulas.py -v --no-cov`
Expected: all PASS, including the Hypothesis property.

- [ ] **Step 5: Lint, typecheck, commit**

```bash
uv run ruff check src tests && uv run ruff format src tests && uv run ty check src/asset_manager
git add src/asset_manager/formulas.py tests/test_formulas.py
git commit -m "Add formula evaluation for computed accounts"
```

---

### Task 3: Migration and repository core

This task changes the schema, so the repository and its tests must move in the same commit to keep the suite green. `insert_records` survives temporarily, reimplemented on the new schema, so `sheets.py` and the CLI keep working until Task 6 replaces it.

**Files:**
- Create: `db/migrations/20260906120000_create_accounts.sql`
- Create: `tests/test_migration.py`
- Modify: `tests/conftest.py`
- Modify: `src/asset_manager/repository.py` (full rewrite)
- Modify: `tests/test_repository.py` (full rewrite)
- Regenerated: `db/schema.sql`

**Interfaces:**
- Consumes: models from Task 1.
- Produces (repository): `get_all_records`, `get_records_by_date_range`, `get_latest_snapshot_records`, `get_summary_by_date`, `upsert_amounts(conn, as_of, amounts: dict[int, Decimal]) -> int`, `get_accounts(conn, *, include_retired=True) -> list[Account]`, `get_account_by_name(conn, type, name) -> Account | None`, `insert_account(conn, account) -> Account`, temporary `insert_records(conn, records) -> int`.

- [ ] **Step 1: Write the migration**

Create `db/migrations/20260906120000_create_accounts.sql`:

```sql
-- migrate:up
CREATE TABLE accounts (
    id          SERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    type        VARCHAR(10) NOT NULL CHECK (type IN ('asset', 'liability')),
    formula     JSONB,
    retired_at  DATE,
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

-- One account per distinct (type, description), in order of first appearance.
INSERT INTO accounts (name, type)
SELECT description, type
FROM snapshots
GROUP BY type, description
ORDER BY MIN(date), MIN(id);

ALTER TABLE snapshots ADD COLUMN account_id INTEGER REFERENCES accounts(id);
UPDATE snapshots s
SET account_id = a.id
FROM accounts a
WHERE a.type = s.type AND a.name = s.description;
ALTER TABLE snapshots ALTER COLUMN account_id SET NOT NULL;

DROP INDEX idx_snapshots_unique;
DROP INDEX idx_snapshots_type_date;
ALTER TABLE snapshots DROP COLUMN type, DROP COLUMN description;
CREATE UNIQUE INDEX idx_snapshots_unique ON snapshots(date, account_id);
CREATE INDEX idx_snapshots_account_date ON snapshots(account_id, date);

-- migrate:down
ALTER TABLE snapshots ADD COLUMN type VARCHAR(10), ADD COLUMN description TEXT;
UPDATE snapshots s
SET type = a.type, description = a.name
FROM accounts a
WHERE a.id = s.account_id;
ALTER TABLE snapshots ALTER COLUMN type SET NOT NULL, ALTER COLUMN description SET NOT NULL;
ALTER TABLE snapshots ADD CONSTRAINT snapshots_type_check CHECK (type IN ('asset', 'liability'));

DROP INDEX idx_snapshots_unique;
DROP INDEX idx_snapshots_account_date;
ALTER TABLE snapshots DROP COLUMN account_id;
CREATE UNIQUE INDEX idx_snapshots_unique ON snapshots(date, type, description);
CREATE INDEX idx_snapshots_type_date ON snapshots(type, date);

DROP TABLE formula_inputs;
DROP TABLE accounts;
```

- [ ] **Step 2: Update conftest cleanup**

In `tests/conftest.py`, replace the teardown of `db_connection` (the lines after `yield conn`) with:

```python
    # Clean up: roll back anything left open, then truncate every table
    conn.rollback()
    with conn.cursor() as cur:
        cur.execute(
            "TRUNCATE TABLE snapshots, formula_inputs, accounts RESTART IDENTITY CASCADE"
        )
    conn.commit()
    conn.close()
```

- [ ] **Step 3: Write the migration test**

Create `tests/test_migration.py`:

```python
"""Apply the create_accounts migration to legacy rows and check the backfill."""

from datetime import date
from decimal import Decimal
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest

MIGRATIONS = sorted((Path(__file__).parent.parent / "db" / "migrations").glob("*.sql"))


def split_migration(path: Path) -> tuple[str, str]:
    text = path.read_text()
    up_marker, down_marker = "-- migrate:up", "-- migrate:down"
    up = text[text.index(up_marker) + len(up_marker) : text.index(down_marker)]
    down = text[text.index(down_marker) + len(down_marker) :]
    return up, down


@pytest.fixture
def fresh_db_url(db_url):
    """A throwaway database in the same container, with no migrations applied."""
    fresh = urlunsplit(urlsplit(db_url)._replace(path="/migration_test"))
    with psycopg.connect(db_url, autocommit=True) as admin:
        admin.execute("DROP DATABASE IF EXISTS migration_test")
        admin.execute("CREATE DATABASE migration_test")
    yield fresh
    with psycopg.connect(db_url, autocommit=True) as admin:
        admin.execute("DROP DATABASE IF EXISTS migration_test")


def _columns(conn, table: str) -> set[str]:
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns WHERE table_name = %s",
        (table,),
    ).fetchall()
    return {r[0] for r in rows}


@pytest.mark.db
def test_create_accounts_migration_backfills_and_reverses(fresh_db_url):
    create_snapshots, create_accounts = MIGRATIONS[0], MIGRATIONS[1]
    assert "create_accounts" in create_accounts.name

    with psycopg.connect(fresh_db_url) as conn:
        # psycopg runs multi-statement strings when no parameters are passed.
        conn.execute(split_migration(create_snapshots)[0])
        legacy = [
            (date(2024, 1, 10), "asset", "Savings", Decimal("100.00")),
            (date(2024, 1, 10), "liability", "Card", Decimal("50.00")),
            (date(2024, 2, 10), "asset", "Savings", Decimal("120.00")),
            (date(2024, 2, 10), "asset", "Brokerage", Decimal("500.00")),
        ]
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO snapshots (date, type, description, amount) VALUES (%s, %s, %s, %s)",
                legacy,
            )
        conn.commit()

        conn.execute(split_migration(create_accounts)[0])
        conn.commit()

        accounts = conn.execute("SELECT name, type FROM accounts ORDER BY id").fetchall()
        assert accounts == [("Savings", "asset"), ("Card", "liability"), ("Brokerage", "asset")]

        rows = conn.execute(
            """
            SELECT s.date, a.type, a.name, s.amount
            FROM snapshots s JOIN accounts a ON a.id = s.account_id
            """
        ).fetchall()
        assert sorted(rows) == sorted(legacy)
        assert {"type", "description"}.isdisjoint(_columns(conn, "snapshots"))
        assert "account_id" in _columns(conn, "snapshots")

        conn.execute(split_migration(create_accounts)[1])
        conn.commit()

        restored = conn.execute(
            "SELECT date, type, description, amount FROM snapshots"
        ).fetchall()
        assert sorted(restored) == sorted(legacy)
        assert "account_id" not in _columns(conn, "snapshots")
        assert conn.execute("SELECT to_regclass('accounts')").fetchone() == (None,)
```

- [ ] **Step 4: Run the migration test to verify it fails**

Run: `uv run pytest tests/test_migration.py -v --no-cov`
Expected: PASS (the migration from Step 1 backfills and reverses correctly).

Run: `uv run pytest tests/test_repository.py -v --no-cov`
Expected: FAIL with `column "type" of relation "snapshots" does not exist`, because the old repository still queries the dropped columns.

- [ ] **Step 5: Rewrite the repository**

Replace `src/asset_manager/repository.py` with:

```python
"""Thin SQL layer. Functions here never commit; callers own the transaction."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from psycopg import Connection, Cursor
from psycopg.types.json import Jsonb

from asset_manager.models import Account, DailySummary, Formula, Record, RecordType

_RECORD_SELECT = """
    SELECT s.id, s.date, s.account_id, a.type, a.name, s.amount, s.created_at
    FROM snapshots s
    JOIN accounts a ON a.id = s.account_id
"""

_ACCOUNT_SELECT = """
    SELECT a.id, a.name, a.type, a.formula, a.retired_at, a.created_at,
           COALESCE(
               array_agg(fi.input_id ORDER BY fi.input_id)
                   FILTER (WHERE fi.input_id IS NOT NULL),
               '{}'
           ) AS input_ids
    FROM accounts a
    LEFT JOIN formula_inputs fi ON fi.account_id = a.id
"""


# --- snapshots -------------------------------------------------------------


def _record_from_row(row: tuple[Any, ...]) -> Record:
    return Record(
        id=row[0],
        date=row[1],
        account_id=row[2],
        type=RecordType(row[3]),
        description=row[4],
        amount=Decimal(row[5]),
        created_at=row[6],
    )


def _select_records(
    conn: Connection,
    where: str = "",
    params: tuple[Any, ...] = (),
    order: str = "s.date, a.type, a.name",
) -> list[Record]:
    with conn.cursor() as cur:
        cur.execute(f"{_RECORD_SELECT} {where} ORDER BY {order}", params)
        rows = cur.fetchall()
    return [_record_from_row(row) for row in rows]


def get_all_records(conn: Connection) -> list[Record]:
    """Fetch all snapshot records, joined to their account."""
    return _select_records(conn)


def get_records_by_date_range(conn: Connection, start_date: date, end_date: date) -> list[Record]:
    """Fetch records within a date range."""
    return _select_records(conn, "WHERE s.date >= %s AND s.date <= %s", (start_date, end_date))


def get_latest_snapshot_records(conn: Connection) -> list[Record]:
    """Fetch records for the most recent snapshot date."""
    return _select_records(
        conn, "WHERE s.date = (SELECT MAX(date) FROM snapshots)", order="a.type, a.name"
    )


def get_summary_by_date(conn: Connection) -> list[DailySummary]:
    """Get aggregated totals by date and type."""
    query = """
        SELECT s.date, a.type, SUM(s.amount) AS total_amount
        FROM snapshots s
        JOIN accounts a ON a.id = s.account_id
        GROUP BY s.date, a.type
        ORDER BY s.date, a.type
    """
    with conn.cursor() as cur:
        cur.execute(query)
        rows = cur.fetchall()
    return [
        DailySummary(date=row[0], type=RecordType(row[1]), total_amount=Decimal(row[2]))
        for row in rows
    ]


def upsert_amounts(conn: Connection, as_of: date, amounts: dict[int, Decimal]) -> int:
    """Write one row per account for `as_of`, replacing any existing row for that date."""
    if not amounts:
        return 0
    query = """
        INSERT INTO snapshots (date, account_id, amount)
        VALUES (%s, %s, %s)
        ON CONFLICT (date, account_id) DO UPDATE SET amount = EXCLUDED.amount
    """
    with conn.cursor() as cur:
        cur.executemany(query, [(as_of, aid, amount) for aid, amount in amounts.items()])
    return len(amounts)


def insert_records(conn: Connection, records: list[Record]) -> int:
    """Temporary bridge for the Sheets fetch: resolve accounts by (type, description),
    creating unknown ones, then upsert. Commits. Replaced by sheets.save_rows in Task 6."""
    if not records:
        return 0
    by_date: dict[date, dict[int, Decimal]] = {}
    for record in records:
        account = get_account_by_name(conn, record.type, record.description)
        if account is None:
            account = insert_account(conn, Account(name=record.description, type=record.type))
        if account.id is None:
            raise ValueError("insert_account returned no id")
        by_date.setdefault(record.date, {})[account.id] = record.amount
    count = sum(upsert_amounts(conn, d, amounts) for d, amounts in by_date.items())
    conn.commit()
    return count


# --- accounts --------------------------------------------------------------


def _account_from_row(row: tuple[Any, ...]) -> Account:
    return Account.model_validate(
        {
            "id": row[0],
            "name": row[1],
            "type": row[2],
            "formula": row[3],
            "retired_at": row[4],
            "created_at": row[5],
            "input_ids": list(row[6]),
        }
    )


def _select_accounts(
    conn: Connection, where: str = "", params: tuple[Any, ...] = ()
) -> list[Account]:
    with conn.cursor() as cur:
        cur.execute(f"{_ACCOUNT_SELECT} {where} GROUP BY a.id ORDER BY a.id", params)
        rows = cur.fetchall()
    return [_account_from_row(row) for row in rows]


def _formula_param(formula: Formula | None) -> Jsonb | None:
    return Jsonb(formula.model_dump(mode="json")) if formula is not None else None


def _replace_inputs(cur: Cursor, account_id: int, input_ids: list[int]) -> None:
    cur.execute("DELETE FROM formula_inputs WHERE account_id = %s", (account_id,))
    if input_ids:
        cur.executemany(
            "INSERT INTO formula_inputs (account_id, input_id) VALUES (%s, %s)",
            [(account_id, input_id) for input_id in input_ids],
        )


def get_accounts(conn: Connection, *, include_retired: bool = True) -> list[Account]:
    """All accounts in id order, with their formula inputs."""
    where = "" if include_retired else "WHERE a.retired_at IS NULL"
    return _select_accounts(conn, where)


def get_account_by_name(conn: Connection, type: RecordType, name: str) -> Account | None:
    accounts = _select_accounts(conn, "WHERE a.type = %s AND a.name = %s", (type.value, name))
    return accounts[0] if accounts else None


def insert_account(conn: Connection, account: Account) -> Account:
    """Insert an account and its inputs. Returns the account with id and created_at set."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO accounts (name, type, formula, retired_at)
            VALUES (%s, %s, %s, %s)
            RETURNING id, created_at
            """,
            (account.name, account.type.value, _formula_param(account.formula), account.retired_at),
        )
        row = cur.fetchone()
        if row is None:
            raise RuntimeError("INSERT returned no row")
        account_id, created_at = row
        _replace_inputs(cur, account_id, account.input_ids)
    return account.model_copy(update={"id": account_id, "created_at": created_at})
```

- [ ] **Step 6: Rewrite the repository tests**

Replace `tests/test_repository.py` with:

```python
from datetime import date
from decimal import Decimal

import psycopg
import pytest

from asset_manager.models import Account, ProportionalFormula, Record, RecordType
from asset_manager.repository import (
    get_account_by_name,
    get_accounts,
    get_all_records,
    get_latest_snapshot_records,
    get_records_by_date_range,
    get_summary_by_date,
    insert_account,
    insert_records,
    upsert_amounts,
)


def make_account(conn, name: str, type: RecordType = RecordType.ASSET, **kwargs) -> Account:
    return insert_account(conn, Account(name=name, type=type, **kwargs))


@pytest.mark.db
class TestSnapshots:
    def test_upsert_and_fetch_records(self, db_connection):
        savings = make_account(db_connection, "Savings Account")
        card = make_account(db_connection, "Credit Card", RecordType.LIABILITY)

        count = upsert_amounts(
            db_connection,
            date(2024, 1, 15),
            {savings.id: Decimal("10000.00"), card.id: Decimal("500.00")},
        )
        assert count == 2

        fetched = get_all_records(db_connection)
        assert [(r.type, r.description, r.amount, r.account_id) for r in fetched] == [
            (RecordType.ASSET, "Savings Account", Decimal("10000.00"), savings.id),
            (RecordType.LIABILITY, "Credit Card", Decimal("500.00"), card.id),
        ]

    def test_upsert_replaces_same_date(self, db_connection):
        savings = make_account(db_connection, "Savings Account")
        upsert_amounts(db_connection, date(2024, 1, 15), {savings.id: Decimal("10000.00")})
        upsert_amounts(db_connection, date(2024, 1, 15), {savings.id: Decimal("15000.00")})

        fetched = get_all_records(db_connection)
        assert len(fetched) == 1
        assert fetched[0].amount == Decimal("15000.00")

    def test_upsert_empty(self, db_connection):
        assert upsert_amounts(db_connection, date(2024, 1, 15), {}) == 0
        assert get_all_records(db_connection) == []

    def test_get_records_by_date_range(self, db_connection):
        a1 = make_account(db_connection, "Account 1")
        a2 = make_account(db_connection, "Account 2")
        a3 = make_account(db_connection, "Account 3")
        upsert_amounts(db_connection, date(2024, 1, 10), {a1.id: Decimal("1000.00")})
        upsert_amounts(db_connection, date(2024, 1, 15), {a2.id: Decimal("2000.00")})
        upsert_amounts(db_connection, date(2024, 1, 20), {a3.id: Decimal("3000.00")})

        fetched = get_records_by_date_range(db_connection, date(2024, 1, 12), date(2024, 1, 18))
        assert [r.description for r in fetched] == ["Account 2"]

    def test_get_latest_snapshot_records(self, db_connection):
        a1 = make_account(db_connection, "Account 1")
        a2 = make_account(db_connection, "Account 2")
        upsert_amounts(db_connection, date(2024, 1, 10), {a1.id: Decimal("1"), a2.id: Decimal("2")})
        upsert_amounts(db_connection, date(2024, 1, 20), {a1.id: Decimal("3")})

        latest = get_latest_snapshot_records(db_connection)
        assert [(r.date, r.description, r.amount) for r in latest] == [
            (date(2024, 1, 20), "Account 1", Decimal("3.00"))
        ]

    def test_get_summary_by_date(self, db_connection):
        a1 = make_account(db_connection, "Asset 1")
        a2 = make_account(db_connection, "Asset 2")
        l1 = make_account(db_connection, "Liability 1", RecordType.LIABILITY)
        upsert_amounts(
            db_connection,
            date(2024, 1, 15),
            {a1.id: Decimal("1000.00"), a2.id: Decimal("2000.00"), l1.id: Decimal("500.00")},
        )

        summaries = get_summary_by_date(db_connection)
        assert [(s.type, s.total_amount) for s in summaries] == [
            (RecordType.ASSET, Decimal("3000.00")),
            (RecordType.LIABILITY, Decimal("500.00")),
        ]

    def test_insert_records_bridge_creates_accounts_by_name(self, db_connection):
        records = [
            Record(date=date(2024, 1, 15), type=RecordType.ASSET, description="Savings", amount=Decimal("10")),
            Record(date=date(2024, 1, 15), type=RecordType.LIABILITY, description="Card", amount=Decimal("5")),
        ]
        assert insert_records(db_connection, records) == 2
        assert [a.name for a in get_accounts(db_connection)] == ["Savings", "Card"]
        assert len(get_all_records(db_connection)) == 2


@pytest.mark.db
class TestAccounts:
    def test_insert_and_get_accounts_round_trips_formula_and_inputs(self, db_connection):
        schwab = make_account(db_connection, "Schwab")
        tax = make_account(
            db_connection,
            "Cap Gains Tax",
            RecordType.LIABILITY,
            formula=ProportionalFormula(rate=Decimal("0.15"), cost_basis=Decimal("70634.00")),
            input_ids=[schwab.id],
        )
        assert tax.id is not None
        assert tax.created_at is not None

        accounts = get_accounts(db_connection)
        assert [a.name for a in accounts] == ["Schwab", "Cap Gains Tax"]
        assert accounts[0].formula is None
        assert accounts[0].input_ids == []
        assert accounts[1].formula == ProportionalFormula(
            rate=Decimal("0.15"), cost_basis=Decimal("70634.00")
        )
        assert accounts[1].input_ids == [schwab.id]

    def test_get_accounts_can_exclude_retired(self, db_connection):
        make_account(db_connection, "Live")
        make_account(db_connection, "Old", retired_at=date(2026, 1, 1))
        assert [a.name for a in get_accounts(db_connection)] == ["Live", "Old"]
        assert [a.name for a in get_accounts(db_connection, include_retired=False)] == ["Live"]

    def test_get_account_by_name_is_per_type(self, db_connection):
        make_account(db_connection, "Winchester", RecordType.ASSET)
        make_account(db_connection, "Winchester", RecordType.LIABILITY)
        asset = get_account_by_name(db_connection, RecordType.ASSET, "Winchester")
        liability = get_account_by_name(db_connection, RecordType.LIABILITY, "Winchester")
        assert asset is not None and asset.type == RecordType.ASSET
        assert liability is not None and liability.type == RecordType.LIABILITY
        assert get_account_by_name(db_connection, RecordType.ASSET, "Nope") is None

    def test_name_is_unique_within_type(self, db_connection):
        make_account(db_connection, "Savings")
        with pytest.raises(psycopg.errors.UniqueViolation):
            make_account(db_connection, "Savings")
        db_connection.rollback()
```

- [ ] **Step 7: Run the full suite to verify it passes**

Run: `uv run pytest -v --no-cov`
Expected: all PASS, including `test_migration.py`, `test_repository.py`, and the untouched `test_sheets.py` and `test_report.py`.

- [ ] **Step 8: Lint, typecheck, commit (including the regenerated schema dump)**

```bash
uv run ruff check src tests && uv run ruff format src tests && uv run ty check src/asset_manager
git add db/migrations/20260906120000_create_accounts.sql db/schema.sql tests/conftest.py tests/test_migration.py src/asset_manager/repository.py tests/test_repository.py
git commit -m "Add accounts table and key snapshots by account id"
```

---

### Task 4: Repository account operations

**Files:**
- Modify: `src/asset_manager/repository.py` (append)
- Modify: `tests/test_repository.py` (append to `TestAccounts`)

**Interfaces:**
- Produces: `get_account(conn, account_id) -> Account | None`, `update_account(conn, account) -> None`, `set_formula(conn, account_id, formula) -> None`, `set_retired_at(conn, account_id, retired_at) -> None`, `get_dependents(conn, account_id) -> list[Account]`, `get_latest_amount(conn, account_id) -> Decimal | None`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_repository.py` (add the new names to the import list at the top: `get_account`, `get_dependents`, `get_latest_amount`, `set_formula`, `set_retired_at`, `update_account`):

```python
@pytest.mark.db
class TestAccountOperations:
    def test_get_account(self, db_connection):
        savings = make_account(db_connection, "Savings")
        loaded = get_account(db_connection, savings.id)
        assert loaded is not None and loaded.name == "Savings"
        assert get_account(db_connection, 9999) is None

    def test_update_account_replaces_name_formula_and_inputs(self, db_connection):
        a = make_account(db_connection, "A")
        b = make_account(db_connection, "B")
        tax = make_account(
            db_connection,
            "Tax",
            RecordType.LIABILITY,
            formula=ProportionalFormula(rate=Decimal("0.1")),
            input_ids=[a.id],
        )
        update_account(
            db_connection,
            tax.model_copy(
                update={
                    "name": "Tax v2",
                    "formula": ProportionalFormula(rate=Decimal("0.2"), cost_basis=Decimal("5")),
                    "input_ids": [b.id],
                }
            ),
        )
        loaded = get_account(db_connection, tax.id)
        assert loaded is not None
        assert loaded.name == "Tax v2"
        assert loaded.formula == ProportionalFormula(rate=Decimal("0.2"), cost_basis=Decimal("5"))
        assert loaded.input_ids == [b.id]

    def test_update_account_can_clear_formula(self, db_connection):
        a = make_account(db_connection, "A")
        tax = make_account(
            db_connection,
            "Tax",
            RecordType.LIABILITY,
            formula=ProportionalFormula(rate=Decimal("0.1")),
            input_ids=[a.id],
        )
        update_account(db_connection, tax.model_copy(update={"formula": None, "input_ids": []}))
        loaded = get_account(db_connection, tax.id)
        assert loaded is not None and loaded.formula is None and loaded.input_ids == []

    def test_set_formula_only_touches_the_document(self, db_connection):
        a = make_account(db_connection, "A")
        tax = make_account(
            db_connection,
            "Tax",
            RecordType.LIABILITY,
            formula=ProportionalFormula(rate=Decimal("0.1")),
            input_ids=[a.id],
        )
        set_formula(db_connection, tax.id, ProportionalFormula(rate=Decimal("0.1"), cost_basis=Decimal("42")))
        loaded = get_account(db_connection, tax.id)
        assert loaded is not None
        assert loaded.formula == ProportionalFormula(rate=Decimal("0.1"), cost_basis=Decimal("42"))
        assert loaded.input_ids == [a.id]

    def test_set_retired_at_round_trips(self, db_connection):
        a = make_account(db_connection, "A")
        set_retired_at(db_connection, a.id, date(2026, 9, 1))
        loaded = get_account(db_connection, a.id)
        assert loaded is not None and loaded.retired_at == date(2026, 9, 1)
        set_retired_at(db_connection, a.id, None)
        loaded = get_account(db_connection, a.id)
        assert loaded is not None and loaded.retired_at is None

    def test_get_dependents_lists_active_computed_accounts_only(self, db_connection):
        a = make_account(db_connection, "A")
        live = make_account(
            db_connection, "Live Tax", RecordType.LIABILITY,
            formula=ProportionalFormula(rate=Decimal("0.1")), input_ids=[a.id],
        )
        make_account(
            db_connection, "Old Tax", RecordType.LIABILITY,
            formula=ProportionalFormula(rate=Decimal("0.1")), input_ids=[a.id],
            retired_at=date(2026, 1, 1),
        )
        assert [d.id for d in get_dependents(db_connection, a.id)] == [live.id]
        assert get_dependents(db_connection, live.id) == []

    def test_get_latest_amount_uses_the_accounts_own_latest_row(self, db_connection):
        a = make_account(db_connection, "A")
        b = make_account(db_connection, "B")
        upsert_amounts(db_connection, date(2024, 1, 10), {a.id: Decimal("10"), b.id: Decimal("1")})
        upsert_amounts(db_connection, date(2024, 2, 10), {b.id: Decimal("2")})
        assert get_latest_amount(db_connection, a.id) == Decimal("10.00")
        assert get_latest_amount(db_connection, b.id) == Decimal("2.00")
        assert get_latest_amount(db_connection, 9999) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_repository.py -v --no-cov`
Expected: ImportError for `get_account` and the other new names.

- [ ] **Step 3: Append the functions to the repository**

Append to `src/asset_manager/repository.py`:

```python
def get_account(conn: Connection, account_id: int) -> Account | None:
    accounts = _select_accounts(conn, "WHERE a.id = %s", (account_id,))
    return accounts[0] if accounts else None


def update_account(conn: Connection, account: Account) -> None:
    """Replace name, formula document, and inputs. Type and retirement are untouched."""
    if account.id is None:
        raise ValueError("Cannot update an account without an id")
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE accounts SET name = %s, formula = %s WHERE id = %s",
            (account.name, _formula_param(account.formula), account.id),
        )
        _replace_inputs(cur, account.id, account.input_ids)


def set_formula(conn: Connection, account_id: int, formula: Formula | None) -> None:
    """Replace only the formula document, leaving inputs alone."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE accounts SET formula = %s WHERE id = %s",
            (_formula_param(formula), account_id),
        )


def set_retired_at(conn: Connection, account_id: int, retired_at: date | None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE accounts SET retired_at = %s WHERE id = %s", (retired_at, account_id)
        )


def get_dependents(conn: Connection, account_id: int) -> list[Account]:
    """Active computed accounts that list `account_id` as an input."""
    return _select_accounts(
        conn,
        """
        WHERE a.retired_at IS NULL
          AND a.id IN (SELECT account_id FROM formula_inputs WHERE input_id = %s)
        """,
        (account_id,),
    )


def get_latest_amount(conn: Connection, account_id: int) -> Decimal | None:
    """The amount in this account's own most recent snapshot row, if any."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT amount FROM snapshots WHERE account_id = %s ORDER BY date DESC LIMIT 1",
            (account_id,),
        )
        row = cur.fetchone()
    return Decimal(row[0]) if row else None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_repository.py -v --no-cov`
Expected: all PASS.

- [ ] **Step 5: Lint, typecheck, commit**

```bash
uv run ruff check src tests && uv run ruff format src tests && uv run ty check src/asset_manager
git add src/asset_manager/repository.py tests/test_repository.py
git commit -m "Add account update, retire, dependents and latest-amount queries"
```

---

### Task 5: Account service and save transaction

**Files:**
- Create: `src/asset_manager/accounts.py`
- Create: `tests/test_accounts.py`

**Interfaces:**
- Consumes: repository from Tasks 3 and 4; `compute_snapshot`, `MissingValueError`, `quantize_cents` from Task 2.
- Produces: `AccountError(ValueError)`, `parse_amount(text) -> Decimal`, `create_account(conn, name, type, formula=None, input_ids=()) -> Account`, `update_account(conn, account_id, name, formula=None, input_ids=()) -> Account`, `retire_blocker(conn, account) -> str | None`, `retire_account(conn, account_id, on: date) -> Account`, `unretire_account(conn, account_id) -> Account`, `save_snapshot(conn, values: dict[int, Decimal], cost_bases: dict[int, Decimal], as_of: date) -> int`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_accounts.py`:

```python
"""Tests for the account service: rules and the save transaction."""

from datetime import date
from decimal import Decimal

import pytest

from asset_manager.accounts import (
    AccountError,
    create_account,
    parse_amount,
    retire_account,
    retire_blocker,
    save_snapshot,
    unretire_account,
    update_account,
)
from asset_manager.models import ProportionalFormula, RecordType
from asset_manager.repository import get_account, get_all_records, upsert_amounts

TODAY = date(2026, 9, 6)
RATE = ProportionalFormula(rate=Decimal("0.15"))


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1531.32", Decimal("1531.32")),
        ("$1,531.32", Decimal("1531.32")),
        (" 1,531 ", Decimal("1531.00")),
        ("-17.44", Decimal("-17.44")),
        ("(17.44)", Decimal("-17.44")),
        ("0", Decimal("0.00")),
        ("10.005", Decimal("10.01")),
    ],
)
def test_parse_amount(text, expected):
    assert parse_amount(text) == expected


@pytest.mark.parametrize("text", ["", "abc", "1.2.3", "NaN", "Infinity"])
def test_parse_amount_rejects_junk(text):
    with pytest.raises(AccountError):
        parse_amount(text)


@pytest.mark.db
class TestCreateAndUpdate:
    def test_create_strips_name(self, db_connection):
        account = create_account(db_connection, "  Savings   Account ", RecordType.ASSET)
        assert account.name == "Savings Account"
        assert account.id is not None

    def test_create_rejects_blank_name(self, db_connection):
        with pytest.raises(AccountError, match="Name is required"):
            create_account(db_connection, "   ", RecordType.ASSET)

    def test_create_rejects_duplicate_name_within_type(self, db_connection):
        create_account(db_connection, "Savings", RecordType.ASSET)
        with pytest.raises(AccountError, match="already exists"):
            create_account(db_connection, "Savings", RecordType.ASSET)
        create_account(db_connection, "Savings", RecordType.LIABILITY)

    def test_computed_needs_an_input(self, db_connection):
        with pytest.raises(AccountError, match="at least one input"):
            create_account(db_connection, "Tax", RecordType.LIABILITY, RATE, [])

    def test_input_must_exist_and_be_plain_and_active(self, db_connection):
        schwab = create_account(db_connection, "Schwab", RecordType.ASSET)
        tax = create_account(db_connection, "Tax", RecordType.LIABILITY, RATE, [schwab.id])
        retired = create_account(db_connection, "Old", RecordType.ASSET)
        retire_account(db_connection, retired.id, TODAY)

        with pytest.raises(AccountError, match="does not exist"):
            create_account(db_connection, "X", RecordType.LIABILITY, RATE, [9999])
        with pytest.raises(AccountError, match="is computed"):
            create_account(db_connection, "X", RecordType.LIABILITY, RATE, [tax.id])
        with pytest.raises(AccountError, match="is retired"):
            create_account(db_connection, "X", RecordType.LIABILITY, RATE, [retired.id])

    def test_inputs_are_deduplicated_and_sorted(self, db_connection):
        a = create_account(db_connection, "A", RecordType.ASSET)
        b = create_account(db_connection, "B", RecordType.ASSET)
        tax = create_account(db_connection, "Tax", RecordType.LIABILITY, RATE, [b.id, a.id, b.id])
        assert tax.input_ids == [a.id, b.id]

    def test_update_renames_and_rejects_collision(self, db_connection):
        a = create_account(db_connection, "A", RecordType.ASSET)
        create_account(db_connection, "B", RecordType.ASSET)
        updated = update_account(db_connection, a.id, "A2")
        assert updated.name == "A2"
        with pytest.raises(AccountError, match="already exists"):
            update_account(db_connection, a.id, "B")
        # Keeping your own name is fine
        update_account(db_connection, a.id, "A2")

    def test_update_cannot_use_self_as_input(self, db_connection):
        a = create_account(db_connection, "A", RecordType.LIABILITY)
        with pytest.raises(AccountError, match="its own input"):
            update_account(db_connection, a.id, "A", RATE, [a.id])

    def test_an_input_cannot_be_made_computed(self, db_connection):
        schwab = create_account(db_connection, "Schwab", RecordType.ASSET)
        other = create_account(db_connection, "Other", RecordType.ASSET)
        create_account(db_connection, "Tax", RecordType.LIABILITY, RATE, [schwab.id])
        with pytest.raises(AccountError, match="is an input to Tax"):
            update_account(db_connection, schwab.id, "Schwab", RATE, [other.id])

    def test_update_can_add_formula_to_plain_account(self, db_connection):
        schwab = create_account(db_connection, "Schwab", RecordType.ASSET)
        tax = create_account(db_connection, "Tax", RecordType.LIABILITY)
        updated = update_account(db_connection, tax.id, "Tax", RATE, [schwab.id])
        assert updated.formula == RATE
        assert updated.input_ids == [schwab.id]
        loaded = get_account(db_connection, tax.id)
        assert loaded is not None and loaded.input_ids == [schwab.id]


@pytest.mark.db
class TestRetire:
    def test_retire_blocked_when_latest_amount_is_nonzero(self, db_connection):
        a = create_account(db_connection, "A", RecordType.ASSET)
        upsert_amounts(db_connection, date(2026, 1, 1), {a.id: Decimal("5")})
        db_connection.commit()
        assert retire_blocker(db_connection, a) is not None
        with pytest.raises(AccountError, match="Set it to zero and save"):
            retire_account(db_connection, a.id, TODAY)

    def test_retire_blocked_when_it_feeds_a_formula(self, db_connection):
        schwab = create_account(db_connection, "Schwab", RecordType.ASSET)
        create_account(db_connection, "Tax", RecordType.LIABILITY, RATE, [schwab.id])
        with pytest.raises(AccountError, match="is an input to Tax"):
            retire_account(db_connection, schwab.id, TODAY)

    def test_retire_allowed_at_zero_or_never_snapshotted(self, db_connection):
        never = create_account(db_connection, "Never", RecordType.ASSET)
        zero = create_account(db_connection, "Zero", RecordType.ASSET)
        upsert_amounts(db_connection, date(2026, 1, 1), {zero.id: Decimal("0")})
        db_connection.commit()
        assert retire_blocker(db_connection, never) is None
        assert retire_account(db_connection, never.id, TODAY).retired_at == TODAY
        assert retire_account(db_connection, zero.id, TODAY).retired_at == TODAY
        loaded = get_account(db_connection, zero.id)
        assert loaded is not None and loaded.retired_at == TODAY

    def test_retire_twice_and_unretire(self, db_connection):
        a = create_account(db_connection, "A", RecordType.ASSET)
        retire_account(db_connection, a.id, TODAY)
        with pytest.raises(AccountError, match="already retired"):
            retire_account(db_connection, a.id, TODAY)
        assert unretire_account(db_connection, a.id).retired_at is None
        with pytest.raises(AccountError, match="is not retired"):
            unretire_account(db_connection, a.id)


@pytest.mark.db
class TestSaveSnapshot:
    def _setup(self, conn):
        schwab = create_account(conn, "Schwab", RecordType.ASSET)
        cash = create_account(conn, "Cash", RecordType.ASSET)
        tax = create_account(
            conn, "Tax", RecordType.LIABILITY,
            ProportionalFormula(rate=Decimal("0.15"), cost_basis=Decimal("100")),
            [schwab.id],
        )
        old = create_account(conn, "Old", RecordType.ASSET)
        retire_account(conn, old.id, date(2026, 1, 1))
        return schwab, cash, tax, old

    def test_writes_every_active_account_and_updates_basis(self, db_connection):
        schwab, cash, tax, old = self._setup(db_connection)
        count = save_snapshot(
            db_connection,
            {schwab.id: Decimal("1000"), cash.id: Decimal("50")},
            {tax.id: Decimal("400")},
            TODAY,
        )
        assert count == 3
        rows = {(r.description, r.amount) for r in get_all_records(db_connection)}
        assert rows == {("Schwab", Decimal("1000.00")), ("Cash", Decimal("50.00")), ("Tax", Decimal("90.00"))}
        loaded = get_account(db_connection, tax.id)
        assert loaded is not None and loaded.formula is not None
        assert loaded.formula.cost_basis == Decimal("400.00")

    def test_same_day_save_replaces(self, db_connection):
        schwab, cash, tax, _ = self._setup(db_connection)
        save_snapshot(db_connection, {schwab.id: Decimal("1000"), cash.id: Decimal("50")}, {}, TODAY)
        save_snapshot(db_connection, {schwab.id: Decimal("2000"), cash.id: Decimal("50")}, {}, TODAY)
        rows = {(r.description, r.amount) for r in get_all_records(db_connection)}
        assert rows == {("Schwab", Decimal("2000.00")), ("Cash", Decimal("50.00")), ("Tax", Decimal("285.00"))}

    def test_missing_value_writes_nothing_including_basis(self, db_connection):
        schwab, cash, tax, _ = self._setup(db_connection)
        with pytest.raises(AccountError, match="Missing value for Cash"):
            save_snapshot(db_connection, {schwab.id: Decimal("1000")}, {tax.id: Decimal("999")}, TODAY)
        assert get_all_records(db_connection) == []
        loaded = get_account(db_connection, tax.id)
        assert loaded is not None and loaded.formula is not None
        assert loaded.formula.cost_basis == Decimal("100")

    def test_rejects_retired_computed_and_unknown_ids(self, db_connection):
        schwab, cash, tax, old = self._setup(db_connection)
        base = {schwab.id: Decimal("1"), cash.id: Decimal("1")}
        with pytest.raises(AccountError, match="not an active account"):
            save_snapshot(db_connection, {**base, old.id: Decimal("0")}, {}, TODAY)
        with pytest.raises(AccountError, match="is computed"):
            save_snapshot(db_connection, {**base, tax.id: Decimal("0")}, {}, TODAY)
        with pytest.raises(AccountError, match="not an active computed account"):
            save_snapshot(db_connection, base, {cash.id: Decimal("0")}, TODAY)
        assert get_all_records(db_connection) == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_accounts.py -v --no-cov`
Expected: ImportError, `asset_manager.accounts` does not exist.

- [ ] **Step 3: Write the service**

Create `src/asset_manager/accounts.py`:

```python
"""Account rules and the snapshot save transaction.

Everything here raises AccountError with a message that is safe to show the
user. Functions commit on success.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from decimal import Decimal, InvalidOperation

from psycopg import Connection

from . import repository as repo
from .formulas import MissingValueError, compute_snapshot, quantize_cents
from .models import Account, Formula, RecordType


class AccountError(ValueError):
    """A rule violation with a user-facing message."""


def parse_amount(text: str) -> Decimal:
    """Parse "$1,234.56", "-17.44", or "(17.44)" into a Decimal with two places."""
    cleaned = text.replace("$", "").replace(",", "").replace(" ", "").strip()
    negative = cleaned.startswith("(") and cleaned.endswith(")")
    if negative:
        cleaned = cleaned[1:-1]
    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        raise AccountError(f"{text.strip()!r} is not a number") from None
    if not amount.is_finite():
        raise AccountError(f"{text.strip()!r} is not a number")
    return quantize_cents(-amount if negative else amount)


def _clean_name(name: str) -> str:
    cleaned = " ".join(name.split())
    if not cleaned:
        raise AccountError("Name is required")
    return cleaned


def _get_or_error(conn: Connection, account_id: int) -> Account:
    account = repo.get_account(conn, account_id)
    if account is None:
        raise AccountError(f"Account {account_id} does not exist")
    return account


def _check_name_free(
    conn: Connection, type: RecordType, name: str, *, except_id: int | None = None
) -> None:
    other = repo.get_account_by_name(conn, type, name)
    if other is not None and other.id != except_id:
        raise AccountError(f"A {type.value} named {name!r} already exists")


def _validate_inputs(
    conn: Connection,
    account_id: int | None,
    formula: Formula | None,
    input_ids: Iterable[int],
) -> list[int]:
    if formula is None:
        return []
    ids = sorted(set(input_ids))
    if not ids:
        raise AccountError("A computed account needs at least one input")
    for input_id in ids:
        if input_id == account_id:
            raise AccountError("An account cannot be its own input")
        candidate = repo.get_account(conn, input_id)
        if candidate is None:
            raise AccountError(f"Input account {input_id} does not exist")
        if not candidate.is_active:
            raise AccountError(f"{candidate.name} is retired and cannot be an input")
        if candidate.is_computed:
            raise AccountError(f"{candidate.name} is computed and cannot be an input")
    return ids


def _dependents_message(account: Account, dependents: list[Account]) -> str:
    names = ", ".join(d.name for d in dependents)
    return f"{account.name} is an input to {names}"


def create_account(
    conn: Connection,
    name: str,
    type: RecordType,
    formula: Formula | None = None,
    input_ids: Iterable[int] = (),
) -> Account:
    name = _clean_name(name)
    _check_name_free(conn, type, name)
    ids = _validate_inputs(conn, None, formula, input_ids)
    account = repo.insert_account(
        conn, Account(name=name, type=type, formula=formula, input_ids=ids)
    )
    conn.commit()
    return account


def update_account(
    conn: Connection,
    account_id: int,
    name: str,
    formula: Formula | None = None,
    input_ids: Iterable[int] = (),
) -> Account:
    existing = _get_or_error(conn, account_id)
    name = _clean_name(name)
    _check_name_free(conn, existing.type, name, except_id=account_id)
    if formula is not None:
        dependents = repo.get_dependents(conn, account_id)
        if dependents:
            raise AccountError(
                f"{_dependents_message(existing, dependents)} and cannot be computed"
            )
    ids = _validate_inputs(conn, account_id, formula, input_ids)
    updated = existing.model_copy(update={"name": name, "formula": formula, "input_ids": ids})
    repo.update_account(conn, updated)
    conn.commit()
    return updated


def retire_blocker(conn: Connection, account: Account) -> str | None:
    """Why this account cannot be retired right now, or None if it can."""
    if account.id is None:
        return "Account has not been saved"
    latest = repo.get_latest_amount(conn, account.id)
    if latest is not None and latest != 0:
        return (
            f"{account.name} was ${latest:,.2f} in its latest snapshot. "
            "Set it to zero and save before retiring."
        )
    dependents = repo.get_dependents(conn, account.id)
    if dependents:
        return f"{_dependents_message(account, dependents)}. Retire or edit those first."
    return None


def retire_account(conn: Connection, account_id: int, on: date) -> Account:
    account = _get_or_error(conn, account_id)
    if not account.is_active:
        raise AccountError(f"{account.name} is already retired")
    blocker = retire_blocker(conn, account)
    if blocker is not None:
        raise AccountError(blocker)
    repo.set_retired_at(conn, account_id, on)
    conn.commit()
    return account.model_copy(update={"retired_at": on})


def unretire_account(conn: Connection, account_id: int) -> Account:
    account = _get_or_error(conn, account_id)
    if account.is_active:
        raise AccountError(f"{account.name} is not retired")
    repo.set_retired_at(conn, account_id, None)
    conn.commit()
    return account.model_copy(update={"retired_at": None})


def save_snapshot(
    conn: Connection,
    values: dict[int, Decimal],
    cost_bases: dict[int, Decimal],
    as_of: date,
) -> int:
    """Write a complete snapshot for `as_of`: every active account gets a row.

    `values` must hold an amount for every active plain account. `cost_bases`
    updates the formula document of computed accounts before evaluation.
    All or nothing.
    """
    try:
        with conn.transaction():
            accounts = repo.get_accounts(conn, include_retired=False)
            by_id = {a.id: a for a in accounts if a.id is not None}

            for account_id, amount in values.items():
                account = by_id.get(account_id)
                if account is None:
                    raise AccountError(f"Account {account_id} is not an active account")
                if account.is_computed:
                    raise AccountError(f"{account.name} is computed and cannot be set directly")
                if not amount.is_finite():
                    raise AccountError(f"{account.name} has an invalid amount")

            for account_id, basis in cost_bases.items():
                account = by_id.get(account_id)
                if account is None or account.formula is None:
                    raise AccountError(f"Account {account_id} is not an active computed account")
                if not basis.is_finite():
                    raise AccountError(f"{account.name} has an invalid cost basis")
                formula = account.formula.model_copy(update={"cost_basis": quantize_cents(basis)})
                repo.set_formula(conn, account_id, formula)
                by_id[account_id] = account.model_copy(update={"formula": formula})

            amounts = compute_snapshot(list(by_id.values()), values, as_of)
            return repo.upsert_amounts(conn, as_of, amounts)
    except MissingValueError as e:
        raise AccountError(str(e)) from e
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_accounts.py -v --no-cov`
Expected: all PASS. If `test_missing_value_writes_nothing_including_basis` fails with the basis changed, the transaction did not roll back: check that `conn.transaction()` wraps every write.

- [ ] **Step 5: Lint, typecheck, commit**

```bash
uv run ruff check src tests && uv run ruff format src tests && uv run ty check src/asset_manager
git add src/asset_manager/accounts.py tests/test_accounts.py
git commit -m "Add account service with retire rules and snapshot save"
```

---

### Task 6: Sheets fetch through the cutover

**Files:**
- Modify: `src/asset_manager/sheets.py`
- Modify: `src/asset_manager/cli.py`
- Modify: `src/asset_manager/repository.py` (delete `insert_records`)
- Modify: `tests/test_sheets.py`
- Modify: `tests/test_repository.py` (delete the `insert_records` test and import)

**Interfaces:**
- Produces: `ParsedRow(type, description, amount)`, `parse_rows_from_table(raw_table, col_idx, record_type) -> list[ParsedRow]`, `fetch_rows() -> list[ParsedRow]`, `describe_rows(conn, rows) -> list[str]`, `save_rows(conn, rows, as_of) -> int`, `fetch_and_save() -> int`.

- [ ] **Step 1: Update the parsing tests and add save tests**

In `tests/test_sheets.py`:

1. Change the import block to:

```python
import os
from datetime import date
from decimal import Decimal

import pytest

from asset_manager.accounts import create_account, retire_account
from asset_manager.models import RecordType
from asset_manager.repository import get_accounts, get_all_records
from asset_manager.sheets import (
    ParsedRow,
    describe_rows,
    dollars_to_decimal,
    get_service,
    parse_rows_from_table,
    save_rows,
)
```

2. In each `parse_records_from_table` test: rename the call to `parse_rows_from_table`, drop the `record_date` variable and the fourth argument, and delete the `assert records[0].date == record_date` line. For example the assets test becomes:

```python
def test_parse_rows_from_table_assets():
    raw_table = [
        ["Description", "Amount", "Accessible", "Liquidity"],
        ["Savings", "$1,000.00", "Y", "$500.00"],
        ["401k", "$5,000.00", "N", "$0.00"],
    ]
    rows = parse_rows_from_table(raw_table, slice(0, 4), RecordType.ASSET)

    assert len(rows) == 2
    assert rows[0].description == "Savings"
    assert rows[0].amount == Decimal("1000.00")
    assert rows[0].type == RecordType.ASSET
    assert rows[1].description == "401k"
    assert rows[1].amount == Decimal("5000.00")
```

Apply the same rename to the liabilities, skips-blank-rows, and empty tests.

3. Append:

```python
@pytest.mark.db
def test_save_rows_creates_unknown_accounts_and_skips_retired(db_connection, capsys):
    known = create_account(db_connection, "Savings", RecordType.ASSET)
    old = create_account(db_connection, "Old 401k", RecordType.ASSET)
    retire_account(db_connection, old.id, date(2026, 1, 1))
    rows = [
        ParsedRow(type=RecordType.ASSET, description="Savings", amount=Decimal("10")),
        ParsedRow(type=RecordType.ASSET, description="Brokerage", amount=Decimal("20")),
        ParsedRow(type=RecordType.ASSET, description="Old 401k", amount=Decimal("5")),
        ParsedRow(type=RecordType.LIABILITY, description="Card", amount=Decimal("1")),
    ]

    count = save_rows(db_connection, rows, date(2026, 9, 6))

    assert count == 3
    assert [a.name for a in get_accounts(db_connection)] == ["Savings", "Old 401k", "Brokerage", "Card"]
    written = {(r.description, r.amount) for r in get_all_records(db_connection)}
    assert written == {("Savings", Decimal("10.00")), ("Brokerage", Decimal("20.00")), ("Card", Decimal("1.00"))}
    assert known.id is not None
    assert "Old 401k is retired" in capsys.readouterr().out


@pytest.mark.db
def test_describe_rows_annotates_new_and_retired(db_connection):
    create_account(db_connection, "Savings", RecordType.ASSET)
    old = create_account(db_connection, "Old", RecordType.ASSET)
    retire_account(db_connection, old.id, date(2026, 1, 1))
    rows = [
        ParsedRow(type=RecordType.ASSET, description="Savings", amount=Decimal("10")),
        ParsedRow(type=RecordType.ASSET, description="New", amount=Decimal("1")),
        ParsedRow(type=RecordType.ASSET, description="Old", amount=Decimal("0")),
    ]
    lines = describe_rows(db_connection, rows)
    assert lines == [
        "  asset: Savings = $10",
        "  asset: New = $1  (new account)",
        "  asset: Old = $0  (retired, skipped)",
    ]
```

4. In `tests/test_repository.py`, delete `test_insert_records_bridge_creates_accounts_by_name` and remove `insert_records` and `Record` from the imports.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_sheets.py -v --no-cov`
Expected: ImportError for `ParsedRow`, `parse_rows_from_table`, `save_rows`, `describe_rows`.

- [ ] **Step 3: Rewrite sheets.py**

Replace `src/asset_manager/sheets.py` with:

```python
from __future__ import annotations

import configparser
import datetime
import os
import re
from decimal import Decimal
from importlib import resources
from typing import Any

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from psycopg import Connection
from pydantic import BaseModel

from .db import get_connection_context
from .models import Account, RecordType
from .repository import get_account_by_name, insert_account, upsert_amounts

SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]

config_contents = (
    resources.files("asset_manager").joinpath("data/config.ini").read_text()
)
config = configparser.ConfigParser()
config.read_string(config_contents)
SHEET_ID = config["DEFAULT"]["SHEET_ID"]
SHEET_RANGE = config["DEFAULT"]["SHEET_RANGE"]


class ParsedRow(BaseModel):
    """One line of the sheet: an account name and its amount."""

    type: RecordType
    description: str
    amount: Decimal


def get_service() -> Any:
    """
    From https://developers.google.com/sheets/api/quickstart/python
    """
    service_account_file = os.environ["GOOGLE_APPLICATION_CREDENTIALS"]
    creds = Credentials.from_service_account_file(
        service_account_file,
        scopes=SCOPES,
    )
    service = build("sheets", "v4", credentials=creds)
    return service


def dollars_to_decimal(dollar_str: str) -> Decimal:
    """Convert a dollar string like '$1,234.56' to a Decimal."""
    pattern = r"\d+(,\d{3})*(.\d\d)?"
    matches = re.search(pattern, dollar_str)
    if matches is not None:
        return Decimal(matches[0].replace(",", ""))
    elif "$ -" in dollar_str:
        return Decimal("0")
    else:
        raise ValueError(f"can't parse '{dollar_str}'")


def parse_rows_from_table(
    raw_table: list[list[str]],
    col_idx: slice,
    record_type: RecordType,
) -> list[ParsedRow]:
    """
    Parse rows from a raw table slice.

    Args:
        raw_table: Raw table data from Google Sheets
        col_idx: Slice indicating which columns to use
        record_type: Whether these are assets or liabilities
    """
    # Find where the first blank row occurs in the given columns
    first_blank = len(raw_table)
    for i, row in enumerate(raw_table):
        if len(row) <= col_idx.start:
            first_blank = i
            break

    rows_in_range = raw_table[:first_blank]

    # Extract the slice from each row, handling short rows
    def row_from_slice(row: list[str], _slice: slice) -> list[str]:
        if len(row) < _slice.start:
            return [""] * (_slice.stop - _slice.start)
        return row[_slice] + [""] * max(0, _slice.stop - len(row))

    rows_in_range = [row_from_slice(r, col_idx) for r in rows_in_range]

    if not rows_in_range:
        return []

    col_headers, *values = rows_in_range

    # Find column indices
    desc_idx = col_headers.index("Description") if "Description" in col_headers else 0
    # Amount is typically the column with dollar values
    amount_idx = None
    for idx, header in enumerate(col_headers):
        if (
            header not in ("Description", "Liquidity", "Accessible")
            and amount_idx is None
        ):
            # First non-Description, non-Liquidity, non-Accessible column is likely the amount
            amount_idx = idx

    if amount_idx is None:
        amount_idx = 1  # Default fallback

    rows = []
    for row in values:
        # Skip blank rows
        if len(row) <= desc_idx or not row[desc_idx].strip():
            continue

        description = row[desc_idx].strip()
        amount_str = row[amount_idx] if len(row) > amount_idx else "$ -"

        try:
            amount = dollars_to_decimal(amount_str)
        except ValueError:
            print(f"Warning: Could not parse amount '{amount_str}' for {description}")
            continue

        rows.append(ParsedRow(type=record_type, description=description, amount=amount))

    return rows


def fetch_rows() -> list[ParsedRow]:
    """
    Fetch data from Google Sheets and parse into rows.

    Returns the parsed rows without saving to the database.
    """
    service = get_service()
    sheets = service.spreadsheets()
    print("Pulling spreadsheet...")
    my_sheet = sheets.values().get(spreadsheetId=SHEET_ID, range=SHEET_RANGE).execute()
    raw_table: list[list[str]] = my_sheet.get("values", [])

    if not raw_table:
        print("No data found in the spreadsheet")
        return []

    # Some sad hard-coding...
    asset_cols = slice(0, 4)
    liability_cols = slice(4, 7)
    # The first row is just the headings: "Assets" & "Liabilities"
    raw_table = raw_table[1:]

    asset_rows = parse_rows_from_table(raw_table, asset_cols, RecordType.ASSET)
    liability_rows = parse_rows_from_table(raw_table, liability_cols, RecordType.LIABILITY)
    return asset_rows + liability_rows


def describe_rows(conn: Connection, rows: list[ParsedRow]) -> list[str]:
    """One printable line per row, noting accounts that would be created or skipped."""
    lines = []
    for row in rows:
        account = get_account_by_name(conn, row.type, row.description)
        if account is None:
            note = "  (new account)"
        elif not account.is_active:
            note = "  (retired, skipped)"
        else:
            note = ""
        lines.append(f"  {row.type.value}: {row.description} = ${row.amount}{note}")
    return lines


def save_rows(conn: Connection, rows: list[ParsedRow], as_of: datetime.date) -> int:
    """Write the sheet's values for `as_of`.

    Unknown descriptions become plain accounts. Retired accounts are skipped,
    with a warning if the sheet still shows a non-zero amount for one.
    Formulas are not evaluated: the sheet's own computed cells are written as-is.
    Commits.
    """
    amounts: dict[int, Decimal] = {}
    for row in rows:
        account = get_account_by_name(conn, row.type, row.description)
        if account is None:
            account = insert_account(conn, Account(name=row.description, type=row.type))
            print(f"Created account: {row.type.value} {row.description}")
        elif not account.is_active:
            if row.amount != 0:
                print(
                    f"Warning: {row.description} is retired but the sheet shows "
                    f"${row.amount}; skipping"
                )
            continue
        if account.id is not None:
            amounts[account.id] = row.amount
    count = upsert_amounts(conn, as_of, amounts)
    conn.commit()
    return count


def fetch_and_save() -> int:
    """
    Fetch data from Google Sheets and save to the database.

    Returns the number of records saved.
    """
    rows = fetch_rows()
    if not rows:
        return 0

    print(f"Parsed {len(rows)} rows:")
    with get_connection_context() as conn:
        for line in describe_rows(conn, rows):
            print(line)
        count = save_rows(conn, rows, datetime.date.today())
        print(f"Saved {count} records to database")
    return count
```

- [ ] **Step 4: Update the CLI**

In `src/asset_manager/cli.py`:

1. Change the sheets import to `from .sheets import describe_rows, fetch_and_save, fetch_rows`.
2. Replace the `if dry_run:` block inside `fetch` with:

```python
    if dry_run:
        try:
            rows = fetch_rows()
        except Exception as exc:
            typer.echo(f"Error fetching data: {exc}", err=True)
            raise typer.Exit(code=1)

        if not rows:
            typer.echo("No rows found.")
            raise typer.Exit(code=1)

        typer.echo(f"Found {len(rows)} rows (dry run, not saving):\n")
        try:
            with get_connection_context() as conn:
                for line in describe_rows(conn, rows):
                    typer.echo(line)
        except Exception as exc:
            typer.echo(f"Error connecting to database: {exc}", err=True)
            raise typer.Exit(code=1)
        return
```

- [ ] **Step 5: Delete the bridge from the repository**

In `src/asset_manager/repository.py`, delete the `insert_records` function and its docstring. `Record` stays imported (used by `_record_from_row`).

- [ ] **Step 6: Run the full suite to verify it passes**

Run: `uv run pytest -v --no-cov`
Expected: all PASS.

- [ ] **Step 7: Lint, typecheck, commit**

```bash
uv run ruff check src tests && uv run ruff format src tests && uv run ty check src/asset_manager
git add src/asset_manager/sheets.py src/asset_manager/cli.py src/asset_manager/repository.py tests/test_sheets.py tests/test_repository.py
git commit -m "Resolve sheet rows to accounts and skip retired ones on fetch"
```

---

### Task 7: Web foundation

Shared dependency for the session user, flash messages, chart code moved out of `app.py`, the email allowlist, and the first web tests.

**Files:**
- Create: `src/asset_manager/web/rendering.py`
- Create: `src/asset_manager/web/charts.py`
- Modify: `src/asset_manager/web/auth.py`
- Modify: `src/asset_manager/web/app.py` (full rewrite)
- Modify: `src/asset_manager/web/templates/base.html`
- Modify: `src/asset_manager/web/templates/dashboard.html`
- Create: `tests/test_web.py`

**Interfaces:**
- Produces: `rendering.templates`, `rendering.render(request, name, context, status_code=200)`, `rendering.set_flash(request, kind, text)`, `rendering.pop_flash(request)`; `auth.LoginRequired`, `auth.require_user(request) -> dict`, `auth.CurrentUser` (Annotated dependency), `auth.is_email_allowed(email) -> bool`; `charts.build_chart_html(records, accounts) -> tuple[dict, dict, dict, dict]`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_web.py`:

```python
"""Web tests: real database container plus a signed session cookie."""

from datetime import date
from decimal import Decimal

import pytest
from itsdangerous import URLSafeTimedSerializer

from asset_manager.accounts import create_account
from asset_manager.models import Account, Record, RecordType
from asset_manager.repository import upsert_amounts

SECRET = "test-secret-key"
USER = {"sub": "user-1", "email": "me@example.com", "name": "Me"}


@pytest.fixture
def client(db_connection, db_url, monkeypatch):
    """A TestClient wired to the test container. db_connection handles cleanup."""
    monkeypatch.setenv("SECRET_KEY", SECRET)
    monkeypatch.setenv("DATABASE_URL", db_url)
    monkeypatch.setenv("ENV", "dev")
    monkeypatch.delenv("ALLOWED_EMAILS", raising=False)

    from fastapi.testclient import TestClient

    from asset_manager.config import get_settings
    from asset_manager.web.app import app

    get_settings.cache_clear()
    with TestClient(app) as test_client:
        yield test_client
    get_settings.cache_clear()


def login(client) -> None:
    client.cookies.set("session", URLSafeTimedSerializer(SECRET).dumps(USER))


@pytest.mark.db
class TestAuth:
    def test_dashboard_redirects_when_logged_out(self, client):
        response = client.get("/", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == "/login"

    def test_json_clients_get_401_when_logged_out(self, client):
        response = client.get("/", headers={"Accept": "application/json"})
        assert response.status_code == 401
        assert response.json() == {"error": "Login required"}


def test_is_email_allowed(monkeypatch):
    from asset_manager.web.auth import is_email_allowed

    monkeypatch.delenv("ALLOWED_EMAILS", raising=False)
    assert is_email_allowed("anyone@example.com")
    assert is_email_allowed(None)

    monkeypatch.setenv("ALLOWED_EMAILS", "Me@Example.com, other@example.com")
    assert is_email_allowed("me@example.com")
    assert is_email_allowed("OTHER@example.com")
    assert not is_email_allowed("stranger@example.com")
    assert not is_email_allowed(None)


@pytest.mark.db
class TestDashboard:
    def test_empty_state(self, client):
        login(client)
        response = client.get("/")
        assert response.status_code == 200
        assert "No data yet" in response.text

    def test_renders_with_data(self, client, db_connection):
        savings = create_account(db_connection, "Savings Account", RecordType.ASSET)
        upsert_amounts(db_connection, date(2026, 9, 1), {savings.id: Decimal("1000")})
        db_connection.commit()
        login(client)
        response = client.get("/")
        assert response.status_code == 200
        assert "Savings Account" in response.text
        assert "$1,000" in response.text


def test_build_chart_html_excludes_retired_from_breakdown():
    from asset_manager.web.charts import build_chart_html

    accounts = [
        Account(id=1, name="Live", type=RecordType.ASSET),
        Account(id=2, name="Old", type=RecordType.ASSET, retired_at=date(2026, 1, 1)),
        Account(id=3, name="Card", type=RecordType.LIABILITY),
    ]
    records = [
        Record(date=date(2026, 1, 1), account_id=1, type=RecordType.ASSET, description="Live", amount=Decimal("10")),
        Record(date=date(2026, 1, 1), account_id=2, type=RecordType.ASSET, description="Old", amount=Decimal("0")),
        Record(date=date(2026, 1, 1), account_id=3, type=RecordType.LIABILITY, description="Card", amount=Decimal("4")),
    ]
    charts, totals, assets_breakdown, liabilities_breakdown = build_chart_html(records, accounts)
    assert set(charts) == {"assets", "liabilities", "summary"}
    assert totals == {"net_worth": 6.0, "assets": 10.0, "liabilities": 4.0}
    assert assets_breakdown == {"Live": 10.0}
    assert liabilities_breakdown == {"Card": 4.0}
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_web.py -v --no-cov`
Expected: ImportError for `asset_manager.web.charts`, and `is_email_allowed`.

- [ ] **Step 3: Create rendering.py**

Create `src/asset_manager/web/rendering.py`:

```python
"""Template rendering with one-shot flash messages."""

from __future__ import annotations

from importlib import resources
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

templates_path = resources.files("asset_manager.web").joinpath("templates")
templates = Jinja2Templates(directory=str(templates_path))


def set_flash(request: Request, kind: str, text: str) -> None:
    """Queue a message for the next rendered page. kind is "success" or "error"."""
    request.session["flash"] = {"kind": kind, "text": text}


def pop_flash(request: Request) -> dict[str, str] | None:
    return request.session.pop("flash", None)


def render(
    request: Request, name: str, context: dict[str, Any], status_code: int = 200
) -> HTMLResponse:
    """Render a template with the pending flash message, if any."""
    return templates.TemplateResponse(
        request, name, {**context, "flash": pop_flash(request)}, status_code=status_code
    )
```

- [ ] **Step 4: Extend auth.py**

In `src/asset_manager/web/auth.py`:

1. Add to the imports: `from typing import Annotated, Any` (replace the existing `from typing import Any`) and `from fastapi import Depends`.
2. After `get_session_user`, add:

```python
class LoginRequired(Exception):
    """Raised by require_user when the request has no valid session."""


def require_user(request: Request) -> dict[str, Any]:
    """FastAPI dependency: the session user, or LoginRequired."""
    user = get_session_user(request)
    if not user:
        raise LoginRequired()
    return user


CurrentUser = Annotated[dict[str, Any], Depends(require_user)]


def is_email_allowed(email: str | None) -> bool:
    """True unless ALLOWED_EMAILS is set and does not list this email (case-insensitive)."""
    raw = os.environ.get("ALLOWED_EMAILS", "")
    allowed = {e.strip().lower() for e in raw.split(",") if e.strip()}
    if not allowed:
        return True
    return email is not None and email.lower() in allowed
```

3. In `handle_callback`, after `user_info` is resolved and before `user_data` is built, add:

```python
    email = user_info.get("email")
    if not is_email_allowed(email):
        raise PermissionError(f"{email} is not in ALLOWED_EMAILS")
```

- [ ] **Step 5: Create charts.py**

Create `src/asset_manager/web/charts.py` by moving `_build_chart_html` out of `app.py`, renamed and with retired accounts filtered from the breakdowns. The body is the existing function unchanged except for the marked lines:

```python
"""Plotly chart HTML for the dashboard."""

from __future__ import annotations

from asset_manager.models import Account, Record, RecordType
from asset_manager.report import _transform_data


def build_chart_html(
    records: list[Record],
    accounts: list[Account],
) -> tuple[dict[str, str], dict[str, float], dict[str, float], dict[str, float]]:
    """Build Plotly chart HTML snippets for embedding.

    Returns:
        Tuple of (charts dict, totals dict, assets_breakdown dict, liabilities_breakdown dict)
        - charts: HTML snippets for each chart
        - totals: current net_worth, assets, liabilities
        - assets_breakdown: description -> latest amount for each active asset
        - liabilities_breakdown: description -> latest amount for each active liability
    """
    import plotly.graph_objects as go

    assets_data, liabilities_data, summary_data = _transform_data(records)
    retired = {(a.type, a.name) for a in accounts if not a.is_active}

    charts = {}
    totals = {"net_worth": 0.0, "assets": 0.0, "liabilities": 0.0}

    # ... dark_layout dict exactly as in the current app.py ...

    # Extract latest value for each active asset/liability for breakdown display
    assets_breakdown = {}
    for description, series in sorted(assets_data.items()):
        if series and (RecordType.ASSET, description) not in retired:
            assets_breakdown[description] = float(series[-1][1])

    liabilities_breakdown = {}
    for description, series in sorted(liabilities_data.items()):
        if series and (RecordType.LIABILITY, description) not in retired:
            liabilities_breakdown[description] = float(series[-1][1])

    # ... the three figures and their update_layout calls exactly as in the current app.py ...

    return charts, totals, assets_breakdown, liabilities_breakdown
```

Copy the `dark_layout` dict and the three `go.Figure()` sections verbatim from the current `app.py` `_build_chart_html` (lines 74 to 213) into the marked spots.

- [ ] **Step 6: Rewrite app.py**

Replace `src/asset_manager/web/app.py` with:

```python
"""FastAPI web application for the asset dashboard."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

from asset_manager.db import get_connection_context
from asset_manager.repository import get_accounts, get_all_records

from .auth import (
    CurrentUser,
    LoginRequired,
    get_oauth,
    get_secret_key,
    handle_callback,
    handle_login,
    handle_logout,
)
from .charts import build_chart_html
from .rendering import render, templates

logger = logging.getLogger(__name__)

app = FastAPI(title="Asset Dashboard", docs_url=None, redoc_url=None)

# Session middleware for OAuth state and flash messages
app.add_middleware(
    SessionMiddleware,
    secret_key=get_secret_key(),
    session_cookie="oauth_session",
    max_age=600,  # 10 minutes for OAuth flow
)

# OAuth client (lazy initialization)
_oauth = None


def get_oauth_client():
    """Get or create the OAuth client."""
    global _oauth
    if _oauth is None:
        _oauth = get_oauth()
    return _oauth


@app.exception_handler(LoginRequired)
async def login_required_handler(request: Request, exc: LoginRequired):
    """Pages redirect to login; JSON clients get a 401."""
    if "application/json" in request.headers.get("accept", ""):
        return JSONResponse({"error": "Login required"}, status_code=401)
    return RedirectResponse(url="/login", status_code=302)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, user: CurrentUser):
    """Render the main dashboard."""
    try:
        with get_connection_context() as conn:
            records = get_all_records(conn)
            accounts = get_accounts(conn)
    except Exception:
        logger.exception("Database error in dashboard")
        return render(
            request,
            "dashboard.html",
            {
                "user": user,
                "active_tab": "dashboard",
                "error": "An error occurred while loading your data. Please try again later.",
                "charts": {},
            },
        )

    if records:
        charts, totals, assets_breakdown, liabilities_breakdown = build_chart_html(
            records, accounts
        )
    else:
        charts, totals = {}, {"net_worth": 0.0, "assets": 0.0, "liabilities": 0.0}
        assets_breakdown, liabilities_breakdown = {}, {}

    return render(
        request,
        "dashboard.html",
        {
            "user": user,
            "active_tab": "dashboard",
            "charts": charts,
            "totals": totals,
            "assets_breakdown": assets_breakdown,
            "liabilities_breakdown": liabilities_breakdown,
            "record_count": len(records),
        },
    )


@app.get("/login", response_class=HTMLResponse)
async def login(request: Request):
    """Show the login page."""
    return templates.TemplateResponse(request, "login.html")


@app.get("/auth/start")
async def auth_start(request: Request):
    """Redirect to the IDP for authentication."""
    oauth = get_oauth_client()
    return await handle_login(request, oauth)


@app.get("/auth/callback")
async def auth_callback(request: Request):
    """Handle the OAuth callback."""
    oauth = get_oauth_client()
    try:
        return await handle_callback(request, oauth)
    except PermissionError:
        logger.warning("Login refused: email not in ALLOWED_EMAILS")
        return HTMLResponse("Your account is not authorized to use this app.", status_code=403)
    except Exception as e:
        logger.exception("OAuth callback failed: %s", e)
        return HTMLResponse("Authentication failed. Please try again.", status_code=400)


@app.get("/logout")
async def logout():
    """Log out and clear the session."""
    return handle_logout()


@app.get("/health")
async def health():
    """Health check endpoint."""
    return JSONResponse(
        content={"status": "ok"},
        headers={"Access-Control-Allow-Origin": "*"},
    )
```

The `/accounts` route is gone from `app.py` for now; Task 8 adds it back through a router. The dashboard tests in this task do not touch it.

- [ ] **Step 7: Add flash rendering to base.html**

In `src/asset_manager/web/templates/base.html`:

1. After the `.error { ... }` CSS block, add:

```css
        .flash {
            padding: 0.85rem 1.25rem;
            border-radius: var(--radius);
            margin-bottom: 1.25rem;
            font-size: 0.9rem;
            border: 1px solid;
        }

        .flash-error {
            background-color: var(--color-liability-dim);
            border-color: rgba(199, 92, 92, 0.3);
            color: #e08888;
        }

        .flash-success {
            background-color: var(--color-asset-dim);
            border-color: rgba(106, 173, 122, 0.3);
            color: #8fcb9c;
        }

        .no-data a {
            color: var(--accent-gold);
        }
```

2. In the `.container` div, after the `{% if error %}...{% endif %}` block, add:

```html
        {% if flash %}
        <div class="flash flash-{{ flash.kind }}">{{ flash.text }}</div>
        {% endif %}
```

- [ ] **Step 8: Update the dashboard empty state**

In `src/asset_manager/web/templates/dashboard.html`, replace the `.no-data` paragraph with:

```html
        <p>No data yet. <a href="/accounts">Add accounts</a> and save a snapshot to see charts.</p>
```

- [ ] **Step 9: Run the tests to verify they pass**

Run: `uv run pytest tests/test_web.py -v --no-cov`
Expected: all PASS.

Run: `uv run pytest -v --no-cov`
Expected: all PASS.

- [ ] **Step 10: Lint, typecheck, commit**

```bash
uv run ruff check src tests && uv run ruff format src tests && uv run ty check src/asset_manager
git add src/asset_manager/web tests/test_web.py
git commit -m "Add require_user dependency, flash messages, and chart module"
```

---

### Task 8: Editable accounts page and Save

**Files:**
- Create: `src/asset_manager/web/accounts_routes.py`
- Modify: `src/asset_manager/web/app.py` (include the router)
- Modify: `src/asset_manager/web/templates/accounts.html` (full rewrite)
- Modify: `tests/test_web.py` (append)

**Interfaces:**
- Consumes: `CurrentUser`, `render` from Task 7; service functions from Task 5; repository from Tasks 3 and 4.
- Produces: `router`, `format_percent(rate) -> str`, `format_amount(amount | None) -> str`, `account_rows(accounts, latest) -> list[dict]`, `SnapshotPayload`, `GET /accounts`, `POST /snapshots`.

- [ ] **Step 1: Write the failing tests**

In `tests/test_web.py`, change the accounts import to
`from asset_manager.accounts import create_account, retire_account`, then append:

```python
def test_format_percent():
    from asset_manager.web.accounts_routes import format_percent

    assert format_percent(Decimal("0.15")) == "15"
    assert format_percent(Decimal("0.325")) == "32.5"
    assert format_percent(Decimal("0")) == "0"
    assert format_percent(Decimal("1")) == "100"


def test_account_rows_view_model():
    from asset_manager.models import ProportionalFormula
    from asset_manager.web.accounts_routes import account_rows

    schwab = Account(id=1, name="Schwab", type=RecordType.ASSET)
    tax = Account(
        id=2, name="Cap Gains Tax", type=RecordType.LIABILITY,
        formula=ProportionalFormula(rate=Decimal("0.15"), cost_basis=Decimal("70634")),
        input_ids=[1],
    )
    old = Account(id=3, name="Old", type=RecordType.ASSET, retired_at=date(2026, 1, 1))
    latest = [
        Record(date=date(2026, 9, 1), account_id=1, type=RecordType.ASSET, description="Schwab", amount=Decimal("163202.77")),
        Record(date=date(2026, 9, 1), account_id=2, type=RecordType.LIABILITY, description="Cap Gains Tax", amount=Decimal("13885.32")),
    ]

    rows = account_rows([schwab, tax, old], latest)

    assert rows[0] == {
        "id": 1, "name": "Schwab", "type": "asset", "computed": False, "formula": None,
        "input_ids": [], "amount": "163202.77", "amount_display": "163,202.77",
        "basis_display": "", "retired": False, "retired_at": None, "formula_text": "",
    }
    assert rows[1]["computed"] is True
    assert rows[1]["formula"] == {"kind": "proportional", "rate": "0.15", "cost_basis": "70634"}
    assert rows[1]["basis_display"] == "70,634.00"
    assert rows[1]["formula_text"] == "15% × (Schwab − basis)"
    assert rows[2]["retired"] is True
    assert rows[2]["retired_at"] == "2026-01-01"
    assert rows[2]["amount"] is None
    assert rows[2]["amount_display"] == ""


@pytest.mark.db
class TestAccountsPage:
    def test_empty_state(self, client):
        login(client)
        response = client.get("/accounts")
        assert response.status_code == 200
        assert "No accounts yet" in response.text

    def test_renders_rows_and_embeds_json(self, client, db_connection):
        from asset_manager.models import ProportionalFormula

        schwab = create_account(db_connection, "Schwab Trading", RecordType.ASSET)
        create_account(
            db_connection, "Cap Gains Tax", RecordType.LIABILITY,
            ProportionalFormula(rate=Decimal("0.15"), cost_basis=Decimal("100")), [schwab.id],
        )
        old = create_account(db_connection, "Old 401k", RecordType.ASSET)
        retire_account(db_connection, old.id, date(2026, 1, 1))
        upsert_amounts(db_connection, date(2026, 9, 1), {schwab.id: Decimal("1000")})
        db_connection.commit()
        login(client)

        response = client.get("/accounts")

        assert response.status_code == 200
        text = response.text
        assert 'id="accounts-data"' in text
        assert 'value="1,000.00"' in text
        assert "Cap Gains Tax" in text
        assert "Show retired (1)" in text
        assert "September 1, 2026" in text
        assert f'href="/accounts/{schwab.id}/edit"' in text

    def test_redirects_when_logged_out(self, client):
        response = client.get("/accounts", follow_redirects=False)
        assert response.status_code == 302


@pytest.mark.db
class TestSaveSnapshot:
    def test_writes_computed_rows(self, client, db_connection):
        from asset_manager.models import ProportionalFormula
        from asset_manager.repository import get_all_records

        schwab = create_account(db_connection, "Schwab", RecordType.ASSET)
        tax = create_account(
            db_connection, "Tax", RecordType.LIABILITY,
            ProportionalFormula(rate=Decimal("0.15"), cost_basis=Decimal("100")), [schwab.id],
        )
        login(client)

        response = client.post(
            "/snapshots",
            json={"values": {str(schwab.id): "1000.00"}, "cost_bases": {str(tax.id): "400.00"}},
            headers={"Accept": "application/json"},
        )

        assert response.status_code == 200
        assert response.json() == {"date": date.today().isoformat(), "count": 2}
        rows = {(r.description, r.amount) for r in get_all_records(db_connection)}
        assert rows == {("Schwab", Decimal("1000.00")), ("Tax", Decimal("90.00"))}

    def test_missing_value_returns_400_and_writes_nothing(self, client, db_connection):
        from asset_manager.repository import get_all_records

        create_account(db_connection, "Schwab", RecordType.ASSET)
        create_account(db_connection, "Cash", RecordType.ASSET)
        login(client)

        response = client.post("/snapshots", json={"values": {}, "cost_bases": {}})

        assert response.status_code == 400
        assert "Missing value for" in response.json()["error"]
        assert get_all_records(db_connection) == []

    def test_requires_login(self, client):
        response = client.post("/snapshots", json={"values": {}}, headers={"Accept": "application/json"})
        assert response.status_code == 401
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_web.py -v --no-cov`
Expected: ImportError for `asset_manager.web.accounts_routes`; the page tests get 404.

- [ ] **Step 3: Create the router with the page and Save routes**

Create `src/asset_manager/web/accounts_routes.py`:

```python
"""Routes for the editable accounts page, the account form, and Save."""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from asset_manager.accounts import AccountError, save_snapshot
from asset_manager.db import get_connection_context
from asset_manager.models import Account, Record
from asset_manager.repository import get_accounts, get_latest_snapshot_records

from .auth import CurrentUser
from .rendering import render

logger = logging.getLogger(__name__)
router = APIRouter()


# --- view helpers ----------------------------------------------------------


def format_percent(rate: Decimal) -> str:
    """0.15 -> "15", 0.325 -> "32.5"."""
    text = f"{rate * 100:f}"
    return text.rstrip("0").rstrip(".") if "." in text else text


def format_amount(amount: Decimal | None) -> str:
    return "" if amount is None else f"{amount:,.2f}"


def formula_text(account: Account, by_id: dict[int, Account]) -> str:
    """Human-readable formula, e.g. "15% × (Schwab + Fidelity − basis)"."""
    formula = account.formula
    if formula is None:
        return ""
    names = [by_id[i].name if i in by_id else f"account {i}" for i in account.input_ids]
    return f"{format_percent(formula.rate)}% × ({' + '.join(names)} − basis)"


def account_rows(accounts: list[Account], latest: list[Record]) -> list[dict[str, Any]]:
    """JSON-safe view model for the accounts page, one dict per account.

    `amount` is the account's value on the latest snapshot date, or None if it
    has no row on that date (new, just unretired, or dropped from the sheet).
    """
    by_id = {a.id: a for a in accounts if a.id is not None}
    amounts = {r.account_id: r.amount for r in latest}
    rows = []
    for account in accounts:
        amount = amounts.get(account.id)
        formula = account.formula
        rows.append(
            {
                "id": account.id,
                "name": account.name,
                "type": account.type.value,
                "computed": account.is_computed,
                "formula": formula.model_dump(mode="json") if formula else None,
                "input_ids": list(account.input_ids),
                "amount": None if amount is None else str(amount),
                "amount_display": format_amount(amount),
                "basis_display": format_amount(formula.cost_basis) if formula else "",
                "retired": not account.is_active,
                "retired_at": account.retired_at.isoformat() if account.retired_at else None,
                "formula_text": formula_text(account, by_id),
            }
        )
    return rows


# --- page ------------------------------------------------------------------


@router.get("/accounts", response_class=HTMLResponse)
async def accounts_page(request: Request, user: CurrentUser):
    """Render the editable accounts page."""
    try:
        with get_connection_context() as conn:
            accounts = get_accounts(conn)
            latest = get_latest_snapshot_records(conn)
    except Exception:
        logger.exception("Database error in accounts")
        return render(
            request,
            "accounts.html",
            {
                "user": user,
                "active_tab": "accounts",
                "error": "An error occurred while loading your data. Please try again later.",
                "rows": [],
            },
        )

    rows = account_rows(accounts, latest)
    # Active rows first, retired rows last, id order within each group
    rows.sort(key=lambda r: (r["retired"], r["id"]))
    return render(
        request,
        "accounts.html",
        {
            "user": user,
            "active_tab": "accounts",
            "rows": rows,
            "assets": [r for r in rows if r["type"] == "asset"],
            "liabilities": [r for r in rows if r["type"] == "liability"],
            "retired_count": sum(1 for r in rows if r["retired"]),
            "snapshot_date": latest[0].date if latest else None,
        },
    )


# --- save ------------------------------------------------------------------


class SnapshotPayload(BaseModel):
    values: dict[int, Decimal] = Field(default_factory=dict)
    cost_bases: dict[int, Decimal] = Field(default_factory=dict)


@router.post("/snapshots")
async def save_snapshot_route(payload: SnapshotPayload, user: CurrentUser) -> JSONResponse:
    """Write a complete snapshot for today from the page's staged values."""
    today = date.today()
    try:
        with get_connection_context() as conn:
            count = save_snapshot(conn, payload.values, payload.cost_bases, today)
    except AccountError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return JSONResponse({"date": today.isoformat(), "count": count})
```

- [ ] **Step 4: Include the router in app.py**

In `src/asset_manager/web/app.py`, add `from .accounts_routes import router as accounts_router` to the relative imports, and after the `app.add_middleware(...)` call add:

```python
app.include_router(accounts_router)
```

- [ ] **Step 5: Rewrite accounts.html**

Replace `src/asset_manager/web/templates/accounts.html` with:

```html
{% extends "base.html" %}

{% block styles %}
    .page-top {
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        margin-bottom: 1.25rem;
    }

    .snapshot-date {
        color: var(--text-muted);
        font-size: 0.8rem;
        font-weight: 500;
        letter-spacing: 0.06em;
        text-transform: uppercase;
    }

    .snapshot-date span {
        color: var(--text-secondary);
    }

    .toggle-retired {
        color: var(--text-muted);
        font-size: 0.8rem;
        cursor: pointer;
        user-select: none;
    }

    .toggle-retired input {
        margin-right: 0.4rem;
        accent-color: var(--accent-gold);
    }

    .accounts-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 1.5rem;
        margin-bottom: 1.5rem;
    }

    .account-table-wrapper {
        background-color: var(--bg-surface);
        border: 1px solid var(--border-subtle);
        border-radius: var(--radius);
        overflow: hidden;
    }

    .table-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 0.85rem 1.25rem;
        border-bottom: 1px solid var(--border-subtle);
    }

    .table-header h2 {
        font-family: var(--font-display);
        font-size: 1.05rem;
        font-weight: 400;
        letter-spacing: 0.01em;
    }

    .table-header.asset h2 {
        color: var(--color-asset);
    }

    .table-header.liability h2 {
        color: var(--color-liability);
    }

    .table-actions .btn {
        padding: 0.25rem 0.6rem;
        font-size: 0.7rem;
    }

    .accounts-table {
        width: 100%;
        border-collapse: collapse;
    }

    .accounts-table th {
        text-align: left;
        padding: 0.55rem 1.25rem;
        font-size: 0.7rem;
        font-weight: 600;
        color: var(--text-muted);
        text-transform: uppercase;
        letter-spacing: 0.08em;
        border-bottom: 1px solid var(--border-subtle);
    }

    .accounts-table th.amount-col {
        text-align: right;
    }

    .accounts-table td {
        padding: 0.55rem 1.25rem;
        font-size: 0.9rem;
        border-bottom: 1px solid rgba(46, 51, 64, 0.5);
        vertical-align: top;
    }

    .accounts-table tbody tr {
        transition: background-color 0.15s ease;
    }

    .accounts-table tbody tr:hover:not(.totals-row) {
        background-color: var(--bg-surface-hover);
    }

    .account-name {
        color: var(--text-secondary);
        text-decoration: none;
        border-bottom: 1px dotted transparent;
        transition: color 0.15s, border-color 0.15s;
    }

    .account-name:hover {
        color: var(--text-primary);
        border-bottom-color: var(--text-muted);
    }

    .formula-badge {
        display: inline-block;
        margin-left: 0.5rem;
        padding: 0 0.4rem;
        border-radius: 3px;
        background: var(--accent-gold-dim);
        color: var(--accent-gold);
        font-family: var(--font-mono);
        font-size: 0.7rem;
        cursor: help;
    }

    .basis-field {
        display: block;
        margin-top: 0.2rem;
        color: var(--text-muted);
        font-size: 0.75rem;
        font-family: var(--font-mono);
    }

    .amount-cell {
        text-align: right;
        font-family: var(--font-mono);
        font-size: 0.85rem;
        font-variant-numeric: tabular-nums;
    }

    .amount-cell input,
    .basis-field input {
        background: transparent;
        border: none;
        border-bottom: 1px solid var(--border-medium);
        color: var(--text-primary);
        font-family: var(--font-mono);
        font-size: 0.85rem;
        text-align: right;
        padding: 0.1rem 0.2rem;
        width: 9rem;
        font-variant-numeric: tabular-nums;
        outline: none;
        transition: border-color 0.15s;
    }

    .basis-field input {
        width: 7.5rem;
        font-size: 0.75rem;
    }

    .amount-cell input:focus,
    .basis-field input:focus,
    .amount-cell input.dirty,
    .basis-field input.dirty {
        border-bottom-color: var(--accent-gold);
    }

    .amount-cell input.invalid,
    .basis-field input.invalid {
        border-bottom-color: var(--color-liability);
        color: #e08888;
    }

    .computed-amount {
        color: var(--text-primary);
    }

    .retired-note {
        color: var(--text-muted);
        font-size: 0.75rem;
    }

    .retired-row {
        display: none;
    }

    body.show-retired .retired-row {
        display: table-row;
    }

    .retired-row .account-name {
        color: var(--text-muted);
        text-decoration: line-through;
    }

    .accounts-table .totals-row td {
        font-weight: 600;
        border-top: 1px solid var(--border-medium);
        border-bottom: none;
        padding-top: 0.7rem;
        padding-bottom: 0.7rem;
        color: var(--text-primary);
        font-size: 0.9rem;
    }

    .net-worth-summary {
        background-color: var(--bg-surface);
        border: 1px solid var(--border-subtle);
        border-radius: var(--radius);
        padding: 1rem 1.25rem;
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        position: relative;
        overflow: hidden;
    }

    .net-worth-summary::before {
        content: '';
        position: absolute;
        left: 0;
        top: 0;
        bottom: 0;
        width: 3px;
        background: var(--accent-gold);
    }

    .net-worth-summary .label {
        font-family: var(--font-display);
        font-size: 1.05rem;
        font-weight: 400;
        color: var(--text-secondary);
    }

    .net-worth-summary .value {
        font-family: var(--font-mono);
        font-size: 1.35rem;
        font-weight: 600;
        color: var(--accent-gold);
        letter-spacing: -0.02em;
    }

    .save-bar {
        position: sticky;
        bottom: 0;
        margin-top: 1.5rem;
        padding: 0.85rem 1.25rem;
        background: var(--bg-primary);
        border: 1px solid var(--border-subtle);
        border-radius: var(--radius);
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 1rem;
        box-shadow: var(--shadow);
    }

    .save-bar .status {
        color: var(--text-muted);
        font-size: 0.85rem;
    }

    .save-bar .status.dirty {
        color: var(--accent-gold);
    }

    .save-bar .actions {
        display: flex;
        gap: 0.75rem;
    }

    .btn:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }

    .accounts-table tbody tr {
        animation: fadeUp 0.3s ease-out both;
    }

    {% for i in range(20) %}
    .accounts-table tbody tr:nth-child({{ i + 1 }}) {
        animation-delay: {{ 0.03 * i }}s;
    }
    {% endfor %}

    @media (max-width: 768px) {
        .accounts-grid {
            grid-template-columns: 1fr;
        }
    }
{% endblock %}

{% block content %}
    {% if rows %}
    <div class="page-top fade-in">
        <div class="snapshot-date">
            {% if snapshot_date %}
            Snapshot <span>{{ snapshot_date.strftime('%B %-d, %Y') }}</span>
            {% else %}
            No snapshot saved yet
            {% endif %}
        </div>
        {% if retired_count %}
        <label class="toggle-retired">
            <input type="checkbox" id="show-retired"> Show retired ({{ retired_count }})
        </label>
        {% endif %}
    </div>

    <div id="save-error" class="error" hidden></div>

    <div class="accounts-grid fade-in" style="animation-delay: 0.05s">
        {% for kind, title, section_rows in [('asset', 'Assets', assets), ('liability', 'Liabilities', liabilities)] %}
        <div class="account-table-wrapper">
            <div class="table-header {{ kind }}">
                <h2>{{ title }}</h2>
                <div class="table-actions">
                    <a class="btn btn-secondary" href="/accounts/new?type={{ kind }}">+ Add</a>
                </div>
            </div>
            <table class="accounts-table">
                <thead>
                    <tr>
                        <th>Description</th>
                        <th class="amount-col">Amount</th>
                    </tr>
                </thead>
                <tbody>
                    {% for row in section_rows %}
                    <tr data-account-id="{{ row.id }}" class="{% if row.retired %}retired-row{% endif %}">
                        <td>
                            <a class="account-name" href="/accounts/{{ row.id }}/edit">{{ row.name }}</a>
                            {% if row.computed %}
                            <span class="formula-badge" title="{{ row.formula_text }}">ƒ</span>
                            {% if not row.retired %}
                            <span class="basis-field">basis $
                                <input class="basis-input" data-field="basis" data-account-id="{{ row.id }}"
                                       value="{{ row.basis_display }}" inputmode="decimal"
                                       aria-label="Cost basis for {{ row.name }}">
                            </span>
                            {% endif %}
                            {% endif %}
                        </td>
                        <td class="amount-cell">
                            {% if row.retired %}
                            <span class="retired-note">retired {{ row.retired_at }}</span>
                            {% elif row.computed %}
                            <span class="computed-amount" data-account-id="{{ row.id }}">—</span>
                            {% else %}
                            <input class="amount-input" data-field="amount" data-account-id="{{ row.id }}"
                                   value="{{ row.amount_display }}" inputmode="decimal" placeholder="0.00"
                                   aria-label="Amount for {{ row.name }}">
                            {% endif %}
                        </td>
                    </tr>
                    {% endfor %}
                    <tr class="totals-row">
                        <td>Total</td>
                        <td class="amount-cell" id="total-{{ kind }}">—</td>
                    </tr>
                </tbody>
            </table>
        </div>
        {% endfor %}
    </div>

    <div class="net-worth-summary fade-in" style="animation-delay: 0.15s">
        <span class="label">Net Worth</span>
        <span class="value" id="net-worth">—</span>
    </div>

    <div class="save-bar fade-in" style="animation-delay: 0.2s">
        <span class="status" id="dirty-status">No unsaved changes</span>
        <div class="actions">
            <button type="button" class="btn btn-secondary" id="discard-button">Discard</button>
            <button type="button" class="btn btn-primary" id="save-button">Save snapshot</button>
        </div>
    </div>
    {% else %}
    <div class="no-data">
        <p>No accounts yet. <a href="/accounts/new?type=asset">Add an asset</a> to get started.</p>
    </div>
    {% endif %}
{% endblock %}

{% block scripts %}
{% if rows %}
<script id="accounts-data" type="application/json">{{ rows | tojson }}</script>
<script>
(function () {
    const rows = JSON.parse(document.getElementById('accounts-data').textContent);
    const active = rows.filter(r => !r.retired);
    const STORAGE_KEY = 'asset-manager:staged-edits';

    const amountInputs = Array.from(document.querySelectorAll('.amount-input'));
    const basisInputs = Array.from(document.querySelectorAll('.basis-input'));
    const allInputs = amountInputs.concat(basisInputs);
    const initial = new Map(allInputs.map(el => [el, el.value]));

    // --- parsing and formatting -------------------------------------------
    function parseAmount(text) {
        let s = String(text).replace(/[$,\s]/g, '');
        if (s === '') return null;
        let negative = false;
        if (s.startsWith('(') && s.endsWith(')')) { negative = true; s = s.slice(1, -1); }
        if (!/^-?(\d+\.?\d*|\.\d+)$/.test(s)) return NaN;
        const n = Number(s);
        return negative ? -n : n;
    }
    function usable(n) { return n !== null && n !== undefined && !Number.isNaN(n); }
    // Round half away from zero, matching Python's ROUND_HALF_UP on the server.
    function roundCents(n) { return Math.sign(n) * Math.round(Math.abs(n) * 100 + 1e-9) / 100; }
    function fmt(n) {
        return Math.abs(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    }
    function fmtMoney(n) { return (n < 0 ? '-$' : '$') + fmt(n); }
    function normalized(text) {
        const n = parseAmount(text);
        return usable(n) ? roundCents(n).toFixed(2) : String(text).trim();
    }
    function isDirty(el) { return normalized(el.value) !== normalized(initial.get(el)); }
    function key(el) { return el.dataset.field + ':' + el.dataset.accountId; }

    // --- recompute ---------------------------------------------------------
    function readInputs(list) {
        const out = {};
        list.forEach(el => {
            const n = parseAmount(el.value);
            el.classList.toggle('invalid', Number.isNaN(n));
            el.classList.toggle('dirty', isDirty(el));
            out[el.dataset.accountId] = n;
        });
        return out;
    }

    function recompute() {
        const values = readInputs(amountInputs);
        const bases = readInputs(basisInputs);
        const totals = { asset: 0, liability: 0 };
        active.forEach(row => {
            let amount = null;
            if (row.computed) {
                const inputs = row.input_ids.map(id => values[id]);
                const basis = bases[row.id];
                if (inputs.every(usable) && usable(basis)) {
                    const sum = inputs.reduce((s, v) => s + v, 0);
                    amount = roundCents(Number(row.formula.rate) * (sum - basis));
                }
                const el = document.querySelector('.computed-amount[data-account-id="' + row.id + '"]');
                if (el) el.textContent = amount === null ? '—' : fmtMoney(amount);
            } else if (usable(values[row.id])) {
                amount = values[row.id];
            }
            if (amount !== null) totals[row.type] += amount;
        });
        document.getElementById('total-asset').textContent = fmtMoney(totals.asset);
        document.getElementById('total-liability').textContent = fmtMoney(totals.liability);
        document.getElementById('net-worth').textContent = fmtMoney(totals.asset - totals.liability);

        const dirtyCount = allInputs.filter(isDirty).length;
        const status = document.getElementById('dirty-status');
        status.textContent = dirtyCount === 0
            ? 'No unsaved changes'
            : dirtyCount + ' unsaved change' + (dirtyCount === 1 ? '' : 's');
        status.classList.toggle('dirty', dirtyCount > 0);
    }

    // --- staged edits survive page reloads (add/edit account round trips) --
    function persist() {
        try {
            const staged = {};
            allInputs.forEach(el => { if (isDirty(el)) staged[key(el)] = el.value; });
            sessionStorage.setItem(STORAGE_KEY, JSON.stringify(staged));
        } catch (e) { /* storage unavailable; edits still live in the page */ }
    }
    function restore() {
        try {
            const staged = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || '{}');
            allInputs.forEach(el => { if (key(el) in staged) el.value = staged[key(el)]; });
        } catch (e) { /* ignore */ }
    }
    function clearStaged() {
        try { sessionStorage.removeItem(STORAGE_KEY); } catch (e) { /* ignore */ }
    }

    // --- save / discard ----------------------------------------------------
    function showError(text) {
        const box = document.getElementById('save-error');
        box.textContent = text;
        box.hidden = !text;
    }

    function collect(list, target, payload) {
        let problem = null;
        list.forEach(el => {
            const n = parseAmount(el.value);
            if (!usable(n)) {
                el.classList.add('invalid');
                problem = problem || el;
            } else {
                payload[target][el.dataset.accountId] = roundCents(n).toFixed(2);
            }
        });
        return problem;
    }

    async function save() {
        showError('');
        const payload = { values: {}, cost_bases: {} };
        const problem = collect(amountInputs, 'values', payload) || collect(basisInputs, 'cost_bases', payload);
        if (problem) {
            showError('Every account needs an amount before saving.');
            problem.focus();
            return;
        }
        const button = document.getElementById('save-button');
        button.disabled = true;
        try {
            const res = await fetch('/snapshots', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
                body: JSON.stringify(payload),
            });
            if (res.status === 401) { window.location.href = '/login'; return; }
            const body = await res.json().catch(() => ({}));
            if (!res.ok) { showError(body.error || ('Save failed (' + res.status + ')')); return; }
            clearStaged();
            window.location.reload();
        } catch (e) {
            showError('Save failed: ' + e.message);
        } finally {
            button.disabled = false;
        }
    }

    function discard() {
        clearStaged();
        allInputs.forEach(el => { el.value = initial.get(el); });
        showError('');
        recompute();
    }

    // --- wiring ------------------------------------------------------------
    allInputs.forEach(el => {
        el.addEventListener('input', () => { persist(); recompute(); });
        el.addEventListener('blur', () => {
            const n = parseAmount(el.value);
            if (usable(n)) { el.value = (n < 0 ? '-' : '') + fmt(n); recompute(); }
        });
    });
    document.getElementById('save-button').addEventListener('click', save);
    document.getElementById('discard-button').addEventListener('click', discard);
    const toggle = document.getElementById('show-retired');
    if (toggle) {
        toggle.addEventListener('change', () => document.body.classList.toggle('show-retired', toggle.checked));
    }

    restore();
    recompute();
})();
</script>
{% endif %}
{% endblock %}
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_web.py -v --no-cov`
Expected: all PASS.

- [ ] **Step 7: Check the page by eye**

Run: `ENV=dev uv run asset-manager serve` and open `http://127.0.0.1:8000/accounts` (needs the staging database migrated, see Task 10, or a local database with the migrations applied and some accounts). Confirm: typing in an amount updates totals and the unsaved count; a computed row recomputes when its input or basis changes; blur reformats with commas; reloading the page keeps typed values; Save reloads with the new snapshot date; Discard resets.

- [ ] **Step 8: Lint, typecheck, commit**

```bash
uv run ruff check src tests && uv run ruff format src tests && uv run ty check src/asset_manager
git add src/asset_manager/web tests/test_web.py
git commit -m "Make the accounts page editable with live formulas and Save"
```

---

### Task 9: Account form: create, edit, retire, unretire

**Files:**
- Modify: `src/asset_manager/web/accounts_routes.py` (append)
- Create: `src/asset_manager/web/templates/account_form.html`
- Modify: `tests/test_web.py` (append)

**Interfaces:**
- Consumes: `create_account`, `update_account`, `retire_account`, `unretire_account`, `retire_blocker`, `parse_amount` from Task 5; `set_flash` from Task 7.
- Produces: `GET /accounts/new`, `GET /accounts/{id}/edit`, `POST /accounts`, `POST /accounts/{id}`, `POST /accounts/{id}/retire`, `POST /accounts/{id}/unretire`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_web.py`:

```python
@pytest.mark.db
class TestAccountForm:
    def test_new_page_presets_type_and_lists_inputs(self, client, db_connection):
        create_account(db_connection, "Schwab", RecordType.ASSET)
        login(client)
        response = client.get("/accounts/new?type=liability")
        assert response.status_code == 200
        assert "New liability" in response.text
        assert 'name="input_ids"' in response.text
        assert "Schwab" in response.text

    def test_create_plain_account_redirects_with_flash(self, client, db_connection):
        from asset_manager.repository import get_accounts

        login(client)
        response = client.post(
            "/accounts", data={"name": "Cash", "type": "asset"}, follow_redirects=False
        )
        assert response.status_code == 303
        assert response.headers["location"] == "/accounts"
        assert [a.name for a in get_accounts(db_connection)] == ["Cash"]
        page = client.get("/accounts")
        assert "Added Cash" in page.text

    def test_create_computed_account(self, client, db_connection):
        from asset_manager.repository import get_accounts

        schwab = create_account(db_connection, "Schwab", RecordType.ASSET)
        login(client)
        response = client.post(
            "/accounts",
            data={
                "name": "Cap Gains Tax", "type": "liability", "computed": "on",
                "rate_percent": "15", "cost_basis": "$70,634.00", "input_ids": [str(schwab.id)],
            },
            follow_redirects=False,
        )
        assert response.status_code == 303
        tax = [a for a in get_accounts(db_connection) if a.name == "Cap Gains Tax"][0]
        assert tax.formula is not None
        assert tax.formula.rate == Decimal("0.15")
        assert tax.formula.cost_basis == Decimal("70634.00")
        assert tax.input_ids == [schwab.id]

    def test_create_duplicate_rerenders_with_error(self, client, db_connection):
        create_account(db_connection, "Cash", RecordType.ASSET)
        login(client)
        response = client.post("/accounts", data={"name": "Cash", "type": "asset"})
        assert response.status_code == 400
        assert "already exists" in response.text
        assert 'value="Cash"' in response.text

    def test_create_bad_rate_rerenders_with_error(self, client):
        login(client)
        response = client.post(
            "/accounts",
            data={"name": "Tax", "type": "liability", "computed": "on", "rate_percent": "abc"},
        )
        assert response.status_code == 400
        assert "Rate must be a number" in response.text

    def test_edit_page_prefills_formula(self, client, db_connection):
        from asset_manager.models import ProportionalFormula

        schwab = create_account(db_connection, "Schwab", RecordType.ASSET)
        tax = create_account(
            db_connection, "Tax", RecordType.LIABILITY,
            ProportionalFormula(rate=Decimal("0.325"), cost_basis=Decimal("100")), [schwab.id],
        )
        login(client)
        response = client.get(f"/accounts/{tax.id}/edit")
        assert response.status_code == 200
        assert "Edit liability" in response.text
        assert 'value="32.5"' in response.text
        assert 'value="100.00"' in response.text
        assert f'value="{schwab.id}" checked' in response.text
        assert "cannot be changed" in response.text

    def test_edit_page_404_for_unknown(self, client):
        login(client)
        assert client.get("/accounts/9999/edit").status_code == 404

    def test_update_account(self, client, db_connection):
        from asset_manager.repository import get_account

        cash = create_account(db_connection, "Cash", RecordType.ASSET)
        login(client)
        response = client.post(
            f"/accounts/{cash.id}", data={"name": "Cash (SoFi)"}, follow_redirects=False
        )
        assert response.status_code == 303
        loaded = get_account(db_connection, cash.id)
        assert loaded is not None and loaded.name == "Cash (SoFi)"

    def test_retire_blocked_shows_flash(self, client, db_connection):
        cash = create_account(db_connection, "Cash", RecordType.ASSET)
        upsert_amounts(db_connection, date(2026, 9, 1), {cash.id: Decimal("5")})
        db_connection.commit()
        login(client)
        response = client.post(f"/accounts/{cash.id}/retire", follow_redirects=False)
        assert response.status_code == 303
        page = client.get("/accounts")
        assert "Set it to zero and save before retiring" in page.text
        edit = client.get(f"/accounts/{cash.id}/edit")
        assert "Set it to zero and save before retiring" in edit.text

    def test_retire_and_unretire(self, client, db_connection):
        from asset_manager.repository import get_account

        cash = create_account(db_connection, "Cash", RecordType.ASSET)
        login(client)
        client.post(f"/accounts/{cash.id}/retire", follow_redirects=False)
        loaded = get_account(db_connection, cash.id)
        assert loaded is not None and loaded.retired_at == date.today()
        assert "Retired Cash" in client.get("/accounts").text

        client.post(f"/accounts/{cash.id}/unretire", follow_redirects=False)
        loaded = get_account(db_connection, cash.id)
        assert loaded is not None and loaded.retired_at is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_web.py::TestAccountForm -v --no-cov`
Expected: 404s and assertion failures.

- [ ] **Step 3: Append the form routes**

In `src/asset_manager/web/accounts_routes.py`:

1. Extend the imports:

```python
from decimal import Decimal, InvalidOperation
from typing import Annotated, Any

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from asset_manager.accounts import (
    AccountError,
    create_account,
    parse_amount,
    retire_account,
    retire_blocker,
    save_snapshot,
    unretire_account,
    update_account,
)
from asset_manager.models import Account, ProportionalFormula, Record, RecordType
from asset_manager.repository import get_account, get_accounts, get_latest_snapshot_records

from .rendering import render, set_flash
```

2. Append:

```python
# --- account form ----------------------------------------------------------


def _form_defaults(type_: str) -> dict[str, Any]:
    return {
        "name": "",
        "type": type_,
        "computed": False,
        "rate_percent": "",
        "cost_basis": "",
        "input_ids": [],
    }


def _form_from_account(account: Account) -> dict[str, Any]:
    formula = account.formula
    return {
        "name": account.name,
        "type": account.type.value,
        "computed": formula is not None,
        "rate_percent": format_percent(formula.rate) if formula else "",
        "cost_basis": format_amount(formula.cost_basis) if formula else "",
        "input_ids": list(account.input_ids),
    }


def _candidates(accounts: list[Account], exclude_id: int | None) -> list[Account]:
    """Accounts eligible as formula inputs: active, plain, not the account itself."""
    return [a for a in accounts if a.is_active and not a.is_computed and a.id != exclude_id]


def _parse_formula(computed: bool, rate_percent: str, cost_basis: str) -> ProportionalFormula | None:
    if not computed:
        return None
    try:
        rate = (Decimal(rate_percent.strip()) / 100).quantize(Decimal("0.000001"))
    except InvalidOperation:
        raise AccountError("Rate must be a number, e.g. 15 for 15%") from None
    if not rate.is_finite() or rate < 0:
        raise AccountError("Rate must be zero or more")
    basis = parse_amount(cost_basis) if cost_basis.strip() else Decimal("0")
    return ProportionalFormula(rate=rate, cost_basis=basis)


def _render_form(
    request: Request,
    user: dict[str, Any],
    *,
    account: Account | None,
    form: dict[str, Any],
    candidates: list[Account],
    error: str | None = None,
    blocker: str | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    groups = [
        ("Assets", [c for c in candidates if c.type == RecordType.ASSET]),
        ("Liabilities", [c for c in candidates if c.type == RecordType.LIABILITY]),
    ]
    return render(
        request,
        "account_form.html",
        {
            "user": user,
            "active_tab": "accounts",
            "account": account,
            "form": form,
            "candidate_groups": [g for g in groups if g[1]],
            "error": error,
            "retire_blocker": blocker,
        },
        status_code=status_code,
    )


@router.get("/accounts/new", response_class=HTMLResponse)
async def new_account_page(
    request: Request, user: CurrentUser, type: Annotated[str, Query()] = "asset"
):
    type_ = type if type in ("asset", "liability") else "asset"
    with get_connection_context() as conn:
        candidates = _candidates(get_accounts(conn), None)
    return _render_form(
        request, user, account=None, form=_form_defaults(type_), candidates=candidates
    )


@router.post("/accounts")
async def create_account_route(
    request: Request,
    user: CurrentUser,
    name: Annotated[str, Form()] = "",
    type: Annotated[str, Form()] = "asset",
    computed: Annotated[bool, Form()] = False,
    rate_percent: Annotated[str, Form()] = "",
    cost_basis: Annotated[str, Form()] = "",
    input_ids: Annotated[list[int], Form()] = [],
):
    form = {
        "name": name,
        "type": type,
        "computed": computed,
        "rate_percent": rate_percent,
        "cost_basis": cost_basis,
        "input_ids": input_ids,
    }
    with get_connection_context() as conn:
        try:
            formula = _parse_formula(computed, rate_percent, cost_basis)
            account = create_account(conn, name, RecordType(type), formula, input_ids)
        except ValueError as e:
            candidates = _candidates(get_accounts(conn), None)
            return _render_form(
                request, user, account=None, form=form, candidates=candidates,
                error=str(e), status_code=400,
            )
    set_flash(request, "success", f"Added {account.name}")
    return RedirectResponse("/accounts", status_code=303)


@router.get("/accounts/{account_id}/edit", response_class=HTMLResponse)
async def edit_account_page(request: Request, user: CurrentUser, account_id: int):
    with get_connection_context() as conn:
        account = get_account(conn, account_id)
        if account is None:
            raise HTTPException(status_code=404, detail="Account not found")
        candidates = _candidates(get_accounts(conn), account_id)
        blocker = retire_blocker(conn, account) if account.is_active else None
    return _render_form(
        request, user, account=account, form=_form_from_account(account),
        candidates=candidates, blocker=blocker,
    )


@router.post("/accounts/{account_id}")
async def update_account_route(
    request: Request,
    user: CurrentUser,
    account_id: int,
    name: Annotated[str, Form()] = "",
    computed: Annotated[bool, Form()] = False,
    rate_percent: Annotated[str, Form()] = "",
    cost_basis: Annotated[str, Form()] = "",
    input_ids: Annotated[list[int], Form()] = [],
):
    with get_connection_context() as conn:
        account = get_account(conn, account_id)
        if account is None:
            raise HTTPException(status_code=404, detail="Account not found")
        form = {
            "name": name,
            "type": account.type.value,
            "computed": computed,
            "rate_percent": rate_percent,
            "cost_basis": cost_basis,
            "input_ids": input_ids,
        }
        try:
            formula = _parse_formula(computed, rate_percent, cost_basis)
            updated = update_account(conn, account_id, name, formula, input_ids)
        except ValueError as e:
            candidates = _candidates(get_accounts(conn), account_id)
            blocker = retire_blocker(conn, account) if account.is_active else None
            return _render_form(
                request, user, account=account, form=form, candidates=candidates,
                error=str(e), blocker=blocker, status_code=400,
            )
    set_flash(request, "success", f"Saved {updated.name}")
    return RedirectResponse("/accounts", status_code=303)


@router.post("/accounts/{account_id}/retire")
async def retire_account_route(request: Request, user: CurrentUser, account_id: int):
    with get_connection_context() as conn:
        try:
            account = retire_account(conn, account_id, date.today())
        except AccountError as e:
            set_flash(request, "error", str(e))
            return RedirectResponse("/accounts", status_code=303)
    set_flash(request, "success", f"Retired {account.name}")
    return RedirectResponse("/accounts", status_code=303)


@router.post("/accounts/{account_id}/unretire")
async def unretire_account_route(request: Request, user: CurrentUser, account_id: int):
    with get_connection_context() as conn:
        try:
            account = unretire_account(conn, account_id)
        except AccountError as e:
            set_flash(request, "error", str(e))
            return RedirectResponse("/accounts", status_code=303)
    set_flash(request, "success", f"Unretired {account.name}")
    return RedirectResponse("/accounts", status_code=303)
```

- [ ] **Step 4: Create the form template**

Create `src/asset_manager/web/templates/account_form.html`:

```html
{% extends "base.html" %}

{% block styles %}
    .form-card {
        max-width: 560px;
        margin: 0 auto;
        background: var(--bg-surface);
        border: 1px solid var(--border-subtle);
        border-radius: var(--radius);
        padding: 1.5rem 1.75rem;
    }

    .form-card h2 {
        font-family: var(--font-display);
        font-weight: 400;
        font-size: 1.3rem;
        margin-bottom: 1.25rem;
    }

    .form-card h2.asset { color: var(--color-asset); }
    .form-card h2.liability { color: var(--color-liability); }

    .field {
        display: block;
        margin-bottom: 1rem;
    }

    .field > span {
        display: block;
        font-size: 0.7rem;
        font-weight: 600;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--text-muted);
        margin-bottom: 0.3rem;
    }

    .field input[type=text] {
        width: 100%;
        background: var(--bg-primary);
        border: 1px solid var(--border-medium);
        border-radius: var(--radius);
        color: var(--text-primary);
        font-family: var(--font-body);
        font-size: 0.95rem;
        padding: 0.5rem 0.7rem;
        outline: none;
        transition: border-color 0.15s;
    }

    .field input[type=text]:focus {
        border-color: var(--accent-gold);
    }

    .field input.mono {
        font-family: var(--font-mono);
    }

    .choice {
        display: inline-flex;
        align-items: center;
        gap: 0.4rem;
        margin-right: 1.25rem;
        color: var(--text-secondary);
        font-size: 0.9rem;
        cursor: pointer;
    }

    .choice input {
        accent-color: var(--accent-gold);
    }

    .locked {
        color: var(--text-secondary);
        font-size: 0.9rem;
    }

    fieldset {
        border: 1px solid var(--border-subtle);
        border-radius: var(--radius);
        padding: 0.75rem 1rem;
        margin-bottom: 1rem;
    }

    legend {
        font-size: 0.7rem;
        font-weight: 600;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--text-muted);
        padding: 0 0.4rem;
    }

    fieldset h4 {
        font-size: 0.75rem;
        font-weight: 500;
        color: var(--text-muted);
        margin: 0.5rem 0 0.25rem;
    }

    fieldset .choice {
        display: flex;
        margin: 0.15rem 0;
    }

    .hint {
        color: var(--text-muted);
        font-size: 0.8rem;
        margin: 0.25rem 0 1rem;
    }

    .hint code {
        font-family: var(--font-mono);
        color: var(--accent-gold);
    }

    .form-actions {
        display: flex;
        gap: 0.75rem;
        align-items: center;
        margin-top: 1.25rem;
    }

    .danger-zone {
        margin-top: 1.75rem;
        padding-top: 1.25rem;
        border-top: 1px solid var(--border-subtle);
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 1rem;
    }

    .danger-zone .hint {
        margin: 0;
    }

    .btn:disabled {
        opacity: 0.5;
        cursor: not-allowed;
    }
{% endblock %}

{% block content %}
<div class="form-card fade-in">
    <h2 class="{{ form.type }}">{{ 'Edit' if account else 'New' }} {{ form.type }}</h2>

    <form method="post" action="{{ ('/accounts/' ~ account.id) if account else '/accounts' }}">
        <label class="field">
            <span>Name</span>
            <input type="text" name="name" value="{{ form.name }}" required autofocus>
        </label>

        <div class="field">
            <span>Type</span>
            {% if account %}
            <span class="locked">{{ form.type }} (cannot be changed)</span>
            {% else %}
            <label class="choice">
                <input type="radio" name="type" value="asset" {% if form.type == 'asset' %}checked{% endif %}> Asset
            </label>
            <label class="choice">
                <input type="radio" name="type" value="liability" {% if form.type == 'liability' %}checked{% endif %}> Liability
            </label>
            {% endif %}
        </div>

        <label class="choice field">
            <input type="checkbox" name="computed" id="computed" {% if form.computed %}checked{% endif %}>
            Computed from other accounts
        </label>

        <div id="formula-fields" {% if not form.computed %}hidden{% endif %}>
            <p class="hint">Value = <code>rate × (sum of inputs − cost basis)</code>. Leave the basis blank for zero.</p>
            <label class="field">
                <span>Rate (%)</span>
                <input type="text" class="mono" name="rate_percent" value="{{ form.rate_percent }}" inputmode="decimal" placeholder="15">
            </label>
            <label class="field">
                <span>Cost basis ($)</span>
                <input type="text" class="mono" name="cost_basis" value="{{ form.cost_basis }}" inputmode="decimal" placeholder="0.00">
            </label>
            <fieldset>
                <legend>Inputs</legend>
                {% for label, candidates in candidate_groups %}
                <h4>{{ label }}</h4>
                {% for candidate in candidates %}
                <label class="choice">
                    <input type="checkbox" name="input_ids" value="{{ candidate.id }}" {% if candidate.id in form.input_ids %}checked{% endif %}>
                    {{ candidate.name }}
                </label>
                {% endfor %}
                {% else %}
                <p class="hint">No plain, active accounts to use as inputs yet.</p>
                {% endfor %}
            </fieldset>
        </div>

        <div class="form-actions">
            <button type="submit" class="btn btn-primary">Save</button>
            <a href="/accounts" class="btn btn-secondary">Cancel</a>
        </div>
    </form>

    {% if account %}
    <div class="danger-zone">
        {% if account.retired_at %}
        <p class="hint">Retired {{ account.retired_at }}. Unretiring brings it back with a blank amount.</p>
        <form method="post" action="/accounts/{{ account.id }}/unretire">
            <button type="submit" class="btn btn-secondary">Unretire</button>
        </form>
        {% else %}
        <p class="hint">{{ retire_blocker or 'Retiring hides this account and stops including it in snapshots. History is kept.' }}</p>
        <form method="post" action="/accounts/{{ account.id }}/retire">
            <button type="submit" class="btn btn-secondary" {% if retire_blocker %}disabled{% endif %}>Retire</button>
        </form>
        {% endif %}
    </div>
    {% endif %}
</div>
{% endblock %}

{% block scripts %}
<script>
    const computedBox = document.getElementById('computed');
    const formulaFields = document.getElementById('formula-fields');
    computedBox.addEventListener('change', () => { formulaFields.hidden = !computedBox.checked; });
</script>
{% endblock %}
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_web.py -v --no-cov`
Expected: all PASS.

Run: `uv run pytest -v --no-cov`
Expected: all PASS.

- [ ] **Step 6: Check the form by eye**

With the dev server running, open `/accounts/new?type=liability`: the Computed checkbox reveals the formula fields; submitting with a bad rate re-renders with the error and your typed name kept; a successful submit lands on `/accounts` with a green "Added …" flash and the staged amounts you typed earlier still present. Open an account's edit page: the Retire button is disabled with the reason when the rule blocks it.

- [ ] **Step 7: Lint, typecheck, commit**

```bash
uv run ruff check src tests && uv run ruff format src tests && uv run ty check src/asset_manager
git add src/asset_manager/web tests/test_web.py
git commit -m "Add account create, edit, retire and unretire pages"
```

---

### Task 10: Docs, version, final verification

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Modify: `pyproject.toml`, `src/asset_manager/__init__.py`

- [ ] **Step 1: Update README.md**

1. Replace the opening paragraph with:

```markdown
A Python application for tracking personal financial assets and liabilities. Values are entered on the web dashboard's Accounts tab and saved as dated snapshots in PostgreSQL. Liabilities such as deferred tax can be computed from other accounts by a formula. A legacy `fetch` command still imports from a Google Sheet during the cutover.
```

2. In the Setup section's environment example, add after `SECRET_KEY=...`:

```
   ALLOWED_EMAILS=you@example.com   # optional; comma-separated allowlist for login
```

3. Replace the "Fetch data from Google Sheets" subsection with:

````markdown
### Enter values on the Accounts tab

Run the dashboard (below), open **Accounts**, type current amounts, and click **Save snapshot**. Every active account is written for today; saving again the same day replaces that day's snapshot.

- **Add** an asset or liability from the table header. A liability can be **computed**: `rate × (sum of chosen input accounts − cost basis)`. Cost basis is editable inline on the Accounts tab; rate and inputs live on the account's edit page.
- **Retire** an account from its edit page once its latest saved amount is zero and no computed account uses it as an input. History is kept; retired accounts are hidden behind a toggle and can be unretired.

### Import from Google Sheets (legacy)

Still works during the cutover. Rows are matched to accounts by name; unknown names create plain accounts and retired accounts are skipped.
```bash
ENV=dev uv run asset-manager fetch            # writes today's snapshot
ENV=dev uv run asset-manager fetch --dry-run  # shows what would be created or skipped
```
````

4. Delete the "Deployment" section (Vercel is not how this runs; the fleet deploys via ArgoCD).

- [ ] **Step 2: Update CLAUDE.md**

1. Replace the "Project Overview" paragraph with:

```markdown
Asset Manager is a Python application for tracking personal financial assets and liabilities. Values are entered on the web dashboard's Accounts tab and saved as dated snapshots in PostgreSQL. Liabilities can be computed from other accounts by a formula. The Google Sheets `fetch` path is legacy and slated for removal.
```

2. In the "Project Structure" tree, add these entries under `src/asset_manager/`:

```
│       ├── accounts.py         # Account rules, retire checks, snapshot save transaction
│       ├── formulas.py         # Pure formula evaluation (compute_snapshot)
```

and under `web/`:

```
│           ├── accounts_routes.py  # Accounts page, account form, POST /snapshots
│           ├── charts.py       # Plotly chart HTML for the dashboard
│           ├── rendering.py    # Templates, render(), flash messages
│           └── templates/
│               ├── account_form.html
│               ├── accounts.html
│               ├── base.html
│               ├── dashboard.html
│               └── login.html
```

3. Replace the "Core Modules" list with:

```markdown
- **`config.py`**: Environment configuration using pydantic-settings, loads from `.env.{ENV}` files
- **`models.py`**: `Account` (with `formula` JSON document and `input_ids`), `ProportionalFormula`, `Record`, `DailySummary`
- **`formulas.py`**: `compute_snapshot(accounts, values, as_of)`: pure evaluation, raises `MissingValueError`
- **`accounts.py`**: Service layer. `create_account`/`update_account` enforce input rules; `retire_account` requires a zero latest amount and no dependents; `save_snapshot` is all-or-nothing. Raises `AccountError` with user-facing messages. Commits.
- **`repository.py`**: Thin SQL. Never commits.
- **`db.py`**: Database connection management using psycopg3
- **`sheets.py`**: Legacy Google Sheets import (`save_rows` resolves names to accounts)
- **`report.py`**: Interactive HTML report generation using Plotly
- **`cli.py`**: Typer CLI with `fetch`, `report`, `serve`, and `version` commands
- **`web/app.py`**: App wiring, dashboard, auth routes
- **`web/accounts_routes.py`**: Accounts page, account form, `POST /snapshots`
- **`web/auth.py`**: OAuth/OIDC with PKCE, `require_user` dependency, `ALLOWED_EMAILS` gate
```

4. Replace the "Data Flow" section with:

```markdown
### Data Flow

1. The user edits amounts on `/accounts`. Edits are staged in the page (and `sessionStorage`) until **Save snapshot**.
2. `POST /snapshots` sends `{values: {account_id: amount}, cost_bases: {account_id: basis}}`.
3. `accounts.save_snapshot` validates, updates cost bases, evaluates formulas via `formulas.compute_snapshot`, and upserts one `snapshots` row per active account for today. All in one transaction.
4. Retired accounts get no row, so their series end. Charts read `snapshots` joined to `accounts`; formulas are never re-evaluated for history.
```

5. Replace the "Database Schema" SQL with:

```sql
CREATE TABLE accounts (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    type VARCHAR(10) NOT NULL CHECK (type IN ('asset', 'liability')),
    formula JSONB,              -- NULL = plain; {"kind": "proportional", "rate": "0.15", "cost_basis": "70634.00"}
    retired_at DATE,            -- NULL = active
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (type, name)
);

CREATE TABLE formula_inputs (   -- which plain accounts a computed account sums
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    input_id INTEGER NOT NULL REFERENCES accounts(id),
    PRIMARY KEY (account_id, input_id)
);

CREATE TABLE snapshots (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    amount DECIMAL(15, 2) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);
CREATE UNIQUE INDEX idx_snapshots_unique ON snapshots(date, account_id);
```

6. In the "Web Dashboard Environment Variables" table, add a row:

```markdown
| `ALLOWED_EMAILS` | Optional comma-separated allowlist; when set, other identity users get a 403 at login |
```

7. Add to the "Testing" section's file list:

```markdown
- `test_models.py`, `test_formulas.py`: Pure unit tests (Hypothesis for the formula property)
- `test_accounts.py`: Service rules and the save transaction (testcontainers)
- `test_migration.py`: Applies the accounts migration to legacy rows and checks the backfill and rollback
- `test_web.py`: FastAPI TestClient with a signed session cookie against the container
```

8. Add a new section after "Testing":

```markdown
### Rules worth knowing

- **Formula inputs must be plain, active accounts.** A computed account cannot feed another. An account that is an input cannot be made computed.
- **Retire flow**: set the amount to zero, Save, then Retire from the edit page. Blocked while any active computed account lists it as an input.
- **Same-day Save replaces** that day's rows. Retired accounts get no row.
- **Repository never commits**; the service layer does. `save_snapshot` uses `conn.transaction()`.
- **Adding a formula kind** later: one Pydantic class in `models.py` (make `Formula` a discriminated union on `kind`), one branch in `formulas._evaluate`, one form variant. No migration.
```

- [ ] **Step 3: Bump the version**

In `pyproject.toml` set `version = "0.3.0"` and in `src/asset_manager/__init__.py` set `__version__ = "0.3.0"`.

- [ ] **Step 4: Full verification**

Run each and confirm the output:

```bash
uv run ruff check src tests
uv run ruff format --check src tests
uv run ty check src/asset_manager
uv run pytest
```

Expected: no lint or type errors, all tests pass, and the coverage report prints (the default `addopts` include `--cov`).

- [ ] **Step 5: Commit**

```bash
git add README.md CLAUDE.md pyproject.toml src/asset_manager/__init__.py
git commit -m "Document editable accounts and bump to 0.3.0"
```

- [ ] **Step 6: Open the PR**

```bash
git push -u origin editable-accounts
gh pr create --title "Editable accounts with formula liabilities" --body "$(cat <<'EOF'
## Summary

- Adds an `accounts` table; `snapshots` rows now point at accounts by id (migration backfills from the old description text)
- Accounts tab is editable: staged edits, live recompute of formula liabilities, explicit **Save snapshot**
- Liabilities can be computed as `rate × (Σ inputs − cost basis)`; cost basis is inline-editable
- Accounts can be added, renamed, retired (at zero, with no dependents) and unretired
- Sheets `fetch` keeps working through the cutover (name matching, retired rows skipped)
- Optional `ALLOWED_EMAILS` login allowlist

Spec: `docs/superpowers/specs/2026-09-06-editable-accounts-design.md`

## Rollout

After merge, run `uv run dotenv -f .env.dev run dbmate up` for staging; for prod, branch the Neon database, then `dbmate up` against `.env.prod`, then `bif promote asset-manager`.

🤖 Generated with [Claude Code](https://claude.com/claude-code)

https://claude.ai/code/session_019xmQz7xUC8sPrM8sudBnTJ
EOF
)"
```

---

## Rollout after merge (manual, from the spec)

1. Staging: `uv run dotenv -f .env.dev run dbmate up` immediately after merge (staging 500s until then). Configure the two formulas, retire the zero-balance accounts, Save, check the dashboard.
2. Prod: create a Neon branch as a restore point. Then `uv run dotenv -f .env.prod run dbmate up`, then `bif promote asset-manager`.
3. Redo formula and retirement setup in prod. Stop updating the sheet.

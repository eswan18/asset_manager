-- migrate:up

-- A workspace's own grouping for cash flows (unlike account categories,
-- which are a fixed list). position orders them; ties break on id.
CREATE TABLE cash_flow_categories (
    id SERIAL PRIMARY KEY,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
    name TEXT NOT NULL CHECK (btrim(name) <> ''),
    position INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (workspace_id, name),
    UNIQUE (workspace_id, id)
);

-- A recurring income or expense: `amount` every `every` `unit`s. A current
-- list, edited in place, not dated history like snapshots. Per-day and
-- per-month figures are computed, never stored.
CREATE TABLE cash_flows (
    id SERIAL PRIMARY KEY,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
    name TEXT NOT NULL CHECK (btrim(name) <> ''),
    direction TEXT NOT NULL CHECK (direction IN ('income', 'expense')),
    amount NUMERIC(15, 2) NOT NULL CHECK (amount >= 0),
    every INTEGER NOT NULL CHECK (every BETWEEN 1 AND 1000),
    unit TEXT NOT NULL CHECK (unit IN ('day', 'week', 'month', 'year')),
    category_id INTEGER,
    description TEXT,
    is_estimate BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (workspace_id, name),
    -- Same workspace as its category. Deleting the category nulls only
    -- category_id (Postgres 15+), leaving the flow uncategorized.
    FOREIGN KEY (workspace_id, category_id)
        REFERENCES cash_flow_categories (workspace_id, id)
        ON DELETE SET NULL (category_id)
);

-- migrate:down
DROP TABLE cash_flows;
DROP TABLE cash_flow_categories;

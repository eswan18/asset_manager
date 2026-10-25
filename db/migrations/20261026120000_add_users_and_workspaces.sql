-- migrate:up

-- A person, as identity knows them. Matched on idp_sub (identity's stable
-- user id), never on email, which can change at identity.
CREATE TABLE users (
    id SERIAL PRIMARY KEY,
    idp_sub TEXT UNIQUE,  -- NULL until a pre-provisioned row's first login
    email TEXT NOT NULL CHECK (email = lower(email)),
    name TEXT,
    is_admin BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login_at TIMESTAMP WITH TIME ZONE
);
-- A pre-provisioned row is claimed by verified email at first login, so
-- there can be at most one unclaimed row per email.
CREATE UNIQUE INDEX users_unclaimed_email ON users (email) WHERE idp_sub IS NULL;

-- Owns every account, snapshot and formula. timezone dates its snapshots.
CREATE TABLE workspaces (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL CHECK (btrim(name) <> ''),
    timezone TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    deleted_at TIMESTAMP WITH TIME ZONE  -- soft delete; NULL = live
);

CREATE TABLE workspace_members (
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    role TEXT NOT NULL CHECK (role IN ('owner', 'editor', 'viewer')),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (workspace_id, user_id)
);
CREATE INDEX idx_workspace_members_user ON workspace_members (user_id);

-- Existing data has one owner. Give it a workspace and pre-provision that
-- owner as the admin; the first verified login with this email claims the
-- row. Skipped on an empty database, so fresh environments start clean.
WITH ws AS (
    INSERT INTO workspaces (name, timezone)
    SELECT 'Personal', 'America/Chicago'
    WHERE EXISTS (SELECT 1 FROM accounts)
    RETURNING id
), owner AS (
    INSERT INTO users (email, name, is_admin)
    SELECT 'ethanpswan@gmail.com', 'Ethan Swan', true FROM ws
    RETURNING id
)
INSERT INTO workspace_members (workspace_id, user_id, role)
SELECT ws.id, owner.id, 'owner' FROM ws, owner;

-- accounts: names are unique per workspace, and (workspace_id, id) is a key
-- so the tables below can require their accounts to share a workspace.
ALTER TABLE accounts ADD COLUMN workspace_id INTEGER REFERENCES workspaces(id);
UPDATE accounts SET workspace_id = (SELECT min(id) FROM workspaces);
ALTER TABLE accounts ALTER COLUMN workspace_id SET NOT NULL;
ALTER TABLE accounts DROP CONSTRAINT accounts_type_name_key;
ALTER TABLE accounts
    ADD CONSTRAINT accounts_workspace_type_name_key UNIQUE (workspace_id, type, name),
    ADD CONSTRAINT accounts_workspace_id_id_key UNIQUE (workspace_id, id);

-- formula_inputs: the composite keys make a formula reading another
-- workspace's account impossible, whatever the application does.
ALTER TABLE formula_inputs ADD COLUMN workspace_id INTEGER;
UPDATE formula_inputs fi SET workspace_id = a.workspace_id
FROM accounts a WHERE a.id = fi.account_id;
ALTER TABLE formula_inputs ALTER COLUMN workspace_id SET NOT NULL;
ALTER TABLE formula_inputs
    DROP CONSTRAINT formula_inputs_account_id_fkey,
    DROP CONSTRAINT formula_inputs_input_id_fkey,
    ADD CONSTRAINT formula_inputs_account_fkey FOREIGN KEY (workspace_id, account_id)
        REFERENCES accounts (workspace_id, id) ON DELETE CASCADE,
    ADD CONSTRAINT formula_inputs_input_fkey FOREIGN KEY (workspace_id, input_id)
        REFERENCES accounts (workspace_id, id);

-- snapshots: same, so a row can only point at its own workspace's account.
ALTER TABLE snapshots ADD COLUMN workspace_id INTEGER;
UPDATE snapshots s SET workspace_id = a.workspace_id
FROM accounts a WHERE a.id = s.account_id;
ALTER TABLE snapshots ALTER COLUMN workspace_id SET NOT NULL;
ALTER TABLE snapshots
    DROP CONSTRAINT snapshots_account_id_fkey,
    ADD CONSTRAINT snapshots_account_fkey FOREIGN KEY (workspace_id, account_id)
        REFERENCES accounts (workspace_id, id);
CREATE INDEX idx_snapshots_workspace_date ON snapshots (workspace_id, date);

-- migrate:down
-- Fails if two workspaces hold accounts of the same type and name, since
-- the old global uniqueness cannot be restored then.
DROP INDEX idx_snapshots_workspace_date;
ALTER TABLE snapshots
    DROP CONSTRAINT snapshots_account_fkey,
    ADD CONSTRAINT snapshots_account_id_fkey FOREIGN KEY (account_id)
        REFERENCES accounts(id),
    DROP COLUMN workspace_id;

ALTER TABLE formula_inputs
    DROP CONSTRAINT formula_inputs_account_fkey,
    DROP CONSTRAINT formula_inputs_input_fkey,
    ADD CONSTRAINT formula_inputs_account_id_fkey FOREIGN KEY (account_id)
        REFERENCES accounts(id) ON DELETE CASCADE,
    ADD CONSTRAINT formula_inputs_input_id_fkey FOREIGN KEY (input_id)
        REFERENCES accounts(id),
    DROP COLUMN workspace_id;

ALTER TABLE accounts
    DROP CONSTRAINT accounts_workspace_id_id_key,
    DROP CONSTRAINT accounts_workspace_type_name_key,
    ADD CONSTRAINT accounts_type_name_key UNIQUE (type, name),
    DROP COLUMN workspace_id;

DROP TABLE workspace_members;
DROP TABLE workspaces;
DROP TABLE users;

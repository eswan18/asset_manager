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

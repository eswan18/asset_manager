-- migrate:up
CREATE TABLE IF NOT EXISTS snapshots (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    type VARCHAR(10) NOT NULL CHECK (type IN ('asset', 'liability')),
    description TEXT NOT NULL,
    amount DECIMAL(15, 2) NOT NULL,
    accessible BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_snapshots_date ON snapshots(date);
CREATE INDEX IF NOT EXISTS idx_snapshots_type_date ON snapshots(type, date);
CREATE INDEX IF NOT EXISTS idx_snapshots_type_accessible_date ON snapshots(type, accessible, date);

-- Unique constraint to prevent duplicate snapshots
CREATE UNIQUE INDEX IF NOT EXISTS idx_snapshots_unique ON snapshots(date, type, description);

-- migrate:down
DROP TABLE IF EXISTS snapshots;

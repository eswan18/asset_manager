-- migrate:up
CREATE TABLE IF NOT EXISTS records (
    id SERIAL PRIMARY KEY,
    date DATE NOT NULL,
    type VARCHAR(10) NOT NULL CHECK (type IN ('asset', 'liability')),
    description TEXT NOT NULL,
    amount DECIMAL(15, 2) NOT NULL,
    accessible BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_records_date ON records(date);
CREATE INDEX IF NOT EXISTS idx_records_type_date ON records(type, date);
CREATE INDEX IF NOT EXISTS idx_records_type_accessible_date ON records(type, accessible, date);

-- Unique constraint to prevent duplicate records
CREATE UNIQUE INDEX IF NOT EXISTS idx_records_unique ON records(date, type, description);

-- migrate:down
DROP TABLE IF EXISTS records;

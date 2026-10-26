-- migrate:up

-- The zone only ever chose which calendar day a save or a retirement is
-- dated. That belongs to the person saving, so the browser now sends it
-- (the tz cookie) and the app falls back to TIMEZONE.
ALTER TABLE workspaces DROP COLUMN timezone;

-- migrate:down

ALTER TABLE workspaces ADD COLUMN timezone TEXT NOT NULL DEFAULT 'America/Chicago';
ALTER TABLE workspaces ALTER COLUMN timezone DROP DEFAULT;

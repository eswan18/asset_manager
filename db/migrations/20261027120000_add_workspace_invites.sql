-- migrate:up

-- An owner's offer of a role in a workspace to whoever holds `email` at
-- identity. Matched only against verified emails, and it never gets anyone
-- past ALLOWED_EMAILS: the invitee must already be able to log in.
CREATE TABLE workspace_invites (
    id SERIAL PRIMARY KEY,
    workspace_id INTEGER NOT NULL REFERENCES workspaces(id),
    email TEXT NOT NULL CHECK (email = lower(email) AND email LIKE '%_@_%'),
    role TEXT NOT NULL CHECK (role IN ('owner', 'editor', 'viewer')),
    invited_by INTEGER NOT NULL REFERENCES users(id),
    created_at TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP WITH TIME ZONE NOT NULL,
    -- At most one of these is set; all NULL and unexpired means pending.
    accepted_at TIMESTAMP WITH TIME ZONE,
    accepted_by INTEGER REFERENCES users(id),
    declined_at TIMESTAMP WITH TIME ZONE,
    revoked_at TIMESTAMP WITH TIME ZONE,
    CHECK (num_nonnulls(accepted_at, declined_at, revoked_at) <= 1),
    CHECK ((accepted_at IS NULL) = (accepted_by IS NULL))
);
-- One open invite per workspace and email. An expired one still counts, so
-- the service revokes it before inviting the same email again.
CREATE UNIQUE INDEX workspace_invites_open
    ON workspace_invites (workspace_id, email)
    WHERE accepted_at IS NULL AND declined_at IS NULL AND revoked_at IS NULL;
CREATE INDEX idx_workspace_invites_email ON workspace_invites (email);

-- migrate:down
DROP TABLE workspace_invites;

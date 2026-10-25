"""Shared test constants. db_connection seeds these rows before each test."""

# The seeded workspace and its owner. RESTART IDENTITY makes both id 1.
WS = 1
USER_ID = 1
SEED_USER = {"id": USER_ID, "sub": "user-1", "email": "me@example.com", "name": "Me"}

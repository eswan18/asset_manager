"""The invite strip (board Z): a pending invite, on every page with the shell.

Someone already in a workspace learns of an invite here rather than only on
/welcome. One strip per invite they could accept now, newest first. Join and
Decline post to welcome_routes' `/invites/{id}/accept|decline`; Decline
carries the page it was on as `next`, which `safe_next` vets.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlsplit

from psycopg import Connection

from sensibility.invites import acceptable_invites

from .wording import a_role, day_text


def strip_items(conn: Connection, email: str, zone: str) -> list[dict[str, Any]]:
    """What the shell shows for each acceptable invite, newest first."""
    return [
        {
            "id": found.invite.id,
            "sender": found.sender,
            "workspace": found.workspace.name,
            "role": a_role(found.invite.role),
            "expires": day_text(found.invite.expires_at, zone),
        }
        for found in reversed(acceptable_invites(conn, email))
    ]


def safe_next(value: str | None) -> str | None:
    """`value` if it is a path on this site ("/workspaces/1?per=year"), else
    None. Refuses absolute and scheme-relative URLs ("//evil.com"), any
    backslash (browsers read "/\\evil.com" as "//evil.com"), and control
    characters (browsers drop tabs and newlines, which can make "//")."""
    if not value or not value.startswith("/") or value.startswith("//"):
        return None
    if "\\" in value or any(ord(c) < 0x20 or ord(c) == 0x7F for c in value):
        return None
    parts = urlsplit(value)
    if parts.scheme or parts.netloc:
        return None
    return value

"""JSON for settings, welcome and the invite strip: `GET .../settings` and
`GET /api/invites` (with sender names and whether each can be accepted)."""

import pytest

from sensibility import repository as repo
from sensibility.invites import create_invite
from sensibility.models import Role
from sensibility.workspaces import create_workspace
from tests.support import USER_ID, WS
from tests.web_support import USER, STRANGER, add_user, login, session_for

SETTINGS = f"/api/workspaces/{WS}/settings"
THIRD = {"id": 3, "sub": "user-3", "email": "third@example.com", "name": "Third Person"}
NAMELESS = {"id": 4, "sub": "user-4", "email": "nameless@example.com", "name": None}
INVITEE = "sam.lee@example.com"
OTHER_WS = 2


@pytest.fixture
def team(db_connection):
    """The seeded owner (Me), Stranger as an editor, Third as a viewer, and
    a pending invite from Me."""
    add_user(db_connection, STRANGER, "editor")
    add_user(db_connection, THIRD, "viewer")
    return create_invite(db_connection, WS, USER_ID, INVITEE, Role.EDITOR)


def members(body) -> list[tuple]:
    return [
        (m["user_id"], m["display_name"], m["role"], m["you"], m["removable"])
        for m in body["members"]
    ]


@pytest.mark.db
class TestWorkspaceSettings:
    def test_the_owner_gets_everything(self, client, team):
        login(client)
        body = client.get(SETTINGS).json()

        assert {k: body[k] for k in ("id", "name", "role", "is_owner")} == {
            "id": WS,
            "name": "Test",
            "role": "owner",
            "is_owner": True,
        }
        # The only owner: cannot leave, so their own row is not removable.
        assert body["can_leave"] is False
        assert members(body) == [
            (USER_ID, "Me", "owner", True, False),
            (STRANGER["id"], "Stranger", "editor", False, True),
            (THIRD["id"], "Third Person", "viewer", False, True),
        ]
        me = body["members"][0]
        assert (me["email"], me["name"]) == ("me@example.com", "Me")
        assert me["joined_at"]
        [invite] = body["invites"]
        assert invite == {
            "id": team.id,
            "email": INVITEE,
            "role": "editor",
            "invited_by": USER_ID,
            "sent_by_you": True,
            "sender_name": "Me",
            "created_at": team.created_at.isoformat(),
            "expires_at": team.expires_at.isoformat(),
            "lapsed": False,
        }
        assert body["invite_ttl_days"] == 14
        assert body["roles"] == ["owner", "editor", "viewer"]

    @pytest.mark.parametrize(
        ("user", "role"), [(STRANGER, "editor"), (THIRD, "viewer")]
    )
    def test_others_read_it_without_invites_and_may_leave(
        self, client, team, user, role
    ):
        session_for(client, user)
        response = client.get(SETTINGS)

        assert response.status_code == 200
        body = response.json()
        assert (body["role"], body["is_owner"], body["can_leave"]) == (
            role,
            False,
            True,
        )
        assert body["invites"] == []
        # Only their own row: removing yourself is leaving.
        removable = [m["user_id"] for m in body["members"] if m["removable"]]
        assert removable == [user["id"]]
        assert [m["user_id"] for m in body["members"] if m["you"]] == [user["id"]]

    def test_an_owner_with_another_owner_may_leave(self, client, db_connection, team):
        repo.set_member_role(db_connection, WS, STRANGER["id"], Role.OWNER)
        db_connection.commit()
        login(client)
        body = client.get(SETTINGS).json()
        assert body["can_leave"] is True
        assert all(m["removable"] for m in body["members"])

    def test_a_lapsed_invite_and_its_sender(self, client, db_connection, team):
        """An invite speaks for its sender: once they are not an owner it
        cannot be accepted; once they are gone, there is no sender name."""
        repo.set_member_role(db_connection, WS, STRANGER["id"], Role.OWNER)
        db_connection.commit()
        session_for(client, STRANGER)
        [invite] = client.get(SETTINGS).json()["invites"]
        assert (invite["sent_by_you"], invite["sender_name"], invite["lapsed"]) == (
            False,
            "Me",
            False,
        )

        repo.set_member_role(db_connection, WS, USER_ID, Role.EDITOR)
        db_connection.commit()
        [invite] = client.get(SETTINGS).json()["invites"]
        assert (invite["sender_name"], invite["lapsed"]) == ("Me", True)

        repo.delete_member(db_connection, WS, USER_ID)
        db_connection.commit()
        [invite] = client.get(SETTINGS).json()["invites"]
        assert (invite["sender_name"], invite["lapsed"]) == (None, True)

    def test_a_member_without_a_name_shows_their_email(self, client, db_connection):
        add_user(db_connection, STRANGER, "editor")
        add_user(db_connection, THIRD)
        add_user(db_connection, NAMELESS, "viewer")
        login(client)
        last = client.get(SETTINGS).json()["members"][-1]
        assert (last["name"], last["display_name"]) == (None, NAMELESS["email"])

    def test_agrees_with_the_settings_page(self, client, db_connection, team):
        """The page and the API read the same facts."""
        from sensibility.db import get_connection_context
        from sensibility.web.access import WorkspaceAccess
        from sensibility.web.settings_routes import settings_view

        workspace = repo.get_workspace(db_connection, WS)
        assert workspace is not None
        for user, role in (
            (USER, Role.OWNER),
            (STRANGER, Role.EDITOR),
            (THIRD, Role.VIEWER),
        ):
            access = WorkspaceAccess(user=dict(user), workspace=workspace, role=role)
            with get_connection_context() as conn:
                view = settings_view(conn, access, "UTC")
            session_for(client, user)
            body = client.get(SETTINGS).json()
            assert body["can_leave"] == view["can_leave"]
            assert body["is_owner"] == view["is_owner"]
            page_members = [p for p in view["people"] if p["kind"] == "member"]
            assert [
                (m["user_id"], m["you"], m["removable"]) for m in body["members"]
            ] == [(p["id"], p["you"], p["removable"]) for p in page_members]
            page_invites = [p for p in view["people"] if p["kind"] == "invite"]
            assert [i["id"] for i in body["invites"]] == [p["id"] for p in page_invites]

    def test_another_workspace_is_404(self, client, db_connection, team):
        create_workspace(db_connection, STRANGER["id"], "Theirs")
        login(client)
        assert client.get(f"/api/workspaces/{OTHER_WS}/settings").status_code == 404

    def test_logged_out_is_401(self, client):
        assert client.get(SETTINGS).status_code == 401


@pytest.mark.db
class TestMyInvites:
    def test_lists_sender_and_acceptability_keeping_the_old_fields(
        self, client, db_connection
    ):
        add_user(db_connection, STRANGER)
        invite = create_invite(
            db_connection, WS, USER_ID, STRANGER["email"], Role.VIEWER
        )
        session_for(client, STRANGER)

        [mine] = client.get("/api/invites").json()["invites"]

        assert mine == {
            "id": invite.id,
            "workspace_id": WS,
            "workspace_name": "Test",
            "email": STRANGER["email"],
            "role": "viewer",
            "invited_by": USER_ID,
            "sender_name": "Me",
            "created_at": invite.created_at.isoformat(),
            "expires_at": invite.expires_at.isoformat(),
            "acceptable": True,
        }

    def test_a_lapsed_invite_is_listed_but_not_acceptable(self, client, db_connection):
        """The welcome page and the strip leave it out; the API keeps listing
        it, as it always has, and says why it cannot be accepted."""
        add_user(db_connection, STRANGER)
        add_user(db_connection, THIRD, "owner")
        lapsing = create_invite(
            db_connection, WS, THIRD["id"], STRANGER["email"], Role.EDITOR
        )
        create_workspace(db_connection, USER_ID, "Second")
        kept = create_invite(
            db_connection, OTHER_WS, USER_ID, STRANGER["email"], Role.VIEWER
        )
        repo.set_member_role(db_connection, WS, THIRD["id"], Role.VIEWER)
        db_connection.commit()
        session_for(client, STRANGER)

        listed = client.get("/api/invites").json()["invites"]

        # Oldest first.
        assert [
            (i["id"], i["workspace_name"], i["sender_name"], i["acceptable"])
            for i in listed
        ] == [
            (lapsing.id, "Test", "Third Person", False),
            (kept.id, "Second", "Me", True),
        ]
        assert client.post(f"/api/invites/{lapsing.id}/accept").status_code == 404
        assert client.post(f"/api/invites/{kept.id}/accept").status_code == 200

    def test_a_sender_without_a_name_is_their_email(self, client, db_connection):
        add_user(db_connection, STRANGER)
        add_user(db_connection, THIRD)
        add_user(db_connection, NAMELESS, "owner")
        create_invite(db_connection, WS, NAMELESS["id"], STRANGER["email"], Role.VIEWER)
        session_for(client, STRANGER)
        [mine] = client.get("/api/invites").json()["invites"]
        assert mine["sender_name"] == NAMELESS["email"]

    def test_logged_out_is_401(self, client):
        assert client.get("/api/invites").status_code == 401

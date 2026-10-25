"""Workspaces over HTTP: isolation, roles, membership, and login."""

from datetime import date
from decimal import Decimal

import pytest

from asset_manager import repository as repo
from asset_manager.accounts import create_account
from asset_manager.clock import today
from asset_manager.models import RecordType, Role
from asset_manager.workspaces import create_workspace
from tests.support import USER_ID, WS
from tests.web_support import (
    ACCOUNTS,
    SNAPSHOTS,
    STRANGER,
    TZ,
    USER,
    FakeIdp,
    add_user,
    claims,
    login,
    protected_routes,
    session_for,
    sweep,
)

OTHER_WS = 2


def ws1_state(conn) -> tuple:
    """Everything in the seeded workspace, for before/after comparisons."""
    return (
        repo.get_accounts(conn, WS),
        repo.get_all_records(conn, WS),
        repo.get_members(conn, WS),
        repo.get_workspace(conn, WS),
    )


@pytest.fixture
def ws1(db_connection):
    """The seeded workspace with an account (id 1) and one snapshot."""
    cash = create_account(db_connection, WS, "Cash", RecordType.ASSET)
    assert cash.id == 1  # the sweeps substitute 1 for {account_id}
    repo.upsert_amounts(db_connection, WS, date(2026, 9, 1), {cash.id: Decimal("50")})
    db_connection.commit()
    return cash


def in_workspace(path: str, workspace_id: int = WS) -> bool:
    return path.startswith(f"/api/workspaces/{workspace_id}")


@pytest.mark.db
class TestIsolation:
    """A member of one workspace can reach nothing in another."""

    def test_every_route_hides_another_workspace_and_changes_nothing(
        self, client, db_connection, ws1
    ):
        add_user(db_connection, STRANGER)
        create_workspace(db_connection, STRANGER["id"], "Theirs", "UTC")
        theirs = create_account(db_connection, OTHER_WS, "Other", RecordType.ASSET)
        assert theirs.id == 2
        before = ws1_state(db_connection)
        session_for(client, STRANGER)

        statuses = sweep(client)

        foreign = {k: v for k, v in statuses.items() if in_workspace(k[1])}
        assert foreign and set(foreign.values()) == {404}
        assert ws1_state(db_connection) == before

    def test_pages_show_only_your_own_workspace(self, client, db_connection, ws1):
        add_user(db_connection, STRANGER)
        create_workspace(db_connection, STRANGER["id"], "Theirs", "UTC")
        create_account(db_connection, OTHER_WS, "Other", RecordType.ASSET)
        session_for(client, STRANGER)

        assert "Other" in client.get("/accounts").text
        assert "Cash" not in client.get("/accounts").text
        assert "Cash" not in client.get("/").text
        assert client.get(f"/accounts/{ws1.id}/edit").status_code == 404

    def test_another_workspaces_account_ids_are_unknown_to_saves(
        self, client, db_connection, ws1
    ):
        add_user(db_connection, STRANGER)
        create_workspace(db_connection, STRANGER["id"], "Theirs", "UTC")
        theirs = create_account(db_connection, OTHER_WS, "Other", RecordType.ASSET)
        before = ws1_state(db_connection)
        session_for(client, STRANGER)

        response = client.post(
            f"/api/workspaces/{OTHER_WS}/snapshots",
            json={"values": {str(theirs.id): "1", str(ws1.id): "999"}},
        )

        assert response.status_code == 400
        assert "not an active account" in response.json()["error"]
        assert ws1_state(db_connection) == before

    def test_another_workspaces_account_cannot_be_a_formula_input(
        self, client, db_connection, ws1
    ):
        add_user(db_connection, STRANGER)
        create_workspace(db_connection, STRANGER["id"], "Theirs", "UTC")
        session_for(client, STRANGER)

        response = client.post(
            "/accounts",
            data={
                "name": "Tax",
                "type": "liability",
                "computed": "true",
                "rate_percent": "15",
                "input_ids": [str(ws1.id)],
            },
        )

        assert response.status_code == 400
        assert repo.get_accounts(db_connection, OTHER_WS) == []

    def test_latest_snapshot_date_is_per_workspace(self, client, db_connection, ws1):
        """A save in one workspace must not move another's latest date."""
        add_user(db_connection, STRANGER)
        create_workspace(db_connection, STRANGER["id"], "Theirs", TZ)
        theirs = create_account(db_connection, OTHER_WS, "Other", RecordType.ASSET)
        session_for(client, STRANGER)
        saved = client.post(
            f"/api/workspaces/{OTHER_WS}/snapshots",
            json={"values": {str(theirs.id): "1"}},
        )
        assert saved.status_code == 200

        login(client)
        body = client.get(ACCOUNTS).json()
        assert body["as_of"] == "2026-09-01"
        assert [a["amount"] for a in body["accounts"]] == ["50.00"]
        # And a partial save still carries ws1's own values forward.
        assert client.post(SNAPSHOTS, json={}).status_code == 200


@pytest.mark.db
class TestRoles:
    def _expected_403_for_viewer(self) -> set[tuple[str, str]]:
        """Every write except creating your own workspace, plus the add-account
        form, which only exists to write."""
        return {
            (method, path)
            for method, path in protected_routes()
            if method != "GET" and path != "/api/workspaces"
        } | {("GET", "/accounts/new")}

    def test_a_viewer_can_read_but_not_write_anywhere(self, client, db_connection, ws1):
        add_user(db_connection, STRANGER, "viewer")
        before = ws1_state(db_connection)
        session_for(client, STRANGER)

        statuses = sweep(client)

        refused = {k for k, v in statuses.items() if v == 403}
        assert refused == self._expected_403_for_viewer()
        reads = {
            k: v for k, v in statuses.items() if k[0] == "GET" and k not in refused
        }
        assert set(reads.values()) == {200}
        assert ws1_state(db_connection) == before

    def test_an_editor_can_change_data_but_not_the_workspace_or_members(
        self, client, db_connection, ws1
    ):
        add_user(db_connection, STRANGER, "editor")
        session_for(client, STRANGER)

        statuses = sweep(client)

        refused = {k for k, v in statuses.items() if v == 403}
        assert refused == {
            ("PATCH", f"/api/workspaces/{WS}"),
            ("DELETE", f"/api/workspaces/{WS}"),
            ("PATCH", f"/api/workspaces/{WS}/members/{USER_ID}"),
            ("DELETE", f"/api/workspaces/{WS}/members/{USER_ID}"),
        }
        workspace = repo.get_workspace(db_connection, WS)
        assert workspace is not None and workspace.deleted_at is None
        assert {m.user_id: m.role for m in repo.get_members(db_connection, WS)} == {
            USER_ID: Role.OWNER,
            STRANGER["id"]: Role.EDITOR,
        }

    def test_page_writes_are_refused_for_viewers(self, client, db_connection, ws1):
        add_user(db_connection, STRANGER, "viewer")
        session_for(client, STRANGER)
        response = client.post(
            "/snapshots", json={"values": {str(ws1.id): "1"}, "cost_bases": {}}
        )
        assert response.status_code == 403
        assert client.get("/accounts/new").status_code == 403


@pytest.mark.db
class TestMe:
    def test_lists_your_workspaces_with_roles(self, client, db_connection):
        add_user(db_connection, STRANGER)
        create_workspace(db_connection, STRANGER["id"], "Theirs", "UTC")
        repo.add_member(db_connection, OTHER_WS, USER_ID, Role.VIEWER)
        db_connection.commit()
        login(client)

        body = client.get("/api/me").json()

        assert body["id"] == USER_ID and body["is_admin"] is False
        assert body["workspaces"] == [
            {"id": WS, "name": "Test", "timezone": TZ, "role": "owner"},
            {"id": OTHER_WS, "name": "Theirs", "timezone": "UTC", "role": "viewer"},
        ]


@pytest.mark.db
class TestWorkspaceEndpoints:
    def test_create_makes_you_owner_with_the_default_time_zone(self, client):
        login(client)
        response = client.post("/api/workspaces", json={"name": "Joint"})
        assert response.status_code == 201
        assert response.json() == {
            "id": OTHER_WS,
            "name": "Joint",
            "timezone": "America/Chicago",
            "role": "owner",
        }
        names = [w["name"] for w in client.get("/api/me").json()["workspaces"]]
        assert names == ["Test", "Joint"]

    @pytest.mark.parametrize(
        "body", [{"name": " "}, {"name": "W", "timezone": "Mars/Olympus"}]
    )
    def test_create_rejects_bad_input(self, client, db_connection, body):
        login(client)
        response = client.post("/api/workspaces", json=body)
        assert response.status_code == 400
        assert repo.get_workspace(db_connection, OTHER_WS) is None

    def test_time_zone_change_dates_the_next_snapshot(self, client, db_connection, ws1):
        login(client)
        for zone in ("Pacific/Kiritimati", "Pacific/Pago_Pago"):
            patched = client.patch(f"/api/workspaces/{WS}", json={"timezone": zone})
            assert patched.status_code == 200
            assert patched.json()["timezone"] == zone
            saved = client.post(SNAPSHOTS, json={})
            assert saved.json()["date"] == today(zone).isoformat()

    def test_delete_hides_it_from_every_member_and_keeps_data(
        self, client, db_connection, ws1
    ):
        add_user(db_connection, STRANGER, "editor")
        login(client)

        assert client.delete(f"/api/workspaces/{WS}").status_code == 200

        assert client.get(ACCOUNTS).status_code == 404
        assert client.get("/api/me").json()["workspaces"] == []
        assert client.get("/accounts").status_code == 403  # no workspace left
        session_for(client, STRANGER)
        assert client.get(ACCOUNTS).status_code == 404
        assert repo.get_accounts(db_connection, WS) != []


@pytest.mark.db
class TestMemberEndpoints:
    def test_owner_changes_roles_but_not_the_last_owner(self, client, db_connection):
        add_user(db_connection, STRANGER, "viewer")
        login(client)
        members = f"/api/workspaces/{WS}/members"

        assert (
            client.patch(
                f"{members}/{STRANGER['id']}", json={"role": "editor"}
            ).status_code
            == 200
        )
        last = client.patch(f"{members}/{USER_ID}", json={"role": "editor"})
        assert last.status_code == 400
        assert "at least one owner" in last.json()["error"]
        bad = client.patch(f"{members}/{STRANGER['id']}", json={"role": "admin"})
        assert bad.status_code == 422

        listed = client.get(members).json()["members"]
        assert [(m["user_id"], m["role"]) for m in listed] == [
            (USER_ID, "owner"),
            (STRANGER["id"], "editor"),
        ]

    def test_anyone_can_leave_but_the_last_owner(self, client, db_connection):
        add_user(db_connection, STRANGER, "viewer")
        members = f"/api/workspaces/{WS}/members"

        session_for(client, STRANGER)
        assert client.delete(f"{members}/{STRANGER['id']}").status_code == 200
        assert client.get(ACCOUNTS).status_code == 404

        login(client)
        last = client.delete(f"{members}/{USER_ID}")
        assert last.status_code == 400
        assert "at least one owner" in last.json()["error"]

    def test_owner_removes_others(self, client, db_connection):
        add_user(db_connection, STRANGER, "editor")
        login(client)
        response = client.delete(f"/api/workspaces/{WS}/members/{STRANGER['id']}")
        assert response.status_code == 200
        assert [m.user_id for m in repo.get_members(db_connection, WS)] == [USER_ID]


@pytest.mark.db
class TestLogin:
    def _use(self, monkeypatch, idp):
        from types import SimpleNamespace

        import asset_manager.web.app as app_module

        monkeypatch.setattr(
            app_module, "get_oauth_client", lambda: SimpleNamespace(idp=idp)
        )

    def _user_count(self, conn) -> int:
        row = conn.execute("SELECT count(*) FROM users").fetchone()
        assert row is not None
        return row[0]

    @pytest.mark.parametrize("verified", [False, None, "true", 1])
    def test_an_unverified_email_is_refused_and_records_nothing(
        self, client, db_connection, monkeypatch, verified
    ):
        token = claims(STRANGER)
        if verified is None:
            del token["email_verified"]
        else:
            token["email_verified"] = verified
        self._use(monkeypatch, FakeIdp(token={"userinfo": token}))

        response = client.get("/auth/callback", follow_redirects=False)

        assert response.status_code == 403
        assert "session=" not in response.headers.get("set-cookie", "")
        assert self._user_count(db_connection) == 1

    def test_first_login_creates_a_user_with_no_workspace(
        self, client, db_connection, monkeypatch
    ):
        self._use(monkeypatch, FakeIdp(token={"userinfo": claims(STRANGER)}))

        client.get("/auth/callback", follow_redirects=False)

        me = client.get("/api/me").json()
        assert (me["id"], me["email"], me["workspaces"]) == (
            STRANGER["id"],
            STRANGER["email"],
            [],
        )
        assert client.get("/accounts").status_code == 403

    def test_a_preprovisioned_admin_is_claimed_on_first_login(
        self, client, db_connection, monkeypatch
    ):
        db_connection.execute(
            "INSERT INTO users (email, is_admin) VALUES ('boss@example.com', true)"
        )
        db_connection.commit()
        boss = {"sub": "sub-boss", "email": "Boss@Example.com", "name": "Boss"}
        self._use(monkeypatch, FakeIdp(token={"userinfo": claims(boss)}))

        client.get("/auth/callback", follow_redirects=False)

        me = client.get("/api/me").json()
        assert (me["id"], me["is_admin"], me["email"]) == (2, True, "boss@example.com")

    def test_a_session_from_before_users_existed_must_log_in_again(self, client):
        session_for(client, {k: v for k, v in USER.items() if k != "id"})
        assert client.get("/api/me").status_code == 401

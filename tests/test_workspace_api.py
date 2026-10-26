"""Workspaces over HTTP: isolation, roles, membership, and login."""

from datetime import date
from decimal import Decimal

import pytest

from asset_manager import repository as repo
from asset_manager.accounts import create_account
from asset_manager.models import RecordType, Role
from asset_manager.workspaces import create_workspace
from tests.support import USER_ID, WS
from tests.web_support import (
    PAGES,
    ACCOUNTS,
    SNAPSHOTS,
    STRANGER,
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
    cash = create_account(db_connection, WS, "Checking", RecordType.ASSET)
    assert cash.id == 1  # the sweeps substitute 1 for {account_id}
    repo.upsert_amounts(db_connection, WS, date(2026, 9, 1), {cash.id: Decimal("50")})
    db_connection.commit()
    return cash


def in_workspace(path: str, workspace_id: int = WS) -> bool:
    """An API route or a page that acts in this workspace."""
    return path.startswith(
        (f"/api/workspaces/{workspace_id}", f"/workspaces/{workspace_id}")
    )


# Bare paths redirect into your oldest workspace rather than acting in one.
BARE_PAGES = {("GET", "/"), ("GET", "/accounts")}


@pytest.mark.db
class TestIsolation:
    """A member of one workspace can reach nothing in another."""

    def test_every_route_hides_another_workspace_and_changes_nothing(
        self, client, db_connection, ws1
    ):
        add_user(db_connection, STRANGER)
        create_workspace(db_connection, STRANGER["id"], "Theirs")
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
        create_workspace(db_connection, STRANGER["id"], "Theirs")
        create_account(db_connection, OTHER_WS, "Other", RecordType.ASSET)
        session_for(client, STRANGER)
        theirs = f"/workspaces/{OTHER_WS}"

        assert "Other" in client.get(f"{theirs}/accounts").text
        # Not "Cash": the nav's "Cash flows" would match it on every page.
        assert "Checking" not in client.get(f"{theirs}/accounts").text
        assert "Checking" not in client.get(theirs).text
        assert "Checking" not in client.get(f"{theirs}/cash-flows").text
        assert client.get(f"{theirs}/accounts/{ws1.id}/edit").status_code == 404
        for path in (
            PAGES,
            f"{PAGES}/accounts",
            f"{PAGES}/accounts/{ws1.id}/edit",
            f"{PAGES}/cash-flows",
        ):
            assert client.get(path).status_code == 404, path

    def test_bare_paths_go_to_your_own_oldest_workspace(
        self, client, db_connection, ws1
    ):
        add_user(db_connection, STRANGER)
        create_workspace(db_connection, STRANGER["id"], "Theirs")
        repo.add_member(db_connection, WS, STRANGER["id"], Role.VIEWER)
        db_connection.commit()
        session_for(client, STRANGER)

        home = client.get("/", follow_redirects=False)
        accounts = client.get("/accounts", follow_redirects=False)

        assert (home.status_code, home.headers["location"]) == (
            302,
            f"/workspaces/{OTHER_WS}",
        )
        assert accounts.headers["location"] == f"/workspaces/{OTHER_WS}/accounts"
        # A trailing slash reaches the dashboard too.
        assert client.get(f"/workspaces/{OTHER_WS}/").status_code == 200

    def test_the_picker_lists_your_workspaces_on_the_same_page(
        self, client, db_connection, ws1
    ):
        add_user(db_connection, STRANGER)
        create_workspace(db_connection, STRANGER["id"], "Theirs")
        theirs = create_account(db_connection, OTHER_WS, "Other", RecordType.ASSET)
        repo.add_member(db_connection, WS, STRANGER["id"], Role.VIEWER)
        db_connection.commit()
        session_for(client, STRANGER)

        text = client.get(f"/workspaces/{OTHER_WS}/accounts/{theirs.id}/edit").text

        assert f'<option value="{PAGES}/accounts">Test</option>' in text
        assert (
            f'<option value="/workspaces/{OTHER_WS}/accounts" selected>Theirs</option>'
            in text
        )

    def test_another_workspaces_account_ids_are_unknown_to_saves(
        self, client, db_connection, ws1
    ):
        add_user(db_connection, STRANGER)
        create_workspace(db_connection, STRANGER["id"], "Theirs")
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
        create_workspace(db_connection, STRANGER["id"], "Theirs")
        session_for(client, STRANGER)

        response = client.post(
            f"/workspaces/{OTHER_WS}/accounts",
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
        create_workspace(db_connection, STRANGER["id"], "Theirs")
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
        """Every write to the workspace, plus the owner-only invite list and
        the forms that only exist to write: the add-account drawer and the
        Cash flows page's drawers. Creating your own workspace and answering
        your own invites are not workspace writes."""
        return {
            (method, path)
            for method, path in protected_routes()
            if method != "GET"
            and path != "/api/workspaces"
            and not path.startswith("/api/invites/")
        } | {
            ("GET", f"{PAGES}/accounts/new"),
            ("GET", f"{PAGES}/cash-flows/new"),
            ("GET", f"{PAGES}/cash-flows/1/edit"),
            ("GET", f"{PAGES}/cash-flow-categories"),
            ("GET", f"/api/workspaces/{WS}/invites"),
        }

    def test_a_viewer_can_read_but_not_write_anywhere(self, client, db_connection, ws1):
        add_user(db_connection, STRANGER, "viewer")
        before = ws1_state(db_connection)
        session_for(client, STRANGER)

        statuses = sweep(client)

        refused = {k for k, v in statuses.items() if v == 403}
        assert refused == self._expected_403_for_viewer()
        reads = {
            k: v
            for k, v in statuses.items()
            if k[0] == "GET" and k not in refused | BARE_PAGES
        }
        assert set(reads.values()) == {200}
        assert {statuses[k] for k in BARE_PAGES} == {302}
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
            ("POST", f"/api/workspaces/{WS}/invites"),
            ("GET", f"/api/workspaces/{WS}/invites"),
            ("DELETE", f"/api/workspaces/{WS}/invites/1"),
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
            f"{PAGES}/snapshots", json={"values": {str(ws1.id): "1"}, "cost_bases": {}}
        )
        assert response.status_code == 403
        assert client.get(f"{PAGES}/accounts/new").status_code == 403


@pytest.mark.db
class TestMe:
    def test_lists_your_workspaces_with_roles(self, client, db_connection):
        add_user(db_connection, STRANGER)
        create_workspace(db_connection, STRANGER["id"], "Theirs")
        repo.add_member(db_connection, OTHER_WS, USER_ID, Role.VIEWER)
        db_connection.commit()
        login(client)

        body = client.get("/api/me").json()

        assert body["id"] == USER_ID and body["is_admin"] is False
        assert body["workspaces"] == [
            {"id": WS, "name": "Test", "role": "owner"},
            {"id": OTHER_WS, "name": "Theirs", "role": "viewer"},
        ]


@pytest.mark.db
class TestWorkspaceEndpoints:
    def test_create_makes_you_owner(self, client):
        login(client)
        response = client.post("/api/workspaces", json={"name": "Joint"})
        assert response.status_code == 201
        assert response.json() == {
            "id": OTHER_WS,
            "name": "Joint",
            "role": "owner",
        }
        names = [w["name"] for w in client.get("/api/me").json()["workspaces"]]
        assert names == ["Test", "Joint"]

    def test_create_rejects_a_blank_name(self, client, db_connection):
        login(client)
        response = client.post("/api/workspaces", json={"name": " "})
        assert response.status_code == 400
        assert repo.get_workspace(db_connection, OTHER_WS) is None

    def test_a_time_zone_field_is_ignored_like_any_unknown_field(
        self, client, db_connection
    ):
        """Workspaces no longer have a zone; the viewer's zone dates saves."""
        login(client)
        created = client.post(
            "/api/workspaces", json={"name": "W", "timezone": "Mars/Olympus"}
        )
        assert created.status_code == 201
        assert "timezone" not in created.json()
        patched = client.patch(
            f"/api/workspaces/{WS}", json={"name": "Renamed", "timezone": "UTC"}
        )
        assert patched.json() == {"id": WS, "name": "Renamed", "role": "owner"}

    def test_delete_hides_it_from_every_member_and_keeps_data(
        self, client, db_connection, ws1
    ):
        add_user(db_connection, STRANGER, "editor")
        login(client)

        assert client.delete(f"/api/workspaces/{WS}").status_code == 200

        assert client.get(ACCOUNTS).status_code == 404
        assert client.get("/api/me").json()["workspaces"] == []
        assert client.get(f"{PAGES}/accounts").status_code == 404
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
        assert client.get(f"{PAGES}/accounts").status_code == 404

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


@pytest.mark.db
class TestInviteEndpoints:
    def _invite(self, client, email: str = STRANGER["email"], role: str = "viewer"):
        login(client)
        response = client.post(
            f"/api/workspaces/{WS}/invites", json={"email": email, "role": role}
        )
        assert response.status_code == 201, response.text
        return response.json()

    def test_an_invitee_sees_accepts_and_gets_the_role(
        self, client, db_connection, ws1
    ):
        add_user(db_connection, STRANGER)
        invite = self._invite(client, STRANGER["email"].upper(), "viewer")
        assert [
            i["id"]
            for i in client.get(f"/api/workspaces/{WS}/invites").json()["invites"]
        ] == [invite["id"]]

        session_for(client, STRANGER)
        mine = client.get("/api/invites").json()["invites"]
        assert [(i["id"], i["workspace_name"], i["role"]) for i in mine] == [
            (invite["id"], "Test", "viewer")
        ]
        accepted = client.post(f"/api/invites/{invite['id']}/accept")
        assert accepted.json() == {"workspace_id": WS, "role": "viewer"}

        assert client.get(ACCOUNTS).status_code == 200
        assert client.post(SNAPSHOTS, json={}).status_code == 403  # viewer
        assert client.get("/api/invites").json()["invites"] == []

    def test_someone_else_cannot_see_or_use_it(self, client, db_connection, ws1):
        add_user(db_connection, STRANGER)
        third = {
            "id": 3,
            "sub": "user-3",
            "email": "third@example.com",
            "name": "Third",
        }
        add_user(db_connection, third)
        invite = self._invite(client)

        session_for(client, third)
        assert client.get("/api/invites").json()["invites"] == []
        assert client.post(f"/api/invites/{invite['id']}/accept").status_code == 404
        assert client.post(f"/api/invites/{invite['id']}/decline").status_code == 404
        assert client.get(ACCOUNTS).status_code == 404

    def test_decline_and_revoke(self, client, db_connection, ws1):
        add_user(db_connection, STRANGER)
        first = self._invite(client)
        session_for(client, STRANGER)
        assert client.post(f"/api/invites/{first['id']}/decline").status_code == 200
        assert client.post(f"/api/invites/{first['id']}/accept").status_code == 404

        second = self._invite(client)
        assert (
            client.delete(f"/api/workspaces/{WS}/invites/{second['id']}").status_code
            == 200
        )
        session_for(client, STRANGER)
        assert client.post(f"/api/invites/{second['id']}/accept").status_code == 404

    def test_another_workspaces_owner_cannot_revoke_it(
        self, client, db_connection, ws1
    ):
        add_user(db_connection, STRANGER)
        create_workspace(db_connection, STRANGER["id"], "Theirs")
        invite = self._invite(client, "friend@example.com")

        session_for(client, STRANGER)
        response = client.delete(f"/api/workspaces/{OTHER_WS}/invites/{invite['id']}")

        assert response.status_code == 404
        assert repo.get_pending_workspace_invites(db_connection, WS) != []

    def test_bad_input_is_400_or_422(self, client, ws1):
        login(client)
        url = f"/api/workspaces/{WS}/invites"
        assert (
            client.post(url, json={"email": "nope", "role": "viewer"}).status_code
            == 400
        )
        assert (
            client.post(url, json={"email": "a@b.com", "role": "admin"}).status_code
            == 422
        )
        assert (
            client.post(
                url, json={"email": USER["email"], "role": "viewer"}
            ).status_code
            == 400
        )


@pytest.mark.db
class TestCashFlowEndpoints:
    BASE = f"/api/workspaces/{WS}"

    def _category(self, client, name: str) -> int:
        response = client.post(f"{self.BASE}/cash-flow-categories", json={"name": name})
        assert response.status_code == 201, response.text
        return response.json()["id"]

    def _flow(self, client, **body) -> dict:
        response = client.post(f"{self.BASE}/cash-flows", json=body)
        assert response.status_code == 201, response.text
        return response.json()

    def test_a_budget_round_trip(self, client):
        login(client)
        housing = self._category(client, "Mortgage Payment")
        subs = self._category(client, "Subscription Services")
        self._flow(
            client,
            name="Take Home Pay",
            direction="income",
            amount="5103.83",
            every=2,
            unit="week",
        )
        rent = self._flow(
            client,
            name="Rent",
            direction="expense",
            amount=3820,
            every=1,
            unit="month",
            category_id=housing,
            description="Monthly mortgage payment",
        )
        self._flow(
            client,
            name="Groceries",
            direction="expense",
            amount="581.00",
            unit="month",
            is_estimate=True,
        )
        self._flow(
            client,
            name="Spotify Premium",
            direction="expense",
            amount="13.00",
            unit="month",
            category_id=subs,
        )
        assert rent["amount"] == "3820.00" and rent["per_day"] == "-125.59"

        body = client.get(f"{self.BASE}/cash-flows").json()

        assert [f["name"] for f in body["cash_flows"]] == [
            "Take Home Pay",
            "Rent",
            "Spotify Premium",
            "Groceries",
        ]
        groceries = body["cash_flows"][-1]
        assert (groceries["is_estimate"], groceries["category_id"]) == (True, None)
        # 364.56 - 125.59 - 0.43 - 19.10, summed unrounded and rounded once.
        assert body["totals"]["net"]["per_day"] == "219.44"
        assert (
            body["totals"]["income"]["per_month"] == "11088.68"
        )  # 5103.83 × 365 / 14 / 12

    def test_patch_changes_only_what_is_sent_and_can_clear(self, client):
        login(client)
        fitness = self._category(client, "Fitness")
        gym = self._flow(
            client,
            name="Gym",
            direction="expense",
            amount="579",
            unit="year",
            category_id=fitness,
            description="Annual",
        )
        url = f"{self.BASE}/cash-flows/{gym['id']}"

        patched = client.patch(url, json={"category_id": None, "is_estimate": True})

        assert patched.status_code == 200
        assert (patched.json()["category_id"], patched.json()["is_estimate"]) == (
            None,
            True,
        )
        assert patched.json()["description"] == "Annual"
        refused = client.patch(url, json={"name": None})
        assert refused.status_code == 400
        assert "name cannot be null" in refused.json()["error"]

    @pytest.mark.parametrize(
        ("body", "status"),
        [
            (
                {"name": "X", "direction": "expense", "amount": "-1", "unit": "month"},
                400,
            ),
            (
                {"name": "X", "direction": "expense", "amount": "NaN", "unit": "month"},
                422,
            ),
            (
                {"name": "X", "direction": "outflow", "amount": "1", "unit": "month"},
                422,
            ),
            (
                {
                    "name": "X",
                    "direction": "expense",
                    "amount": "1",
                    "unit": "fortnight",
                },
                422,
            ),
            (
                {
                    "name": "X",
                    "direction": "expense",
                    "amount": "1",
                    "unit": "month",
                    "every": 0,
                },
                400,
            ),
            (
                {
                    "name": "X",
                    "direction": "expense",
                    "amount": "1",
                    "unit": "month",
                    "category_id": 99,
                },
                400,
            ),
            ({"direction": "expense", "amount": "1", "unit": "month"}, 422),
        ],
    )
    def test_bad_input(self, client, db_connection, body, status):
        login(client)
        response = client.post(f"{self.BASE}/cash-flows", json=body)
        assert response.status_code == status
        assert repo.get_cash_flows(db_connection, WS) == []

    def test_deleting_a_category_keeps_its_flows(self, client):
        login(client)
        fitness = self._category(client, "Fitness")
        gym = self._flow(
            client,
            name="Gym",
            direction="expense",
            amount="85",
            unit="month",
            category_id=fitness,
        )
        assert (
            client.delete(f"{self.BASE}/cash-flow-categories/{fitness}").status_code
            == 200
        )
        flows = client.get(f"{self.BASE}/cash-flows").json()["cash_flows"]
        assert [(f["id"], f["category_id"]) for f in flows] == [(gym["id"], None)]
        assert client.get(f"{self.BASE}/cash-flow-categories").json() == {
            "categories": []
        }

    def test_another_workspaces_category_cannot_be_used(self, client, db_connection):
        add_user(db_connection, STRANGER)
        create_workspace(db_connection, STRANGER["id"], "Theirs")
        login(client)
        mine = self._category(client, "Fitness")

        session_for(client, STRANGER)
        response = client.post(
            f"/api/workspaces/{OTHER_WS}/cash-flows",
            json={
                "name": "Gym",
                "direction": "expense",
                "amount": "1",
                "unit": "month",
                "category_id": mine,
            },
        )

        assert response.status_code == 400
        assert repo.get_cash_flows(db_connection, OTHER_WS) == []

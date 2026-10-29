"""Web tests: real database container plus a signed session cookie."""

import re
from datetime import date
from decimal import Decimal

import pytest
from itsdangerous import URLSafeTimedSerializer

from sensibility.accounts import create_account, retire_account
from sensibility.clock import today
from sensibility.models import RecordType
from sensibility.repository import upsert_amounts
from tests.support import WS
from tests.web_support import (
    ACCOUNTS,
    SECRET,
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


class TestIsEmailAllowed:
    @pytest.fixture(autouse=True)
    def _clean(self, monkeypatch):
        monkeypatch.delenv("ALLOWED_EMAILS", raising=False)
        monkeypatch.delenv("ENV", raising=False)

    @staticmethod
    def allowed(email):
        from sensibility.web.auth import is_email_allowed

        return is_email_allowed(email)

    def test_dev_with_no_allowlist_is_open(self, monkeypatch):
        monkeypatch.setenv("ENV", "dev")
        assert self.allowed("anyone@example.com")
        assert self.allowed(None)

    @pytest.mark.parametrize(
        "env",
        [None, "", "prod", "staging", "Dev", "DEV", " dev", "dev ", "development"],
    )
    @pytest.mark.parametrize("raw", [None, "", " ", ",", " , "])
    def test_anything_but_exactly_dev_with_no_allowlist_is_closed(
        self, monkeypatch, env, raw
    ):
        if env is not None:
            monkeypatch.setenv("ENV", env)
        if raw is not None:
            monkeypatch.setenv("ALLOWED_EMAILS", raw)
        assert not self.allowed("me@example.com")
        assert not self.allowed(None)

    @pytest.mark.parametrize("env", ["dev", "prod"])
    def test_a_set_allowlist_applies_in_dev_too(self, monkeypatch, env):
        monkeypatch.setenv("ENV", env)
        monkeypatch.setenv("ALLOWED_EMAILS", "me@example.com")
        assert self.allowed("me@example.com")
        assert not self.allowed("stranger@example.com")

    @pytest.mark.parametrize(
        "email", ["me@example.com", "ME@EXAMPLE.COM", "other@example.com"]
    )
    def test_listed_emails_match_case_insensitively(self, monkeypatch, email):
        monkeypatch.setenv("ENV", "prod")
        monkeypatch.setenv("ALLOWED_EMAILS", " Me@Example.com ,other@example.com,")
        assert self.allowed(email)

    @pytest.mark.parametrize(
        "email",
        [
            None,
            "",
            "stranger@example.com",
            "me@example.co",
            "me@example.com.evil.com",
            "evil-me@example.com",
            "me@example",
            "me",
            "example.com",
            "me@example.com,other@example.com",
            "me@example.com ",
            " me@example.com",
        ],
    )
    def test_only_exact_matches_are_allowed(self, monkeypatch, email):
        monkeypatch.setenv("ENV", "prod")
        monkeypatch.setenv("ALLOWED_EMAILS", "me@example.com,other@example.com")
        assert not self.allowed(email)


@pytest.mark.parametrize("env", ["staging", "prod"])
def test_deployed_environments_set_an_allowlist(env):
    """Without it a deployed app refuses everyone, so it must stay in config."""
    from pathlib import Path

    manifest = Path(__file__).parent.parent / "k8s" / env / "configmap-env.yaml"
    match = re.search(r'^\s+ALLOWED_EMAILS:\s*"([^"]*)"', manifest.read_text(), re.M)
    assert match is not None
    assert "ethanpswan@gmail.com" in match.group(1).split(",")


@pytest.mark.db
class TestTheme:
    def test_the_login_page_carries_both_themes(self, client):
        """The React app's themes: test_spa.py checks its tokens match these."""
        text = client.get("/login").text
        assert "color-scheme: light" in text
        assert "@media (prefers-color-scheme: dark)" in text
        assert "color-scheme: dark" in text

    def test_templates_name_tokens_not_colors(self):
        """Templates other than base.html (login.html) take their colors from
        base.html's tokens, so light and dark stay in step."""
        from importlib import resources

        templates = resources.files("sensibility.web").joinpath("templates")
        pages = [
            t
            for t in templates.iterdir()
            if t.name.endswith(".html") and t.name != "base.html"
        ]
        assert [t.name for t in pages] == ["login.html"]
        for page in pages:
            colors = re.findall(
                r"#[0-9A-Fa-f]{6}\b|#[0-9A-Fa-f]{3}\b", page.read_text()
            )
            assert colors == [], page.name


@pytest.mark.db
class TestApi:
    def _setup(self, conn):
        from sensibility.models import ProportionalFormula

        schwab = create_account(conn, WS, "Schwab", RecordType.ASSET)
        cash = create_account(conn, WS, "Cash", RecordType.ASSET)
        tax = create_account(
            conn,
            WS,
            "Tax",
            RecordType.LIABILITY,
            ProportionalFormula(rate=Decimal("0.15"), cost_basis=Decimal("100")),
            [schwab.id],
        )
        old = create_account(conn, WS, "Old", RecordType.ASSET)
        upsert_amounts(
            conn,
            WS,
            date(2026, 9, 1),
            {
                schwab.id: Decimal("1000"),
                cash.id: Decimal("50"),
                tax.id: Decimal("135"),
                old.id: Decimal("7"),
            },
        )
        retire_account(conn, WS, old.id, date(2026, 9, 2))
        conn.commit()
        return schwab, cash, tax

    def test_accounts_lists_active_accounts_with_latest_amounts(
        self, client, db_connection
    ):
        schwab, cash, tax = self._setup(db_connection)
        login(client)

        response = client.get(ACCOUNTS)

        assert response.status_code == 200
        body = response.json()
        assert body["as_of"] == "2026-09-01"
        by_name = {a["name"]: a for a in body["accounts"]}
        assert set(by_name) == {"Schwab", "Cash", "Tax"}
        assert by_name["Schwab"] == {
            "id": schwab.id,
            "name": "Schwab",
            "type": "asset",
            "category": None,
            "computed": False,
            "formula": None,
            "input_ids": [],
            "amount": "1000.00",
        }
        assert by_name["Tax"]["computed"] is True
        assert by_name["Tax"]["input_ids"] == [schwab.id]
        assert by_name["Tax"]["formula"]["cost_basis"] == "100"

    def test_accounts_with_no_snapshots(self, client, db_connection):
        create_account(db_connection, WS, "Cash", RecordType.ASSET)
        login(client)
        body = client.get(ACCOUNTS).json()
        assert body["as_of"] is None
        assert [a["amount"] for a in body["accounts"]] == [None]

    def test_snapshot_merges_with_latest_and_reports_sources(
        self, client, db_connection
    ):
        schwab, cash, tax = self._setup(db_connection)
        login(client)

        response = client.post(SNAPSHOTS, json={"values": {str(schwab.id): "2000"}})

        assert response.status_code == 200
        body = response.json()
        assert body["date"] == today(TZ).isoformat()
        assert body["count"] == 3
        got = {a["name"]: (a["amount"], a["source"]) for a in body["accounts"]}
        assert got == {
            "Schwab": ("2000.00", "updated"),
            "Cash": ("50.00", "carried_forward"),
            "Tax": ("285.00", "computed"),
        }

    def test_snapshot_error_returns_400_and_writes_nothing(self, client, db_connection):
        from sensibility.repository import get_all_records

        _, _, tax = self._setup(db_connection)
        before = get_all_records(db_connection, WS)
        login(client)

        response = client.post(SNAPSHOTS, json={"values": {str(tax.id): "1"}})

        assert response.status_code == 400
        assert "is computed" in response.json()["error"]
        assert get_all_records(db_connection, WS) == before

    def test_a_first_save_needs_every_value(self, client, db_connection):
        from sensibility.repository import get_all_records

        create_account(db_connection, WS, "Cash", RecordType.ASSET)
        db_connection.commit()
        login(client)

        response = client.post(SNAPSHOTS, json={"values": {}})

        assert (response.status_code, response.json()) == (
            400,
            {"error": "Missing value for Cash"},
        )
        assert get_all_records(db_connection, WS) == []

    def test_an_amount_too_large_to_store_is_a_400(self, client, db_connection):
        from sensibility.repository import get_all_records

        schwab, _, _ = self._setup(db_connection)
        before = get_all_records(db_connection, WS)
        login(client)

        for amount in ("10000000000000", "1e999"):
            response = client.post(SNAPSHOTS, json={"values": {str(schwab.id): amount}})
            assert response.status_code == 400, amount
            assert "too large" in response.json()["error"], amount
        assert get_all_records(db_connection, WS) == before

    def test_require_login_without_json_accept_header(self, client):
        assert client.get(ACCOUNTS).status_code == 401
        assert client.post(SNAPSHOTS, json={}).status_code == 401

    def test_snapshot_accepts_json_numbers_without_float_error(
        self, client, db_connection
    ):
        schwab, cash, _ = self._setup(db_connection)
        login(client)
        response = client.post(
            SNAPSHOTS,
            json={"values": {str(schwab.id): 2000.1, str(cash.id): 0.29}},
        )
        assert response.status_code == 200
        got = {a["name"]: a["amount"] for a in response.json()["accounts"]}
        assert got["Schwab"] == "2000.10"
        assert got["Cash"] == "0.29"

    @pytest.mark.parametrize(
        ("body", "status"),
        [
            ({"values": {"abc": "1"}}, 422),
            ({"values": {"SCHWAB": "lots"}}, 422),
            ({"values": {"SCHWAB": None}}, 422),
            ({"values": ["SCHWAB", "1"]}, 422),
            ({"values": {"SCHWAB": "NaN"}}, 422),
            ({"values": {"SCHWAB": "Infinity"}}, 422),
            ({"values": {"999999": "1"}}, 400),
            ({"cost_bases": {"TAX": "-Infinity"}}, 422),
        ],
    )
    def test_snapshot_rejects_bad_payloads_and_writes_nothing(
        self, client, db_connection, body, status
    ):
        import json

        from sensibility.repository import get_account, get_all_records

        schwab, _, tax = self._setup(db_connection)
        text = json.dumps(body)
        text = text.replace("SCHWAB", str(schwab.id)).replace("TAX", str(tax.id))
        before = get_all_records(db_connection, WS)
        login(client)

        response = client.post(
            SNAPSHOTS,
            content=text,
            headers={"Content-Type": "application/json"},
        )

        assert response.status_code == status
        assert get_all_records(db_connection, WS) == before
        loaded = get_account(db_connection, WS, tax.id)
        assert loaded is not None and loaded.formula is not None
        assert loaded.formula.cost_basis == Decimal("100")


@pytest.mark.db
def test_api_docs_are_public(client):
    for path in ("/docs", "/redoc"):
        response = client.get(path)
        assert response.status_code == 200, path
        assert "/openapi.json" in response.text, path
    schema = client.get("/openapi.json")
    assert schema.status_code == 200
    assert {
        "/api/workspaces/{workspace_id}/accounts",
        "/api/workspaces/{workspace_id}/snapshots",
    } <= set(schema.json()["paths"])


def assert_nothing_written(conn, account_id: int) -> None:
    from sensibility.repository import get_account, get_all_records

    assert get_all_records(conn, WS) == []
    loaded = get_account(conn, WS, account_id)
    assert loaded is not None and loaded.is_active and loaded.name == "Cash"


@pytest.mark.db
class TestEveryRouteRequiresLogin:
    def test_the_sweep_sees_every_route_family(self, client):
        paths = {path for _, path in protected_routes()}
        api = f"/api/workspaces/{WS}"
        assert {
            "/api/me",
            ACCOUNTS,
            SNAPSHOTS,
            f"{api}/dashboard",
            f"{api}/accounts/overview",
            f"{api}/accounts/1/retire",
            f"{api}/cash-flows/overview",
            f"{api}/settings",
        } <= paths
        # Every protected route is the API's: the pages are the React app's,
        # public shells that load their data from these.
        assert {p for p in paths if not p.startswith("/api/")} == set()

    def test_logged_out_requests_are_refused_and_write_nothing(
        self, client, db_connection
    ):
        cash = create_account(db_connection, WS, "Cash", RecordType.ASSET)
        db_connection.commit()
        assert cash.id == 1  # the sweep substitutes 1 for {account_id}

        statuses = sweep(client)

        assert {k: v for k, v in statuses.items() if v != 401} == {}
        assert_nothing_written(db_connection, cash.id)

    def test_cookie_signed_with_another_key_is_refused(self, client):
        forged = URLSafeTimedSerializer("not-the-secret").dumps(USER)
        client.cookies.set("session", forged)
        assert client.get(ACCOUNTS).status_code == 401

    def test_tampered_cookie_is_refused(self, client):
        good = URLSafeTimedSerializer(SECRET).dumps(USER)
        payload, rest = good.split(".", 1)
        client.cookies.set("session", payload[:-1] + "A" + "." + rest)
        assert client.get(ACCOUNTS).status_code == 401

    def test_expired_cookie_is_refused(self, client, monkeypatch):
        import time

        from itsdangerous import TimestampSigner

        from sensibility.web.auth import SESSION_MAX_AGE

        old = int(time.time()) - SESSION_MAX_AGE - 60
        # A scoped patch: monkeypatch.undo() would also revert the client
        # fixture's environment, including DATABASE_URL.
        with monkeypatch.context() as clock:
            clock.setattr(TimestampSigner, "get_timestamp", lambda self: old)
            cookie = URLSafeTimedSerializer(SECRET).dumps(USER)
        client.cookies.set("session", cookie)
        assert client.get(ACCOUNTS).status_code == 401


@pytest.mark.db
class TestEveryRouteRequiresAnAllowedEmail:
    """A validly signed session is not enough: the email must be allowed."""

    @pytest.fixture
    def cash(self, db_connection):
        # The stranger is a real user and even an owner of the workspace, so
        # the allowlist is the only thing that can refuse them.
        add_user(db_connection, STRANGER, "owner")
        cash = create_account(db_connection, WS, "Cash", RecordType.ASSET)
        db_connection.commit()
        assert cash.id == 1  # the sweep substitutes 1 for {account_id}
        return cash

    @pytest.mark.parametrize(
        ("env", "allowlist", "user"),
        [
            # Another identity user, with the allowlist set as in prod.
            ("prod", USER["email"], STRANGER),
            ("staging", USER["email"], STRANGER),
            # The real user, but the allowlist was lost from config.
            ("prod", None, USER),
            ("prod", "", USER),
            ("staging", None, USER),
            # Dev is only open when the allowlist is blank.
            ("dev", USER["email"], STRANGER),
            # Validly signed, but not a session for any current user.
            ("prod", USER["email"], {k: v for k, v in USER.items() if k != "id"}),
            ("prod", USER["email"], {**USER, "id": 99}),
            ("prod", USER["email"], {**USER, "id": "1"}),
            ("prod", USER["email"], {**USER, "sub": "someone-else"}),
            ("prod", USER["email"], {**STRANGER, "id": USER["id"]}),
        ],
    )
    def test_every_route_refuses_and_writes_nothing(
        self, client, db_connection, monkeypatch, cash, env, allowlist, user
    ):
        monkeypatch.setenv("ENV", env)
        if allowlist is not None:
            monkeypatch.setenv("ALLOWED_EMAILS", allowlist)
        session_for(client, user)

        statuses = sweep(client)

        assert {k: v for k, v in statuses.items() if v != 401} == {}
        assert_nothing_written(db_connection, cash.id)

    def test_the_allowed_user_gets_through_every_route(self, client, monkeypatch, cash):
        """Control: the refusals above are the allowlist, not a broken sweep."""
        monkeypatch.setenv("ENV", "prod")
        monkeypatch.setenv(
            "ALLOWED_EMAILS", f"other@example.com,{USER['email'].upper()}"
        )
        session_for(client, USER)

        statuses = sweep(client)

        assert {k: v for k, v in statuses.items() if v == 401} == {}

    def test_removing_an_email_locks_out_its_live_session(
        self, client, monkeypatch, cash
    ):
        monkeypatch.setenv("ENV", "prod")
        monkeypatch.setenv("ALLOWED_EMAILS", USER["email"])
        session_for(client, USER)
        assert client.get(ACCOUNTS).status_code == 200

        monkeypatch.setenv("ALLOWED_EMAILS", "someone-else@example.com")

        assert set(sweep(client).values()) == {401}


@pytest.mark.db
class TestCallback:
    def _use(self, monkeypatch, idp):
        from types import SimpleNamespace

        import sensibility.web.app as app_module

        monkeypatch.setattr(
            app_module, "get_oauth_client", lambda: SimpleNamespace(idp=idp)
        )

    def _session_cookie(self, response) -> str | None:
        for header in response.headers.get_list("set-cookie"):
            if header.startswith("session="):
                return header
        return None

    def test_login_sets_a_session_that_authenticates(
        self, client, db_connection, monkeypatch
    ):
        self._use(monkeypatch, FakeIdp(token={"userinfo": claims(USER)}))

        response = client.get("/auth/callback", follow_redirects=False)

        assert response.status_code == 302
        assert response.headers["location"] == "/"
        header = self._session_cookie(response)
        assert header is not None
        assert "HttpOnly" in header and "samesite=lax" in header.lower()
        assert "Secure" not in header  # ENV=dev
        assert client.get(ACCOUNTS).status_code == 200

    def test_session_cookie_is_secure_outside_dev(self, client, monkeypatch):
        self._use(monkeypatch, FakeIdp(token={"userinfo": claims(USER)}))
        monkeypatch.setenv("ENV", "prod")
        monkeypatch.setenv("ALLOWED_EMAILS", USER["email"])
        response = client.get("/auth/callback", follow_redirects=False)
        header = self._session_cookie(response)
        assert header is not None and "Secure" in header

    def test_falls_back_to_the_userinfo_endpoint(self, client, monkeypatch):
        self._use(monkeypatch, FakeIdp(token={}, userinfo=claims(USER)))
        response = client.get("/auth/callback", follow_redirects=False)
        assert response.status_code == 302
        assert self._session_cookie(response) is not None

    @pytest.mark.parametrize("email", ["stranger@example.com", None])
    def test_allowlist_refuses_with_403_and_no_session(
        self, client, monkeypatch, email
    ):
        self._use(monkeypatch, FakeIdp(token={"userinfo": claims(USER, email=email)}))
        monkeypatch.setenv("ALLOWED_EMAILS", "me@example.com")

        response = client.get("/auth/callback", follow_redirects=False)

        assert response.status_code == 403
        assert self._session_cookie(response) is None
        assert client.get(ACCOUNTS).status_code == 401

    def test_login_is_refused_outside_dev_without_an_allowlist(
        self, client, monkeypatch
    ):
        self._use(monkeypatch, FakeIdp(token={"userinfo": claims(USER)}))
        monkeypatch.setenv("ENV", "prod")

        response = client.get("/auth/callback", follow_redirects=False)

        assert response.status_code == 403
        assert self._session_cookie(response) is None

    def test_refusal_also_applies_to_the_userinfo_fallback(self, client, monkeypatch):
        self._use(monkeypatch, FakeIdp(token={}, userinfo=claims(STRANGER)))
        monkeypatch.setenv("ALLOWED_EMAILS", USER["email"])

        response = client.get("/auth/callback", follow_redirects=False)

        assert response.status_code == 403
        assert self._session_cookie(response) is None

    def test_allowed_email_logs_in_regardless_of_case(self, client, monkeypatch):
        self._use(monkeypatch, FakeIdp(token={"userinfo": claims(USER)}))
        monkeypatch.setenv("ENV", "prod")
        monkeypatch.setenv("ALLOWED_EMAILS", USER["email"].upper())

        response = client.get("/auth/callback", follow_redirects=False)

        assert response.status_code == 302
        assert self._session_cookie(response) is not None

    def test_oauth_error_is_400_with_no_session(self, client, monkeypatch):
        from authlib.integrations.starlette_client import OAuthError

        self._use(monkeypatch, FakeIdp(error=OAuthError(error="access_denied")))

        response = client.get("/auth/callback", follow_redirects=False)

        assert response.status_code == 400
        assert self._session_cookie(response) is None

    def test_logout_clears_the_session(self, client, monkeypatch):
        # Log in through the callback so the client holds the cookie exactly
        # as the server set it; one set by hand is never matched for deletion.
        self._use(monkeypatch, FakeIdp(token={"userinfo": claims(USER)}))
        client.get("/auth/callback", follow_redirects=False)
        assert client.get(ACCOUNTS).status_code == 200

        response = client.get("/logout", follow_redirects=False)
        assert response.status_code == 302
        header = self._session_cookie(response)
        assert header is not None and "Max-Age=0" in header
        assert client.get(ACCOUNTS).status_code == 401

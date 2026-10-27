"""The login page (board X): logged out, an email not on the allowlist, an
unverified email, and switching to a different identity account."""

import html as html_lib
import re
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest

from tests.web_support import ACCOUNTS, STRANGER, USER, FakeIdp, claims

END_SESSION = "https://identity.example.com/oauth/logout"


def _text(html: str) -> str:
    body = re.sub(r"<style.*?</style>|<script.*?</script>", "", html, flags=re.S)
    return html_lib.unescape(" ".join(re.sub(r"<[^>]+>", " ", body).split()))


def _use(monkeypatch, idp):
    import asset_manager.web.app as app_module

    monkeypatch.setattr(
        app_module, "get_oauth_client", lambda: SimpleNamespace(idp=idp)
    )


def _broken_idp(monkeypatch):
    import asset_manager.web.app as app_module

    def broken():
        raise RuntimeError("IDP_URL environment variable is required")

    monkeypatch.setattr(app_module, "get_oauth_client", broken)


def _session_cookie(response) -> str | None:
    for header in response.headers.get_list("set-cookie"):
        if header.startswith("session="):
            return header
    return None


@pytest.mark.db
class TestLoginPage:
    def test_logged_out_card(self, client, monkeypatch):
        _use(monkeypatch, FakeIdp())
        response = client.get("/login")
        assert response.status_code == 200
        text = _text(response.text)
        assert "Asset Manager" in text
        assert "What you own, what you owe." in text
        assert "Track your net worth and where your money goes" in text
        assert re.search(r'<a [^>]*href="/auth/start"[^>]*>Log in</a>', response.text)
        assert "<title>Log in · Asset Manager</title>" in response.text

    def test_footnote_names_the_identity_host(self, client, monkeypatch):
        _use(monkeypatch, FakeIdp())
        text = _text(client.get("/login").text)
        assert (
            "You'll sign in with your identity.example.com account and come straight back."
            in text
        )

    def test_footnote_is_generic_when_identity_is_unreachable(
        self, client, monkeypatch
    ):
        _broken_idp(monkeypatch)
        response = client.get("/login")
        assert response.status_code == 200
        text = _text(response.text)
        assert "identity.example.com" not in text
        assert "You'll sign in with your account and come straight back." in text

    def test_is_on_the_design_system_without_the_shell(self, client, monkeypatch):
        _use(monkeypatch, FakeIdp())
        html = client.get("/login").text
        # base.html's tokens, in both themes; none of the old palette.
        assert "--surface: #FFFFFF" in html and "color-scheme: dark" in html
        assert "accent-gold" not in html.split("Legacy aliases")[0]
        assert "DM Serif" not in html
        # No shell: no nav, no workspace picker, no user menu.
        assert "main-nav" not in html.split("</style>")[1]
        assert "Workspace" not in _text(html)
        assert "/logout" not in html


@pytest.mark.db
class TestRefusedLogin:
    def test_not_allowed_renders_the_page_with_403(self, client, monkeypatch):
        _use(monkeypatch, FakeIdp(token={"userinfo": claims(STRANGER)}))
        monkeypatch.setenv("ALLOWED_EMAILS", USER["email"])
        response = client.get("/auth/callback", follow_redirects=False)
        assert response.status_code == 403
        assert response.headers["content-type"].startswith("text/html")
        text = _text(response.text)
        assert "This account isn't on the list yet" in text
        assert "stranger@example.com can't use Asset Manager yet." in text
        assert "Access is invite-only for now." in text
        assert re.search(
            r'<a [^>]*href="/auth/switch"[^>]*>Log in with a different account</a>',
            response.text,
        )
        assert _session_cookie(response) is None
        assert client.get(ACCOUNTS).status_code == 401

    def test_the_email_is_escaped(self, client, monkeypatch):
        evil = {**STRANGER, "email": "<b>x</b>@example.com"}
        _use(monkeypatch, FakeIdp(token={"userinfo": claims(evil)}))
        monkeypatch.setenv("ALLOWED_EMAILS", USER["email"])
        html = client.get("/auth/callback").text
        assert "<b>x</b>" not in html
        assert "&lt;b&gt;x&lt;/b&gt;@example.com" in html

    def test_not_allowed_without_an_email(self, client, monkeypatch):
        _use(monkeypatch, FakeIdp(token={"userinfo": claims(USER, email=None)}))
        monkeypatch.setenv("ALLOWED_EMAILS", USER["email"])
        response = client.get("/auth/callback")
        assert response.status_code == 403
        text = _text(response.text)
        assert "This account can't use Asset Manager yet." in text
        assert "None" not in text

    def test_no_email_is_refused_even_where_everyone_is_allowed(
        self, client, monkeypatch
    ):
        # ENV=dev with no ALLOWED_EMAILS lets any email in, but never none.
        _use(monkeypatch, FakeIdp(token={"userinfo": claims(USER, email=None)}))
        response = client.get("/auth/callback", follow_redirects=False)
        assert response.status_code == 403
        assert "This account can't use Asset Manager yet." in _text(response.text)
        assert _session_cookie(response) is None

    @pytest.mark.parametrize("verified", [False, None, "true"])
    def test_unverified_email(self, client, monkeypatch, verified):
        info = claims(USER)
        if verified is None:
            del info["email_verified"]
        else:
            info["email_verified"] = verified
        _use(monkeypatch, FakeIdp(token={"userinfo": info}))
        monkeypatch.setenv("ALLOWED_EMAILS", USER["email"])
        response = client.get("/auth/callback", follow_redirects=False)
        assert response.status_code == 403
        text = _text(response.text)
        assert "Verify your email first" in text
        assert f"{USER['email']} isn't verified yet." in text
        assert "isn't on the list" not in text
        assert re.search(
            r'<a [^>]*href="/auth/start"[^>]*>Log in again</a>', response.text
        )
        assert 'href="/auth/switch"' in response.text
        assert _session_cookie(response) is None

    def test_an_email_neither_allowed_nor_verified_reads_as_not_allowed(
        self, client, monkeypatch
    ):
        info = claims(STRANGER, email_verified=False)
        _use(monkeypatch, FakeIdp(token={"userinfo": info}))
        monkeypatch.setenv("ALLOWED_EMAILS", USER["email"])
        text = _text(client.get("/auth/callback").text)
        assert "This account isn't on the list yet" in text


@pytest.mark.db
class TestSwitchAccount:
    def test_logs_out_here_and_at_identity_then_returns_to_the_callback(
        self, client, monkeypatch
    ):
        _use(monkeypatch, FakeIdp())
        response = client.get("/auth/switch", follow_redirects=False)
        assert response.status_code == 302
        url = urlsplit(response.headers["location"])
        assert f"{url.scheme}://{url.netloc}{url.path}" == END_SESSION
        assert parse_qs(url.query) == {
            "client_id": ["test-client"],
            "post_logout_redirect_uri": ["http://testserver/auth/callback"],
        }
        header = _session_cookie(response)
        assert header is not None and "Max-Age=0" in header

    def test_the_trip_back_from_identity_starts_a_fresh_login(
        self, client, monkeypatch
    ):
        _use(monkeypatch, FakeIdp())
        client.get("/auth/switch", follow_redirects=False)
        # identity redirects to the callback with no code.
        response = client.get("/auth/callback", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == "/auth/start"
        # Only once: a second bare callback is an ordinary (refused) login.
        _use(monkeypatch, FakeIdp(token={}, userinfo={}))
        again = client.get("/auth/callback", follow_redirects=False)
        assert again.status_code == 403

    def test_a_code_after_switching_still_logs_in(self, client, monkeypatch):
        _use(monkeypatch, FakeIdp(token={"userinfo": claims(USER)}))
        client.get("/auth/switch", follow_redirects=False)
        response = client.get("/auth/callback?code=abc&state=s", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == "/"
        assert _session_cookie(response) is not None

    def test_without_an_end_session_endpoint_goes_to_login(self, client, monkeypatch):
        idp = FakeIdp()
        del idp.server_metadata["end_session_endpoint"]
        _use(monkeypatch, idp)
        response = client.get("/auth/switch", follow_redirects=False)
        assert response.headers["location"] == "/login"
        assert "Max-Age=0" in (_session_cookie(response) or "")

    def test_with_identity_unreachable_goes_to_login(self, client, monkeypatch):
        _broken_idp(monkeypatch)
        response = client.get("/auth/switch", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == "/login"
        assert "Max-Age=0" in (_session_cookie(response) or "")

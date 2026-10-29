"""Real-browser tests: the app under uvicorn, driven by Playwright's Chromium.

The server runs in a subprocess against the session's test container, so it
shares nothing with the in-process TestClient tests (no settings cache, no
environment). Each test still gets the usual seeded database from
`db_connection`, and logs in by carrying the signed session cookie.
"""

import os
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import httpx
import pytest

from itsdangerous import URLSafeTimedSerializer
from playwright.sync_api import Browser, BrowserContext, Error, Page

from sensibility.accounts import create_account
from sensibility.models import ProportionalFormula, RecordType
from sensibility.repository import upsert_amounts
from tests.support import SEED_USER, WS
from tests.web_support import SECRET, TZ, USER


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
# What a build depends on: newer than dist/index.html means rebuild.
_BUILD_INPUTS = ("src", "public", "index.html", "package.json", "package-lock.json")


def _newest_input() -> float:
    newest = 0.0
    for name in [*_BUILD_INPUTS, *(p.name for p in FRONTEND.glob("*.config.*"))]:
        path = FRONTEND / name
        files = path.rglob("*") if path.is_dir() else [path]
        newest = max([newest, *(f.stat().st_mtime for f in files if f.is_file())])
    return newest


@pytest.fixture(scope="session")
def spa_dist() -> Path:
    """frontend/dist, built if it is missing or older than its sources (CI
    builds it in an earlier step, so this finds it fresh). Needs npm."""
    dist = FRONTEND / "dist"
    index = dist / "index.html"
    if index.is_file() and index.stat().st_mtime >= _newest_input():
        return dist
    npm = shutil.which("npm")
    if npm is None:
        pytest.fail(
            "The browser tests need the React app built, and npm is not on PATH.\n"
            "    cd frontend && npm ci && npm run build",
            pytrace=False,
        )
    steps = [[npm, "run", "build"]]
    if not (FRONTEND / "node_modules").is_dir():
        steps.insert(0, [npm, "ci"])
    for step in steps:
        result = subprocess.run(step, cwd=FRONTEND, capture_output=True, text=True)
        if result.returncode != 0:
            pytest.fail(
                f"{' '.join(step[1:])} failed in frontend/:\n"
                f"{result.stdout}\n{result.stderr}",
                pytrace=False,
            )
    return dist


@pytest.fixture(scope="session")
def server_url(db_url, _run_migrations, spa_dist, tmp_path_factory) -> Iterator[str]:
    """The app under uvicorn on a free port, for the whole session, serving
    the built React app from the root."""
    port = _free_port()
    env = {
        **os.environ,
        "SPA_DIST": str(spa_dist),
        "DATABASE_URL": db_url,
        "SECRET_KEY": SECRET,
        # dev: cookies without Secure, since this is plain http.
        "ENV": "dev",
        "ALLOWED_EMAILS": SEED_USER["email"],
        "TIMEZONE": TZ,
    }
    log = tmp_path_factory.mktemp("server") / "uvicorn.log"
    with log.open("w") as out:
        # Run from an empty directory so no .env.dev is picked up.
        proc = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "sensibility.web.app:app"]
            + ["--host", "127.0.0.1", "--port", str(port)],
            cwd=log.parent,
            env=env,
            stdout=out,
            stderr=subprocess.STDOUT,
        )
    url = f"http://127.0.0.1:{port}"
    try:
        deadline = time.monotonic() + 20
        while True:
            try:
                if httpx.get(f"{url}/health").status_code == 200:
                    break
            except httpx.TransportError:
                pass
            if proc.poll() is not None or time.monotonic() > deadline:
                pytest.fail(f"uvicorn did not start:\n{log.read_text()}")
            time.sleep(0.1)
        yield url
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.fixture(scope="session")
def _chromium_installed(playwright) -> None:
    path = Path(playwright.chromium.executable_path)
    if not path.exists():
        pytest.fail(
            "Chromium for Playwright is not installed. Run:\n"
            "    uv run playwright install chromium\n"
            "(add --with-deps on a fresh Linux machine).",
            pytrace=False,
        )


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args, _chromium_installed):
    return browser_type_launch_args


OpenPage = Callable[..., Page]


@pytest.fixture
def open_page(browser: Browser, server_url: str, db_connection) -> Iterator[OpenPage]:
    """Open a logged-in page at `path`, in a fresh context (own cookies and
    sessionStorage) with the given time zone. db_connection seeds and cleans
    the database around the test. Any uncaught JavaScript error fails it.

    `phone=390` opens it as a phone of that width instead of a 1280px desktop:
    touch, a mobile viewport, 2x pixels (see tests/browser/mobile.py)."""
    contexts: list[BrowserContext] = []
    errors: list[str] = []

    def open_(
        path: str, *, timezone_id: str = TZ, user: dict = USER, phone: int | None = None
    ) -> Page:
        screen = (
            {
                "viewport": {"width": phone, "height": 844},
                "is_mobile": True,
                "has_touch": True,
                "device_scale_factor": 2,
            }
            if phone
            else {"viewport": {"width": 1280, "height": 900}}
        )
        context = browser.new_context(
            base_url=server_url, timezone_id=timezone_id, locale="en-US", **screen
        )
        context.set_default_timeout(5000)
        context.add_cookies(
            [
                {
                    "name": "session",
                    "value": URLSafeTimedSerializer(SECRET).dumps(user),
                    "url": server_url,
                }
            ]
        )
        contexts.append(context)
        page = context.new_page()
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(path)
        return page

    yield open_
    for context in contexts:
        try:
            context.close()
        except Error:
            pass
    assert not errors, f"JavaScript errors on the page: {errors}"


SAVED_ON = date(2026, 9, 27)  # in the past, so Save does not ask to overwrite


@pytest.fixture
def seeded(db_connection):
    """Checking, Schwab, a card, and a 15% tax on Schwab's gain."""
    conn = db_connection
    checking = create_account(conn, WS, "Checking", RecordType.ASSET)
    schwab = create_account(conn, WS, "Schwab", RecordType.ASSET)
    card = create_account(conn, WS, "Card", RecordType.LIABILITY)
    tax = create_account(
        conn,
        WS,
        "Cap gains tax",
        RecordType.LIABILITY,
        ProportionalFormula(rate=Decimal("0.15"), cost_basis=Decimal("82386.74")),
        [schwab.id],
    )
    upsert_amounts(
        conn,
        WS,
        SAVED_ON,
        {
            checking.id: Decimal("1000.00"),
            schwab.id: Decimal("179265.00"),
            card.id: Decimal("500.00"),
            tax.id: Decimal("14531.74"),
        },
    )
    conn.commit()
    return {"checking": checking, "schwab": schwab, "card": card, "tax": tax}

"""OIDC authentication for the web dashboard."""
from __future__ import annotations

import os
import secrets
from typing import Any

from authlib.integrations.starlette_client import OAuth, OAuthError
from itsdangerous import URLSafeTimedSerializer
from starlette.requests import Request
from starlette.responses import RedirectResponse

# Session cookie configuration
SESSION_COOKIE_NAME = "session"
SESSION_MAX_AGE = 60 * 60 * 24 * 7  # 7 days


def get_secret_key() -> str:
    """Get the secret key for signing sessions."""
    key = os.environ.get("SECRET_KEY")
    if not key:
        raise RuntimeError("SECRET_KEY environment variable is required")
    return key


def get_serializer() -> URLSafeTimedSerializer:
    """Get the session serializer."""
    return URLSafeTimedSerializer(get_secret_key())


def get_oauth() -> OAuth:
    """Create and configure the OAuth client."""
    oauth = OAuth()

    idp_url = os.environ.get("IDP_URL")
    if not idp_url:
        raise RuntimeError("IDP_URL environment variable is required")

    client_id = os.environ.get("CLIENT_ID")
    client_secret = os.environ.get("CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError("CLIENT_ID and CLIENT_SECRET environment variables are required")

    # Register the OIDC provider with auto-discovery
    oauth.register(
        name="idp",
        client_id=client_id,
        client_secret=client_secret,
        server_metadata_url=f"{idp_url}/.well-known/openid-configuration",
        token_endpoint_auth_method="client_secret_post",
        client_kwargs={
            "scope": "openid profile email",
            "code_challenge_method": "S256",
        },
    )

    return oauth


def get_session_user(request: Request) -> dict[str, Any] | None:
    """Get the current user from the session cookie."""
    cookie = request.cookies.get(SESSION_COOKIE_NAME)
    if not cookie:
        return None

    try:
        serializer = get_serializer()
        data = serializer.loads(cookie, max_age=SESSION_MAX_AGE)
        return data
    except Exception:
        return None


def create_session_response(
    redirect_url: str,
    user_data: dict[str, Any],
) -> RedirectResponse:
    """Create a redirect response with a session cookie."""
    serializer = get_serializer()
    session_data = serializer.dumps(user_data)

    response = RedirectResponse(url=redirect_url, status_code=302)
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_data,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        secure=True,
        samesite="lax",
    )
    return response


def clear_session_response(redirect_url: str) -> RedirectResponse:
    """Create a redirect response that clears the session cookie."""
    response = RedirectResponse(url=redirect_url, status_code=302)
    response.delete_cookie(key=SESSION_COOKIE_NAME)
    return response


async def handle_login(request: Request, oauth: OAuth) -> RedirectResponse:
    """Redirect to the IDP for authentication."""
    # Generate redirect URI based on request
    redirect_uri = str(request.url_for("auth_callback"))

    # Generate and store PKCE state
    state = secrets.token_urlsafe(32)

    return await oauth.idp.authorize_redirect(request, redirect_uri, state=state)


async def handle_callback(request: Request, oauth: OAuth) -> RedirectResponse:
    """Handle the OAuth callback and create a session."""
    try:
        token = await oauth.idp.authorize_access_token(request)
    except OAuthError as e:
        raise RuntimeError(f"OAuth error: {e.error}") from e

    # Get user info from the token or userinfo endpoint
    user_info = token.get("userinfo")
    if not user_info:
        # Fetch from userinfo endpoint if not in token
        user_info = await oauth.idp.userinfo(token=token)

    # Create session with user data
    user_data = {
        "sub": user_info.get("sub"),
        "email": user_info.get("email"),
        "name": user_info.get("name") or user_info.get("username"),
    }

    return create_session_response("/", user_data)


def handle_logout() -> RedirectResponse:
    """Clear the session and redirect to home."""
    # For now, just clear local session
    # Could also redirect to IDP logout endpoint
    return clear_session_response("/")

"""Rendering the one server-side page, login.html (every other page is the
React app in frontend/)."""

from __future__ import annotations

from importlib import resources
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

templates_path = resources.files("sensibility.web").joinpath("templates")
templates = Jinja2Templates(directory=str(templates_path))

# The app's name on the login page. Its full name is "Sensibility Money";
# pages use the short form.
APP_NAME = "Sensibility"


def render(
    request: Request, name: str, context: dict[str, Any], status_code: int = 200
) -> HTMLResponse:
    """Render a template with the app's name."""
    return templates.TemplateResponse(
        request, name, {**context, "app_name": APP_NAME}, status_code=status_code
    )

"""Template rendering with one-shot flash messages."""

from __future__ import annotations

from importlib import resources
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

templates_path = resources.files("asset_manager.web").joinpath("templates")
templates = Jinja2Templates(directory=str(templates_path))


def set_flash(request: Request, kind: str, text: str) -> None:
    """Queue a message for the next rendered page. kind is "success" or "error"."""
    request.session["flash"] = {"kind": kind, "text": text}


def pop_flash(request: Request) -> dict[str, str] | None:
    return request.session.pop("flash", None)


def render(
    request: Request, name: str, context: dict[str, Any], status_code: int = 200
) -> HTMLResponse:
    """Render a template with the pending flash message, if any."""
    return templates.TemplateResponse(
        request, name, {**context, "flash": pop_flash(request)}, status_code=status_code
    )

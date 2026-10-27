"""Vercel entrypoint - imports FastAPI app from package."""

from sensibility.web.app import app

__all__ = ["app"]

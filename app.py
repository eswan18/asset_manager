"""Vercel entrypoint - imports FastAPI app from package."""
from asset_manager.web.app import app

__all__ = ["app"]

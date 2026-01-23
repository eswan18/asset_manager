"""Vercel serverless function entry point."""
from asset_manager.web.app import app

# Vercel automatically detects and uses the FastAPI app

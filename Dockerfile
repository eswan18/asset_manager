# The React app (frontend/): built here, served by FastAPI under /app.
FROM node:24-alpine AS frontend

WORKDIR /frontend

# Install dependencies first (cached unless the lockfile changes)
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build

FROM python:3.13-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install dependencies first (cached unless lock/pyproject changes)
COPY uv.lock pyproject.toml README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy source and install the project itself
COPY src/ src/
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.13-slim

RUN useradd --create-home --uid 1000 appuser

WORKDIR /app
COPY --from=builder /app /app
COPY --from=frontend /frontend/dist /app/frontend/dist

ENV PATH="/app/.venv/bin:$PATH"
# Where web/spa.py finds the built React app.
ENV SPA_DIST=/app/frontend/dist

USER appuser

EXPOSE 8000

CMD ["uvicorn", "sensibility.web.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]

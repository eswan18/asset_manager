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

ENV PATH="/app/.venv/bin:$PATH"

USER appuser

EXPOSE 8000

CMD ["uvicorn", "asset_manager.web.app:app", "--host", "0.0.0.0", "--port", "8000"]

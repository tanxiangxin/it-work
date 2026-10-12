FROM ghcr.io/astral-sh/uv:0.11.3 AS uv
FROM python:3.12.14-slim AS runtime
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY app ./app
COPY migrations ./migrations
COPY alembic.ini ./
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

FROM runtime AS test
RUN uv sync --frozen
COPY tests ./tests
CMD ["python", "-m", "pytest", "-q"]

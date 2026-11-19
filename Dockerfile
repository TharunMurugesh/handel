# One image for both processes (api, worker). Multi-arch: builds on ARM (Oracle VM) and AMD.
FROM python:3.12-slim AS build
COPY --from=ghcr.io/astral-sh/uv:0.8.17 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY handel ./handel
RUN uv sync --frozen --no-dev

FROM python:3.12-slim
RUN useradd --create-home --uid 10001 handel
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY handel ./handel
COPY migrations ./migrations
COPY alembic.ini ./
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER handel
EXPOSE 8000
CMD ["uvicorn", "handel.interfaces.http.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]

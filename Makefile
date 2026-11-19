.PHONY: install check lint fmt type contracts test audit up down

install:
	uv sync

check: lint type contracts test

lint:
	uv run ruff check .
	uv run ruff format --check .

fmt:
	uv run ruff check --fix .
	uv run ruff format .

type:
	uv run mypy

contracts:
	uv run lint-imports

test:
	uv run pytest -q --cov --cov-report=term

audit:
	uv run pip-audit --skip-editable

up:
	docker compose up --build -d
	docker compose ps

down:
	docker compose down

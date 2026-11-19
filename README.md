# Handel

An agent that buys raw material and costs quotes for small factories. Tech4Bharat 2026, problem 4.1.

Design docs: [`docs/`](docs/). Start with [`04-implementation-plan.md`](docs/04-implementation-plan.md).

## Quick start

Needs Python 3.12, [uv](https://docs.astral.sh/uv/) and Docker (with Compose v2.24+).

```bash
uv sync                      # install
make check                   # lint, type-check, architecture contracts, tests

cp .env.example .env
docker compose up --build    # Postgres, MinIO, api, worker
curl localhost:8000/health/ready
```

Integration tests need a Postgres:

```bash
HANDEL_TEST_DATABASE_URL=postgresql+asyncpg://handel:handel@localhost:5432/handel make test
```

## Layout (architecture §3)

| Path | What lives there | May import |
|---|---|---|
| `handel/domain/` | State machines, rules engines, policy, models. Pure Python. | stdlib, Pydantic |
| `handel/application/` | Use cases and agent orchestration | domain, ports |
| `handel/ports/` | Interfaces: channel, speech, llm, storage, clock | domain |
| `handel/adapters/` | Implementations: Telegram, Sarvam, LLMs, Postgres, S3, in-memory fakes, fixtures | ports, domain, application |
| `handel/interfaces/` | FastAPI routes and worker entry points | everything |
| `handel/evals/` | Offline evaluation harness (T-1..T-6) | — |
| `prompts/` | Versioned prompts, `prompts/<task>/vN.md` | — |
| `migrations/` | Alembic migrations, each reversible | — |

`lint-imports` enforces the layer order in CI; `tests/unit/test_architecture.py` enforces the domain allow-list.

## Model mode

`HANDEL_MODEL_MODE` controls the LLM and speech ports:

- `replay` (default): recorded fixtures only. A missing fixture is an error. CI always uses this.
- `record`: call the live provider and save the answer to `tests/fixtures/`. Spends free-tier quota.
- `live`: call the live provider, save nothing.

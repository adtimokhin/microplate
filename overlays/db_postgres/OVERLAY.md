# Overlay: db_postgres

Async PostgreSQL for the FastAPI service: SQLAlchemy 2.x + asyncpg engine,
request-scoped session dependency, and an async Alembic migration environment.

- Owner: Data Layer Engineer
- Registry key: `db_postgres` (bool, default `false`)
- Overlay id: `db_postgres`
- Milestone: 3 (Phase 2)
- Decisions: D-004 (async stack), D-010 (uv + pinned deps), D-019 (frozen pins),
  D-027 (`compose.app-deps` slot)
- Research: `research/data-layer.md`

## What it adds

| Surface | Contribution |
| --- | --- |
| Gated subtree | `{{ python_package }}/db/postgres/` - `engine.py` (`init_engine` / `get_engine` / `get_session_factory` / `dispose_engine`, module-level `_engine` + `_session_factory` holders), `session.py` (`get_session` FastAPI dependency, rollback-on-exception), `models.py` (`Base` declarative base) |
| Gated subtree | `migrations/` - `alembic.ini` (no DSN committed), `env.py` (async `run_migrations_online`, `NullPool`, DSN from `APP_DB_POSTGRES_DSN`, `target_metadata = Base.metadata`), `script.py.mako`, `versions/.gitkeep` |
| `pyproject.toml` | `sqlalchemy[asyncio]==2.0.52`, `asyncpg==0.31.0`, `alembic==1.19.2`, `greenlet==3.5.5` |
| `pyproject.toml` dev group | `testcontainers==4.15.0` (only when `tests_integration`) |
| `config/settings.py` | `db_postgres_dsn`, `db_postgres_pool_size` |
| `.env.example` | `APP_DB_POSTGRES_DSN`, `APP_DB_POSTGRES_POOL_SIZE` |
| `lifespan.py` | startup hook (`init_engine()`, mirror to `app.state.db_postgres`), shutdown hook (`dispose_engine()`) |
| `health.py` | `check_db_postgres()` - zero-arg, reads the `_engine` holder, `SELECT 1` on a fresh connection, never raises |
| `docker-compose.yml` | `postgres` service (`postgres:17.6`, `pg_isready` healthcheck) |
| `docker-compose.yml` `app.depends_on` | `postgres: {condition: service_healthy}` via `compose.app-deps.yml` (D-027) |
| `tests/conftest.py` | `postgres_session` (mock: autouse, patches `init_engine` with a spec'd `AsyncMock` so `SELECT 1` succeeds offline), `postgres_container` (testcontainers, only when `tests_integration`) |
| Boots test | `tests/overlays/test_db_postgres_boots.py` |

## Design notes

- Nothing connects at import time. `create_async_engine` is lazy; the lifespan
  startup hook is the only builder. `get_engine()` raises if the lifespan has not
  run, but `check_db_postgres()` wraps every call so readiness never raises.
- `expire_on_commit=False` on the session factory (required under asyncio).
- `pool_pre_ping=True` so dead connections are recycled transparently.
- `engine.dispose()` on shutdown so asyncpg connections are closed on the loop.
- Alembic reads `APP_DB_POSTGRES_DSN` in `env.py` (keep the `+asyncpg` marker);
  the DSN is never written into `alembic.ini`, so no credential is committed.
  Run migrations with `uv run alembic -c migrations/alembic.ini ...`.
- Mock mode is the default (`tests_integration=false`): the autouse
  `postgres_session` fixture installs a spec'd `AsyncMock` engine, so
  `uv run pytest` needs no container and `isinstance(engine, AsyncEngine)` still
  holds. The boots test enters the real lifespan and calls the real health
  check.

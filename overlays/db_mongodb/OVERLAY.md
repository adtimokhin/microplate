# Overlay: db_mongodb

Async MongoDB for the FastAPI service using the PyMongo async API
(`AsyncMongoClient`), no ODM.

- Owner: Data Layer Engineer
- Registry key: `db_mongodb` (bool, default `false`)
- Overlay id: `db_mongodb`
- Milestone: 3 (Phase 2)
- Decisions: D-008 (PyMongo async API, not Motor - Motor EOL 2026-05-14),
  D-004 (async stack), D-019 (frozen pins), D-027 (`compose.app-deps` slot)
- Research: `research/data-layer.md`

## What it adds

| Surface | Contribution |
| --- | --- |
| Gated subtree | `{{ python_package }}/db/mongodb/` - `client.py` (`init_client` / `get_client` / `get_database` / `close_client`, module-level `_client` holder) |
| `pyproject.toml` | `pymongo==4.18.0` |
| `pyproject.toml` dev group | `testcontainers==4.15.0` (only when `tests_integration`) |
| `config/settings.py` | `db_mongodb_uri`, `db_mongodb_database`, `db_mongodb_server_selection_timeout_ms` |
| `.env.example` | `APP_DB_MONGODB_URI`, `APP_DB_MONGODB_DATABASE`, `APP_DB_MONGODB_SERVER_SELECTION_TIMEOUT_MS` |
| `lifespan.py` | startup hook (`init_client()`, mirror to `app.state.db_mongodb`), shutdown hook (`close_client()`) |
| `health.py` | `check_db_mongodb()` - zero-arg, reads the `_client` holder, `admin.command("ping")`, never raises |
| `docker-compose.yml` | `mongodb` service (`mongo:8.0`, `mongosh` ping healthcheck) |
| `docker-compose.yml` `app.depends_on` | `mongodb: {condition: service_healthy}` via `compose.app-deps.yml` (D-027) |
| `tests/conftest.py` | `mongodb_db` (mock: autouse, patches `init_client` with a spec'd `AsyncMock` whose `admin.command` returns `{"ok": 1.0}`), `mongodb_container` (testcontainers, only when `tests_integration`) |
| Boots test | `tests/overlays/test_db_mongodb_boots.py` |

## Design notes

- Client is a process-wide singleton bound to the lifespan. `AsyncMongoClient`
  does not open a socket on construction; the pool is lazy.
- Low `serverSelectionTimeoutMS` (default 3000) so health checks and cold starts
  fail fast when a replica set is down.
- `ping` is the readiness probe: no auth, database-independent, cheap.
- No ODM. Model documents as plain Pydantic v2 classes at the API boundary and
  convert to/from `dict`; map the `ObjectId` `_id` to a string field. Add an
  `ensure_indexes` routine and call it from a startup hook if needed.
- Mock mode is the default: the autouse `mongodb_db` fixture installs a spec'd
  `AsyncMock` client so `uv run pytest` needs no container and
  `isinstance(client, AsyncMongoClient)` still holds.

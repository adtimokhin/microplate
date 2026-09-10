# Overlay: db_redis

Async Redis for the FastAPI service: redis-py asyncio client on a shared
connection pool, a read-through cache helper, and an optional pub/sub helper
(`redis_pubsub` sub-option).

- Owner: Data Layer Engineer
- Registry keys: `db_redis` (bool, default `false`), `redis_pubsub` (bool,
  default `false`, `when: db_redis`)
- Overlay id: `db_redis` (`redis_pubsub` adds files inside the same gated
  subtree; it has no separate overlay id)
- Milestone: 3 (Phase 2)
- Decisions: D-004 (async stack), D-015 + D-023 (redis-stack image for a
  LangGraph Redis checkpoint; pin owned here), D-019 (frozen pins),
  D-027 (`compose.app-deps` slot)
- Research: `research/data-layer.md`

## What it adds

| Surface | Contribution |
| --- | --- |
| Gated subtree | `{{ python_package }}/db/redis/` - `client.py` (`init_client` / `get_client` / `close_client`, module-level `_pool` + `_client` holders, `cache_get_or_set` helper) |
| Gated subtree (`redis_pubsub`) | `{{ python_package }}/db/redis/pubsub.py` - `publish` (reuses the shared client), `subscribe` (dedicated connection, async generator) |
| `pyproject.toml` | `redis==8.1.0` |
| `pyproject.toml` dev group | `testcontainers==4.15.0` (only when `tests_integration`) |
| `config/settings.py` | `redis_url`, `redis_max_connections`, `redis_health_check_interval` |
| `.env.example` | `APP_REDIS_URL`, `APP_REDIS_MAX_CONNECTIONS`, `APP_REDIS_HEALTH_CHECK_INTERVAL` |
| `lifespan.py` | startup hook (`init_client()`, mirror to `app.state.db_redis`), shutdown hook (`close_client()` - closes client and pool) |
| `health.py` | `check_db_redis()` - zero-arg, reads the `_client` holder, `PING`, never raises |
| `docker-compose.yml` | `redis` service - `redis:8.0` by default; `redis/redis-stack:7.4.0-v8` when `langgraph and langgraph_checkpoint == 'redis'` (IR-1 / D-015), which also publishes port 8001 |
| `docker-compose.yml` `app.depends_on` | `redis: {condition: service_healthy}` via `compose.app-deps.yml` (D-027) |
| `tests/conftest.py` | `redis_client` (mock: autouse, patches `init_client` with a spec'd `AsyncMock` whose `ping` returns `True`), `redis_container` (testcontainers, only when `tests_integration`) |
| Boots test | `tests/overlays/test_db_redis_boots.py` (plus a `redis_pubsub` import assertion when the sub-option is on) |

## Design notes

- One shared `redis.asyncio.Redis` + `ConnectionPool` for the process, built by
  the lifespan startup hook. `decode_responses=True` (str values).
- There is no async destructor: shutdown explicitly `aclose()`s both the client
  and the pool or connections leak.
- `health_check_interval` on the pool so connections dropped by idle timeout or
  failover are revived before the next command.
- pub/sub holds a dedicated connection for the lifetime of the `subscribe`
  generator (never multiplex pub/sub and normal commands on one connection).
  Run a long-lived `subscribe` loop as its own task and cancel it on shutdown.
- redis-stack image resolution (IR-1) is currently an inline Jinja branch in
  `_fragments/db_redis/compose.yml.jinja`. When both `db_redis` and a LangGraph
  Redis checkpoint are selected the single compose `redis` service is upgraded to
  `redis/redis-stack` (RedisJSON + RediSearch, required by
  `langgraph-checkpoint-redis`). Verified present on Docker Hub 2026-09-08,
  multi-arch, modules `ReJSON` + `search` confirmed at runtime.
- Mock mode is the default: the autouse `redis_client` fixture installs a spec'd
  `AsyncMock` so `uv run pytest` needs no container and
  `isinstance(client, redis.Redis)` still holds.

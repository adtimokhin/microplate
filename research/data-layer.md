# Data Layer Research

Runtime target: Python 3.12, fully async, FastAPI on uvicorn. Every entry below is an independent, composable overlay. All version numbers verified against PyPI on 2026-09-07. All access dates below are 2026-09-07.

## Summary of pinned versions

| Library | Pinned version | Released | Purpose |
|---|---|---|---|
| SQLAlchemy | 2.0.52 | 2026-08-11 | PostgreSQL ORM + Core, async |
| asyncpg | 0.31.0 | 2025-11-24 | PostgreSQL async driver |
| alembic | 1.19.2 | 2026-09-04 | PostgreSQL migrations, async env |
| pymongo | 4.18.0 | 2026-09-03 | MongoDB, native async API (AsyncMongoClient) |
| beanie | 2.2.0 | 2026-08-07 | Optional MongoDB ODM overlay |
| redis (redis-py) | 8.1.0 | 2026-07-30 | Redis async client, cache + pub/sub |
| qdrant-client | 1.19.0 | 2026-08-04 | Qdrant vector store async client |

Recommendation for MongoDB: use the PyMongo async API (`pymongo.AsyncMongoClient`), not Motor. Motor is deprecated as of 2025-05-14 and reached end of life on 2026-05-14, which is in the past as of today. New services should not adopt Motor. This contradicts the "Motor" wording in DECISIONS.md D-004 and should be corrected there.

---

## PostgreSQL: SQLAlchemy 2.x async + asyncpg + Alembic

### Versions

- `sqlalchemy[asyncio]==2.0.52` (pulls `greenlet` on CPython)
- `asyncpg==0.31.0`
- `alembic==1.19.2`

SQLAlchemy 2.1 is in development but not the stable line as of today. Stay on the 2.0.x series.

### Env vars

- `POSTGRES_DSN` for example `postgresql+asyncpg://user:pass@host:5432/dbname`
- Optional tuning: `POSTGRES_POOL_SIZE` (default 5), `POSTGRES_MAX_OVERFLOW` (default 10), `POSTGRES_POOL_TIMEOUT` (seconds), `POSTGRES_ECHO` (bool)
- Alembic reads the same DSN. Keep the `+asyncpg` marker in the URL so the async engine is selected.

### Overlay setup code (`db/postgres.py`)

```python
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.settings import settings

engine = create_async_engine(
    settings.postgres_dsn,
    pool_size=settings.postgres_pool_size,
    max_overflow=settings.postgres_max_overflow,
    pool_pre_ping=True,          # recycle dead connections transparently
    echo=settings.postgres_echo,
)

# expire_on_commit=False is required under asyncio so attributes stay usable
# after commit without triggering lazy IO.
SessionFactory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request, rolled back on error."""
    async with SessionFactory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def dispose_engine() -> None:
    await engine.dispose()   # call from FastAPI lifespan shutdown
```

Usage in a route: `async def handler(session: AsyncSession = Depends(get_session))`. Let the route or a service function call `await session.commit()` explicitly; the dependency only guarantees close plus rollback-on-exception. Call `dispose_engine()` in the lifespan shutdown so asyncpg connections are not garbage collected outside the loop.

### Health check contribution

```python
async def postgres_health() -> bool:
    async with engine.connect() as conn:
        await conn.execute(text("SELECT 1"))
    return True
```

Return the boolean plus a measured latency into the aggregate `/health` (or `/readyz`) payload. Use a short statement timeout so a stalled DB fails fast rather than hanging the probe.

### Alembic async setup

Scaffold once with the async template:

```bash
alembic init -t async migrations
```

That produces an `env.py` whose `run_migrations_online` is async. The essential shape:

```python
import asyncio
from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.models import Base   # your DeclarativeBase

target_metadata = Base.metadata


def do_run_migrations(connection):
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,          # detect column type changes on autogenerate
        compare_server_default=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations():
    connectable = async_engine_from_config(
        context.config.get_section(context.config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online():
    asyncio.run(run_async_migrations())
```

Notes: `run_sync` bridges Alembic's sync migration API onto the async connection. Use `NullPool` in migrations so no pooled connections linger. Set `sqlalchemy.url` in `alembic.ini` from the env var (either via `config.set_main_option` in `env.py` reading `os.environ`, or `%(POSTGRES_DSN)s` interpolation). Autogenerate: `alembic revision --autogenerate -m "msg"`; always review the generated script since autogenerate misses some constraint and enum changes.

### Sources

- SQLAlchemy asyncio extension docs, https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html (accessed 2026-09-07). Covers `create_async_engine`, `async_sessionmaker`, `expire_on_commit=False`, and the `await engine.dispose()` requirement for asyncpg.
- SQLAlchemy on PyPI, https://pypi.org/project/SQLAlchemy/ (accessed 2026-09-07). Version 2.0.52, released 2026-08-11.
- asyncpg on PyPI, https://pypi.org/project/asyncpg/ (accessed 2026-09-07). Version 0.31.0, released 2025-11-24.
- Alembic on PyPI, https://pypi.org/project/alembic/ (accessed 2026-09-07). Version 1.19.2, released 2026-09-04.
- Alembic cookbook, async env.py and `alembic init -t async`, https://alembic.sqlalchemy.org/en/latest/cookbook.html (accessed 2026-09-07).

---

## MongoDB: PyMongo async API (recommended) vs Motor

### Which is current

Use `pymongo.AsyncMongoClient` from PyMongo itself. Motor is deprecated (announced 2025-05-14) and its end of life was 2026-05-14. The PyMongo async API is GA, implements asyncio directly in the driver rather than delegating to a thread pool, and generally outperforms Motor. Migration from Motor is largely a rename of `MotorClient` to `AsyncMongoClient` plus import path changes.

### Versions

- `pymongo==4.18.0` (async API included, no extra package)
- Optional ODM overlay: `beanie==2.2.0` (built on the PyMongo async API in current releases; still Pydantic v2 based)

### Env vars

- `MONGO_URI` for example `mongodb://user:pass@host:27017/?retryWrites=true&w=majority`
- `MONGO_DB` database name
- Optional: `MONGO_MAX_POOL_SIZE` (default 100), `MONGO_MIN_POOL_SIZE`, `MONGO_SERVER_SELECTION_TIMEOUT_MS` (lower it, for example 3000, so health checks and cold starts fail fast)

### Overlay setup code (`db/mongo.py`), no ODM

```python
from pymongo import AsyncMongoClient
from pymongo.errors import PyMongoError

from app.settings import settings

client: AsyncMongoClient | None = None


async def connect_mongo() -> None:
    """Call from FastAPI lifespan startup. Client is a module singleton."""
    global client
    client = AsyncMongoClient(
        settings.mongo_uri,
        maxPoolSize=settings.mongo_max_pool_size,
        serverSelectionTimeoutMS=settings.mongo_server_selection_timeout_ms,
        tz_aware=True,
    )
    await client.admin.command("ping")   # fail startup early if unreachable


async def close_mongo() -> None:
    if client is not None:
        await client.close()


def get_db():
    assert client is not None, "Mongo client not initialised"
    return client[settings.mongo_db]
```

Connection lifecycle: create the client once in the lifespan startup, never per request. The connection pool is loop-safe and reused across requests. Instantiating `AsyncMongoClient` inside a handler is an anti-pattern that leaks sockets under load. Close it in lifespan shutdown.

Document model approach without an ODM: define plain Pydantic v2 models for validation at the API boundary, convert to and from `dict` for `insert_one` / `find_one`, and map `_id` (an `ObjectId`) to a string field. Keep an `indexes()` startup routine that calls `await get_db()["col"].create_index(...)` for the indexes the service needs. Choose Beanie only if you want declarative `Document` classes, lifecycle hooks, and typed queries and accept the ODM coupling; for a boilerplate the no-ODM path keeps the overlay smaller and dependency surface lower.

### Health check contribution

```python
async def mongo_health() -> bool:
    try:
        await client.admin.command("ping")
        return True
    except PyMongoError:
        return False
```

`ping` is cheap, requires no auth, and does not depend on a specific database. Pair it with the low `serverSelectionTimeoutMS` so a down replica set surfaces quickly.

### Sources

- Migrate to PyMongo Async, https://www.mongodb.com/docs/languages/python/pymongo-driver/current/reference/migration/ (accessed 2026-09-07). States Motor deprecation on 2025-05-14, EOL 2026-05-14, and recommends AsyncMongoClient.
- Motor docs deprecation notice, https://motor.readthedocs.io/en/latest/ (accessed 2026-09-07).
- PyMongo FastAPI integration tutorial, https://www.mongodb.com/docs/languages/python/pymongo-driver/current/integrations/fastapi-integration/ (accessed 2026-09-07). Client-as-singleton-in-lifespan pattern.
- PyMongo async mongo_client API, https://pymongo.readthedocs.io/en/latest/api/pymongo/asynchronous/mongo_client.html (accessed 2026-09-07).
- PyMongo on PyPI, https://pypi.org/project/pymongo/ (accessed 2026-09-07). Version 4.18.0, released 2026-09-03.
- Beanie on PyPI, https://pypi.org/project/beanie/ (accessed 2026-09-07). Version 2.2.0, released 2026-08-07.

---

## Redis: redis-py asyncio client

### Version

- `redis==8.1.0` (the `redis.asyncio` namespace ships in the same package; no `aioredis`, which was absorbed years ago)

Since redis-py 8.0 the client negotiates RESP3 on the wire by default while keeping RESP2-compatible Python return shapes. Append `protocol=3` to the URL only if you want RESP3 response typing.

### Env vars

- `REDIS_URL` for example `redis://:password@host:6379/0` (or `rediss://` for TLS)
- Optional: `REDIS_MAX_CONNECTIONS` (pool cap, default 2**31 effectively unbounded, set a real number), `REDIS_SOCKET_TIMEOUT`, `REDIS_HEALTH_CHECK_INTERVAL` (seconds; pool pings idle connections)

### Overlay setup code (`db/redis.py`)

```python
import redis.asyncio as redis

from app.settings import settings

pool = redis.ConnectionPool.from_url(
    settings.redis_url,
    max_connections=settings.redis_max_connections,
    health_check_interval=settings.redis_health_check_interval,
    decode_responses=True,
)

client: redis.Redis = redis.Redis(connection_pool=pool)


async def close_redis() -> None:
    await client.aclose()
    await pool.aclose()          # call both from lifespan shutdown


# Cache helper
async def cache_get_or_set(key: str, ttl: int, producer):
    hit = await client.get(key)
    if hit is not None:
        return hit
    value = await producer()
    await client.set(key, value, ex=ttl)
    return value


# Pub/sub consumer
async def subscribe(channel: str):
    async with client.pubsub() as ps:
        await ps.subscribe(channel)
        async for message in ps.listen():
            if message["type"] == "message":
                yield message["data"]
```

Publish with `await client.publish(channel, payload)` on the same shared client. Keep one module-level `client` plus `pool` for the whole app; do not create a client per request.

### Async caveats

- There is no async destructor. You must explicitly `await client.aclose()` and `await pool.aclose()` on shutdown or connections leak.
- `aclose()` is the current method name; the older `close()` is deprecated on the async client.
- A long-lived `pubsub()` subscription holds a dedicated connection. Run it as its own task and cancel it on shutdown. Do not multiplex pub/sub and normal commands on the same connection object.
- Set `health_check_interval` so the pool revives connections dropped by idle timeouts or failovers; otherwise the first command after an idle period can raise `ConnectionError`.
- `decode_responses=True` gives `str` values. If any overlay stores raw bytes (pickled blobs, protobuf) it needs a separate client without that flag.

### Health check contribution

```python
async def redis_health() -> bool:
    return bool(await client.ping())
```

`ping()` returns `True` on success. Wrap in the aggregate probe with a timeout.

### Sources

- redis-py asyncio examples, https://redis.readthedocs.io/en/stable/examples/asyncio_examples.html (accessed 2026-09-07). Covers `from_url`, shared `ConnectionPool`, `aclose`, `pubsub()` context manager, and the explicit-disconnect caveat.
- redis on PyPI, https://pypi.org/project/redis/ (accessed 2026-09-07). Version 8.1.0, released 2026-07-30.
- redis-py releases, https://github.com/redis/redis-py/releases (accessed 2026-09-07). RESP3 default since 8.0, async maintenance-notification support.

---

## Qdrant: qdrant-client async

### Version

- `qdrant-client==1.19.0` (async support via `AsyncQdrantClient` since 1.6.1; `collection_exists` helper since 1.9)

The client version tracks the Qdrant server minor version. Run a server on a compatible 1.19.x line.

### Env vars

- `QDRANT_URL` for example `http://qdrant:6333` (or `https://` for Qdrant Cloud)
- `QDRANT_API_KEY` (required for Qdrant Cloud, empty for local)
- `QDRANT_COLLECTION` collection name the service uses
- `EMBEDDING_DIM` vector size, must match the embedding model (for example 1536 for OpenAI text-embedding-3-small, 3072 for text-embedding-3-large). Keep this in one place shared with the AI overlay.
- Optional: `QDRANT_PREFER_GRPC` (bool; gRPC is lower latency for bulk upserts)

### Overlay setup code (`db/qdrant.py`)

```python
from qdrant_client import AsyncQdrantClient, models

from app.settings import settings

client = AsyncQdrantClient(
    url=settings.qdrant_url,
    api_key=settings.qdrant_api_key or None,
    prefer_grpc=settings.qdrant_prefer_grpc,
)


async def ensure_collection() -> None:
    """Idempotent bootstrap. Call from lifespan startup."""
    if not await client.collection_exists(settings.qdrant_collection):
        await client.create_collection(
            collection_name=settings.qdrant_collection,
            vectors_config=models.VectorParams(
                size=settings.embedding_dim,
                distance=models.Distance.COSINE,
            ),
        )


async def upsert(points: list[models.PointStruct]) -> None:
    await client.upsert(collection_name=settings.qdrant_collection, points=points)


async def search(vector: list[float], limit: int = 10):
    res = await client.query_points(
        collection_name=settings.qdrant_collection,
        query=vector,
        limit=limit,
        with_payload=True,
    )
    return res.points


async def close_qdrant() -> None:
    await client.close()
```

Point shape for upsert: `models.PointStruct(id=<int or uuid str>, vector=[...], payload={...})`. `query_points` is the current search entrypoint; the older `search` method still exists but `query_points` is the one to build on. The create-if-not-exists guard makes the overlay safe to run on every boot and in tests.

### Health check contribution

```python
async def qdrant_health() -> bool:
    try:
        await client.get_collections()
        return True
    except Exception:
        return False
```

`get_collections()` is a light round trip that confirms auth and reachability. The REST service also exposes `/healthz`, `/livez`, `/readyz` for infrastructure probes, but from inside the app the client call above is the check that also validates the API key.

### Sources

- qdrant-client README and quickstart, https://github.com/qdrant/qdrant-client (accessed 2026-09-07). `AsyncQdrantClient`, `VectorParams`, `Distance.COSINE`, gRPC and REST async support.
- qdrant-client on PyPI, https://pypi.org/project/qdrant-client/ (accessed 2026-09-07). Version 1.19.0, released 2026-08-04.
- Qdrant API reference, collection-exists and service health endpoints, https://api.qdrant.tech/api-reference/collections/collection-exists and https://api.qdrant.tech/api-reference/service/readyz (accessed 2026-09-07).
- qdrant-client async module docs, https://python-client.qdrant.tech/qdrant_client.async_qdrant_client (accessed 2026-09-07).

---

## Cross-cutting notes for the overlay author

- Each overlay contributes: one settings block, one `db/<name>.py` module with a module-level client or engine, startup and shutdown hooks for the FastAPI lifespan, and one `<name>_health()` coroutine registered with the aggregate health router.
- The aggregate `/health` (liveness) should be cheap and local. A separate `/readyz` (readiness) runs all registered `*_health()` coroutines concurrently with `asyncio.gather` under a per-check timeout and returns 200 only if all pass.
- Never create clients per request for any of these. All four expose loop-safe pools meant to live for the process lifetime.
- All four require explicit async cleanup on shutdown: `engine.dispose()`, `client.close()` (Mongo), `client.aclose()` plus `pool.aclose()` (Redis), `client.close()` (Qdrant).

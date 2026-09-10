# Overlay: db_qdrant

Async Qdrant vector store for the FastAPI service: `AsyncQdrantClient`,
idempotent collection bootstrap, and thin upsert/search helpers.

- Owner: Data Layer Engineer
- Registry key: `db_qdrant` (bool, default `false`)
- Overlay id: `db_qdrant`
- Milestone: 4 (Phase 2)
- Decisions: D-001 (Qdrant is the sole v1 vector store), D-014 (vector size is a
  registry key, defaulted from `embedding_vector_size`), D-004 (async stack),
  D-019 (frozen pins), D-027 (`compose.app-deps` slot)
- Research: `research/data-layer.md`

## What it adds

| Surface | Contribution |
| --- | --- |
| Gated subtree | `{{ python_package }}/db/qdrant/` - `client.py` (`init_client` / `get_client` / `close_client`, module-level `_client` holder, `ensure_collection`, `upsert`, `search`) |
| `pyproject.toml` | `qdrant-client==1.19.0` |
| `pyproject.toml` dev group | `testcontainers==4.15.0` (only when `tests_integration`) |
| `config/settings.py` | `qdrant_url`, `qdrant_api_key`, `qdrant_collection`, `qdrant_vector_size` |
| `.env.example` | `APP_QDRANT_URL`, `APP_QDRANT_API_KEY` (commented), `APP_QDRANT_COLLECTION`, `APP_QDRANT_VECTOR_SIZE` |
| `lifespan.py` | startup hook (`init_client()`, mirror to `app.state.db_qdrant`, then best-effort `ensure_collection()` - a failure is logged, readiness reports the truth), shutdown hook (`close_client()`) |
| `health.py` | `check_db_qdrant()` - zero-arg, reads the `_client` holder, `get_collections()` (also validates the API key), never raises |
| `docker-compose.yml` | `qdrant` service (`qdrant/qdrant:v1.19.1`, `/readyz` healthcheck over a bash `/dev/tcp` socket - the image ships no curl/wget) |
| `docker-compose.yml` `app.depends_on` | `qdrant: {condition: service_healthy}` via `compose.app-deps.yml` (D-027) |
| `tests/conftest.py` | `qdrant_client` (mock: autouse, patches `init_client` with an in-process `AsyncQdrantClient(location=":memory:")` - a real client, no server, no container), `qdrant_container` (testcontainers, only when `tests_integration`) |
| Boots test | `tests/overlays/test_db_qdrant_boots.py` |

## Design notes

- One `AsyncQdrantClient` for the process, built by the lifespan startup hook.
  Construction performs no I/O.
- `ensure_collection` is idempotent (`collection_exists` guard), so it is safe on
  every boot and in tests. It runs at startup as best-effort: a failure is
  logged and left for the readiness check to surface, so a transient Qdrant
  outage does not abort app startup.
- Collection dimension is `APP_QDRANT_VECTOR_SIZE`, defaulted from the
  `embedding_vector_size` answer (384 for the fastembed default). The embedding
  pipeline itself is a separate AI overlay (Phase 4).
- `query_points` is the search entrypoint (not the older `search`).
- Mock mode is the default and needs no container: the autouse `qdrant_client`
  fixture swaps in a real `:memory:` client, so `ensure_collection`,
  `collection_exists`, `isinstance(client, AsyncQdrantClient)`, and the health
  check all exercise real code paths offline.
- The compose healthcheck probes `/readyz` with
  `bash -c 'exec 3<>/dev/tcp/127.0.0.1/6333; ...; grep -q "200 OK"'` because the
  `qdrant/qdrant` image (Debian slim) has no curl, wget, or netcat, only bash.

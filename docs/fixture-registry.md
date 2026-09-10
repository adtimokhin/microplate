# Fixture registry

For the Data, Messaging, and AI overlay engineers who write
`template/_fragments/<overlay-id>/conftest.py.jinja`.

The machine-readable map lives in `registry.yaml` (`fixtures:` on each overlay
entry). `harness/fixture_registry.py` reads it, never duplicates it:

```
uv run harness/fixture_registry.py          # print overlay -> fixtures + boots test
uv run harness/fixture_registry.py --lint    # contract check, non-zero on error
```

`--lint` errors only on overlays whose `build_status` is `implemented`. Planned
overlays get warnings. A fixture-name collision is always an error.

## What each overlay declares

In `registry.yaml`, under the overlay's option entry:

```yaml
fixtures:
  - { name: postgres_session, kind: mock }
  - { name: postgres_container, kind: container }
```

- `name` is the pytest fixture name exactly as it appears in the fragment.
- `kind` is `mock` or `container`.

## The conftest fragment contract

From `docs/overlay-contract.md` section 4.3 (fragment rules) and section 7
(proves-it-boots). The base `tests/conftest.py` `{% include %}`s every selected
overlay's `_fragments/<id>/conftest.py.jinja` into one file, in `overlay_order`.

1. **Namespaced, globally unique names.** Prefix every fixture with the overlay's
   area token: `postgres_`, `mongodb_`, `redis_`, `qdrant_`, `rabbitmq_`,
   `grpc_`, `openai_`, `anthropic_`, `langchain_`, `langgraph_`, `otel_`, and so
   on. Two overlays must never define the same fixture name; the assembled
   conftest would have a duplicate definition. The lint checks uniqueness across
   all overlays.

2. **A mock fixture is always provided.** It stands up the overlay's client or
   handle with the external call stubbed (per D-013 for LLM and tracing
   overlays: `httpx2.MockTransport` or a `*_BASE_URL` redirect to a local fake,
   never `respx` / `vcrpy`). The proves-it-boots test and all unit tests use it,
   so they run with no container. It must pass in under 2 seconds.

3. **A container fixture only when there is a backing service.** Provide one
   `container` fixture per overlay that has a `compose_services` entry, built on
   `testcontainers`. It is used only when `tests_integration` is selected. It
   must not be collected, imported, or started when `tests_integration` is
   false: guard the import and the fixture body, do not do it at module top
   level. The lint flags a `container` fixture with no `compose_services`, and a
   `compose_services` overlay with no `container` fixture.

4. **No collection-time side effects.** Importing the conftest fragment must open
   no sockets, start no containers, read no environment beyond defaults, and
   touch no disk. All of that goes inside fixture bodies. Pytest imports every
   conftest at collection; a side effect there breaks `--collect-only` and every
   unrelated test run.

5. **Exact fixture set.** Ship exactly the fixtures named in `registry.yaml`, no
   more. If you need another fixture, add it to the registry entry first (one
   source of truth) so the map and the lint stay accurate.

## Current declared fixtures

Run `uv run harness/fixture_registry.py` for the live list. As of registry v0:

| Overlay | mock | container |
| --- | --- | --- |
| `db_postgres` | `postgres_session` | `postgres_container` |
| `db_mongodb` | `mongodb_db` | `mongodb_container` |
| `db_redis` | `redis_client` | `redis_container` |
| `db_qdrant` | `qdrant_client` | `qdrant_container` |
| `messaging_rabbitmq` | `rabbitmq_channel` | `rabbitmq_container` |
| `api_grpc` | `grpc_channel` | - |
| `tool_scaffold` | `tool_client` | - |
| `mcp_server` | `mcp_session` | - |
| `streaming_sse` | `sse_client` | - |
| `streaming_grpc` | `grpc_stream_stub` | - |
| `llm_openai` | `openai_client` | - |
| `llm_anthropic` | `anthropic_client` | - |
| `prompt_management` | `prompt_registry` | - |
| `langchain` | `langchain_llm` | - |
| `embedding_pipeline` | `embedding_client` | - |
| `langgraph` | `langgraph_app` | - |
| `langsmith` | `langsmith_tracer` | - |
| `otel_tracing` | `otel_span_exporter` | - |
| `transport_grpc` | (none yet) | - |
| `transport_rabbitmq` | (none yet) | - |

`transport_grpc` and `transport_rabbitmq` (milestone 6) have no `fixtures` block
yet. The Messaging & Topology Engineer adds one when the overlay is built; the
lint warns until then.

# Overlay: streaming_sse

A Server-Sent Events example endpoint built on `sse-starlette`.

- Owner: MessagingEngineer
- Registry key: `streaming_sse` (bool, default `false`)
- Overlay id: `streaming_sse`
- Milestone: 4 (Phase 2)
- Requires: `api_rest` (V-14) - always true in v1.
- Decisions: D-020 (boolean split), D-019 (pins)

## What it adds

| Surface | Contribution |
| --- | --- |
| Gated subtree | `{{ python_package }}/streaming/sse/` - `routes.py` (`GET /stream/sse`: streams `count` numbered `tick` events then a `done` event, honours client disconnect), `__init__.py` (exports `router`) |
| `pyproject.toml` | `sse-starlette==3.4.11` |
| `api/router.py` | `api_router.py` fragment: imports `router` and calls `api_router.include_router(...)`, wired at import time (D-032) |
| `tests/conftest.py` | `sse_client` (mock: a `TestClient` bound to the app, no backing service) |
| Boots test | `tests/overlays/test_streaming_sse_boots.py` - consumes a real event stream |

## Design notes

- The router is wired into `api_router` at import time through the base
  `api_router.py` fragment slot (D-032), so it is in the app and in
  `/openapi.json` before `create_app()` returns. No lifespan hook, no
  `app.openapi_schema` reset.
- `EventSourceResponse` from `sse-starlette` owns the SSE framing, keep-alive
  pings, and disconnect cleanup; the route only supplies an async generator of
  event dicts.
- No env vars, no health check, no CI step, no compose service. Covered entirely
  by the boots test and unit tests.
- Offline: SSE is served from the app itself, so the boots test needs no
  container or network.

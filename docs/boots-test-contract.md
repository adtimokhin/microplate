# Proves-it-boots test contract

Every overlay ships at least one test that proves the overlay is wired into the
running app, not merely installed. Passing it in mock mode (and container mode
when `tests_integration` is selected) is a hard gate for flipping the overlay's
`build_status` to `implemented` in `registry.yaml`.

Authoritative rules: `docs/overlay-contract.md` section 7. This file is the
copy-ready template and the checklist.

## Location

```
tests/overlays/test_<overlay_id>_boots.py
```

Shipped inside the overlay's gated subtree so the file only exists when the
overlay is selected. The path is also recorded as `boots_test:` in the overlay's
`registry.yaml` entry; keep the two identical.

## Health check shape (canonical)

`check_<overlay_id>` is **zero-arg**: `Callable[[], Awaitable[HealthResult]]`,
matching the base `health.py` `ReadinessCheck` type unchanged. It reads its client
from a module-level holder that the overlay's lifespan startup hook sets. That
same startup hook also mirrors the handle onto `app.state.<name>`. The base
`health.py` does not change; the registry `health_checks` list holds this zero-arg
callable directly.

So the boots test calls `check_<overlay_id>()` with no arguments, and does its
"handle is present and typed" assertion against `app.state.<name>`.

## Two overlay shapes

- **Client overlay** (datastore, broker, gRPC server, LLM client, tracer): opens
  or holds a resource. Its lifespan startup hook creates the client, sets the
  module-level holder, and mirrors the handle onto `app.state.<name>`. It
  registers a zero-arg `check_<overlay_id>()`.
- **Pure-route overlay** (`streaming_sse`, `tool_scaffold`, and any future
  router-only overlay): contributes FastAPI routes and nothing else. It wires its
  router into `api_router` at import time through
  `_fragments/<id>/api_router.py.jinja` (never from a lifespan hook, never by
  resetting `app.openapi_schema`). It has no client handle and often no readiness
  check.

Items 2 and 3 below are for client overlays. A pure-route overlay proves wiring
with item 2b instead.

## What it must do

1. Enter the real app lifespan. Use the generated app and its lifespan context,
   never a hand-built client:
   - `async with lifespan(app):` , or
   - the FastAPI / Starlette test client as a context manager (it runs lifespan).
2. **Client overlay**: assert the overlay's client or handle is on
   `app.state.<name>` and is the expected type. This is the wiring proof: the
   lifespan startup hook created it, put it in the module-level holder, mirrored
   it onto `app.state`, and it survived startup.
2b. **Pure-route overlay**: assert the overlay's path is present in
   `GET /openapi.json` `paths`, then call the route and assert it responds
   correctly end to end. That the route is in the schema is the render-time
   wiring proof; the successful call proves it runs.
3. **Client overlay**: call the overlay's zero-arg health check function
   `check_<overlay_id>()` and assert a healthy result. It resolves its own client
   from the holder, so the test passes no arguments. A pure-route overlay that
   registers no readiness check skips this; one that does (for example
   `tool_scaffold`) still calls it zero-arg.
4. Backing service:
   - `tests_integration` selected: use the `*_container` fixture, hit a real
     container.
   - otherwise: use the `*` mock fixture, external call stubbed. The test still
     runs and still passes.
5. AI overlays: stubbed or recorded responses only, no network LLM call, ever
   (D-013, scope 4.5). Stub via `httpx2.MockTransport` through the SDK's own
   client, or redirect `*_BASE_URL` to a local fake server. Not `respx`, not
   `vcrpy`.
6. Under 2 seconds in mock mode.
7. No `skip`, no `xfail`. If the test cannot run in some configuration, that
   configuration is invalid and belongs in the overlay's `conflicts` in
   `registry.yaml`.
8. Must pass with the overlay alone on the base, and with the overlay plus every
   overlay it names in `requires`.

## Template

```python
# tests/overlays/test_<overlay_id>_boots.py
"""Proves the <overlay_id> overlay is wired into the running app."""

import pytest

from {{ python_package }}.main import app
from {{ python_package }}.lifespan import lifespan
from {{ python_package }}.health import check_<overlay_id>


@pytest.mark.anyio
async def test_<overlay_id>_boots(<overlay_id_short>_<mock_or_container>):
    """Enter the lifespan, confirm the handle is on app state and healthy."""
    async with lifespan(app):
        handle = getattr(app.state, "<name>", None)
        assert handle is not None, "<overlay_id> handle missing from app.state.<name>"
        assert isinstance(handle, <ExpectedType>)

        result = await check_<overlay_id>()  # zero-arg; reads its own client
        assert result.healthy, result
```

Notes for the author:

- The fixture argument name comes from `registry.yaml` `fixtures:` for this
  overlay (`postgres_session` mock, `postgres_container` container). See
  `docs/fixture-registry.md`.
- Whether the mock or the container fixture is injected is decided by a small
  indirection in `conftest.py` keyed on `tests_integration`, not by two separate
  test functions.
- `<name>` is the `app.state` attribute the lifespan startup hook sets (also the
  module-level holder name). `<ExpectedType>` is the concrete client type
  (`AsyncEngine`, `AsyncMongoClient`, `Redis`, `AsyncQdrantClient`,
  `AbstractRobustConnection`, `AsyncOpenAI`, and so on).
- `check_<overlay_id>()` takes no arguments. It pulls its client from the same
  module-level holder the lifespan hook set; if the holder is unset it must
  return an unhealthy `HealthResult`, never raise.
- The health result object is whatever the base `health.py` aggregator expects;
  assert its healthy flag and include it in the assertion message.

## Base smoke test

The base template ships its own, always present:

```
tests/test_app_boots.py
```

App imports, `/health/live` returns 200, `/health/ready` returns 200 with no
overlays selected. The harness runs this for the zero-overlay combination today.

## Checklist before marking an overlay `implemented`

- [ ] `tests/overlays/test_<overlay_id>_boots.py` exists in the gated subtree.
- [ ] `boots_test:` in `registry.yaml` points at that exact path.
- [ ] Enters the real lifespan (context manager), not a hand-built object.
- [ ] Asserts the handle is on `app.state.<name>` and is the right type.
- [ ] Calls the zero-arg `check_<overlay_id>()` and asserts healthy.
- [ ] `check_<overlay_id>` matches the base `ReadinessCheck` type
      (`Callable[[], Awaitable[HealthResult]]`); the registry `health_checks`
      list holds it directly.
- [ ] Passes in mock mode in under 2 seconds.
- [ ] Passes in container mode when `tests_integration` is selected.
- [ ] No skip, no xfail.
- [ ] Passes with the overlay alone and with all `requires` overlays added.
- [ ] AI overlays: no network call in any configuration.
- [ ] `harness/run.py` picks the overlay up (its `build_status` is `implemented`)
      and the combination goes green.

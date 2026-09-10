# Overlay: tool_scaffold

Function-call-shaped FastAPI routes with function-calling-tuned OpenAPI (D-007,
OpenAPI half). MCP exposure is a separate later overlay.

- Owner: MessagingEngineer
- Registry key: `tool_scaffold` (bool, default `false`)
- Overlay id: `tool_scaffold`
- Milestone: 4 (Phase 2)
- Requires: `api_rest or api_grpc` (V-2) - `api_rest` is always true in v1.
- Decisions: D-007 (OpenAPI routes now, MCP overlay later)

## What it adds

| Surface | Contribution |
| --- | --- |
| Gated subtree | `{{ python_package }}/tools/` - `registry.py` (`ToolSpec` + `ToolRegistry`, `function_schema()` renders the OpenAI `{name, description, parameters}` shape), `examples.py` (`echo`, `add` example tools with typed request/response models; importing registers them), `routes.py` (`POST /tools/echo`, `POST /tools/add` each with a stable `operation_id`, summary, description and typed models; `GET /tools` returns the function-spec catalogue), `__init__.py` |
| `api/router.py` | `api_router.py` fragment: imports `router` and calls `api_router.include_router(...)`, wired at import time (D-032) |
| `health.py` | `check_tool_scaffold()` - zero-arg, healthy when the import-time tool registry holds at least one tool |
| `tests/conftest.py` | `tool_client` (mock: a `TestClient` bound to the app; tools run in-process) |
| Boots test | `tests/overlays/test_tool_scaffold_boots.py` - calls the tools over HTTP and asserts the function-calling OpenAPI shape (one `operationId` per tool, JSON-Schema `parameters`) |

## Design notes

- Function-calling-tuned OpenAPI: every tool is one `POST /tools/<name>`
  operation with `operation_id == <name>`, a `summary`, a `description`, and an
  explicit request body model plus response model, so a function-calling client
  can consume `/openapi.json` (or `GET /tools`) directly.
- The router is wired into `api_router` at import time through the base
  `api_router.py` fragment slot (D-032). No lifespan hook, no
  `app.openapi_schema` reset. `check_tool_scaffold()` reads the process-wide tool
  registry, which is populated when `{{ python_package }}.tools` is imported.
- No dependency added (FastAPI + pydantic are base). No env vars. No compose
  service. No network in tests.
- The OpenAPI-shape assertions live in the boots test, which the `test` CI job
  already runs; no separate CI step is added.

# mcp_server

Exposes the service's tools as MCP tools so the service can be plugged into an
agent runtime as a tool server (scope 4.4).

## Keys
- `mcp_server` (bool). Requires `tool_scaffold or api_grpc` (V-3).
- `APP_MCP_HOST` / `APP_MCP_PORT`.

## Design (D-035, hardened Phase 7)
The same handler functions that back the REST tool endpoints (or gRPC methods)
are registered on an `MCPServer` (`mcp==2.2.0`, `from mcp.server import
MCPServer`). One implementation.

The **in-process server + its tool list** (`get_server()`, `list_tool_names()`)
is the primary tested contract - no transport, no network, fully deterministic.

**The streamable-http mount over `/mcp` now actually serves real MCP protocol
traffic end to end**, chained into the base app lifespan. `tests/overlays/test_mcp_server_http.py`
proves it: it runs the real app lifespan, connects with the `mcp` SDK's own
client (`ClientSession` + `streamable_http_client`) over an in-process
`httpx2.ASGITransport` (no real socket), and does `initialize()` ->
`list_tools()` -> `call_tool()` against the mounted app. Always on, no
`tests_integration` gate - there is nothing external to spin up.

### The #1367 lifespan-chaining fix

Mounting an MCP `streamable_http_app()` onto an existing FastAPI app with a
plain `Mount()` does not work out of the box: `Mount()` does not propagate a
sub-app's own `lifespan`, so the SDK's `StreamableHTTPSessionManager` - whose
`run()` context manager starts the task group real requests need - never runs.
A request to `/mcp` would hang or fail forever. This is upstream mcp issue
#1367.

Fix: `_fragments/mcp_server/lifespan.py.jinja` calls
`{{ python_package }}.mcp.server.start_http_transport()` /
`stop_http_transport()` from the base app's `STARTUP_HOOKS` / `SHUTDOWN_HOOKS`
(`overlay-contract` 4.5), manually entering and holding open the session
manager's `run()` lifespan for the life of the app, in an `AsyncExitStack`.

### The second sharp edge: session managers are call-once, but test lifespans are not

`StreamableHTTPSessionManager.run()` may be entered only ONCE per instance,
ever - the SDK raises `RuntimeError` on a second call ("Create a new instance
if you need to run again"). A real deployment's app lifespan runs exactly once
per process, so this would never surface in production. It DOES surface in the
generated test suite: every test file that enters the app lifespan
(`TestClient(app)` or `async with lifespan(app):`) does so against the SAME
module-level `app` singleton, so `_mcp_server_startup` runs once per test
function within one process - a second test's startup would hit the call-once
guard on a session manager built at import time.

Fix: `mcp/server.py`'s `start_http_transport()` builds a FRESH
`streamable_http_app()` (and therefore a fresh session manager - the SDK ties a
new one to each `streamable_http_app()` call) on every invocation, not once at
import time. The ASGI object actually mounted under `/mcp` (`get_asgi_app()`,
wired via the `api_router` slot at import time, exactly once) is a small stable
dispatch shim that forwards each request to whichever streamable-http app is
CURRENT, rather than a frozen reference to one built at mount time. Not started
or degraded: the shim answers `503`, never hangs, never raises. This makes the
overlay's own pytest suite deterministic across repeated lifespan cycles in one
process, which is exactly the shape hardening Phase 7 was checking for.

### Registration schema: `request: <ToolSpec.request_model>`, not `**kwargs`

The pre-hardening tool_scaffold-linked wrapper had `async def _call(**kwargs)`,
which the mcp SDK's schema builder (`inspect.signature`) cannot introspect into
named fields - it produced a tool whose ONLY property was a single opaque
`kwargs: dict`, invisible to a real MCP client and rejected by the SDK's own
argument validation on every real call (verified while writing the HTTP round-
trip test: `call_tool("echo", ...)` failed with "Field required: kwargs" no
matter what was passed). Fixed: the wrapper now has one parameter, `request`,
dynamically annotated with the tool's own `spec.request_model` (a pydantic
model), so the MCP schema nests the tool's real, fully-typed field list under
`{"request": {...}}`. A real client calls e.g. `call_tool("echo", {"request":
{"text": "hi"}})`. This is a correctness fix, not a design change - the prior
shape was invisible to any real caller, not merely less ergonomic.

### The DNS-rebinding auto-protection tradeoff

`streamable_http_app(host=...)` auto-enables a `TransportSecuritySettings` Host-
header allowlist ONLY when `host` is a loopback name (`127.0.0.1` /
`localhost` / `::1`). `mcp/server.py` passes `host=settings.mcp_host` (default
`0.0.0.0`), so this stays off by default: a container bound to `0.0.0.0` is not
the scenario this protection targets (browser-based DNS-rebinding against a
locally-bound dev server). If a service is deliberately run bound to
`localhost` (e.g. behind a local-only sidecar), the protection re-enables
automatically because `mcp_host` would be `127.0.0.1` in that config.

## Files
- `{{ python_package }}/mcp/server.py` - `get_server()`, `list_tool_names()`, `get_asgi_app()`, `start_http_transport()`, `stop_http_transport()`
- `tests/overlays/test_mcp_server_boots.py` - in-process tool registration contract
- `tests/overlays/test_mcp_server_http.py` - real MCP-over-HTTP round trip (Phase 7)

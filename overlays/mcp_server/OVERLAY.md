# mcp_server

Exposes the service's tools as MCP tools so the service can be plugged into an
agent runtime as a tool server (scope 4.4).

## Keys
- `mcp_server` (bool). Requires `tool_scaffold or api_grpc` (V-3).
- `APP_MCP_HOST` / `APP_MCP_PORT`.

## Design (D-035)
The same handler functions that back the REST tool endpoints (or gRPC methods)
are registered on an `MCPServer` (`mcp==2.2.0`, `from mcp.server import
MCPServer`). One implementation.

The **in-process server + its tool list is the tested contract** - the boots
test builds the server, checks the registered tool names, and invokes a tool
directly. The streamable-http mount (`mcp_asgi_app()` -> `/mcp`, wired via the
`api_router` slot) is present but best-effort: mounting the MCP streamable-http
app onto an existing FastAPI app has an upstream lifespan-chaining sharp edge
(mcp issue #1367). An "MCP over HTTP actually serves" check is deferred to
`tests_integration` / Phase 7.

## Files
- `{{ python_package }}/mcp/server.py` - `get_server()`, `list_tool_names()`, `mcp_asgi_app()`

# Overlay: streaming_grpc

A bidirectional-streaming gRPC example (`streaming.v1.ChatService`) added to the
co-hosted server from the `api_grpc` overlay.

- Owner: MessagingEngineer
- Registry key: `streaming_grpc` (bool, default `false`)
- Overlay id: `streaming_grpc`
- Milestone: 4 (Phase 2)
- Requires: `api_grpc` (V-13). Reuses its `grpcio` deps, `proto/` tree, `_pb`
  package, and `proto/regen_proto.py`.
- Decisions: D-020 (boolean split), D-009 (committed stubs)

## What it adds

| Surface | Contribution |
| --- | --- |
| Gated subtree | `{{ python_package }}/streaming/grpc/` - `service.py` (`ChatServicer`: `Chat` bidi RPC, echoes each inbound message upper-cased, preserving `seq`), `client.py` (`chat_stub` async-context helper), `__init__.py` (registers `ChatServicer` with `api_grpc`'s server via `register_servicer` on import), `_pb/streaming/v1/` (committed generated `chat_pb2.py`, `chat_pb2.pyi`, `chat_pb2_grpc.py` - they land under `api_grpc`'s `_pb/` package) |
| Gated subtree | `proto/streaming/v1/chat.proto` |
| `tests/conftest.py` | `grpc_stream_stub` (mock: yields the `chat_stub` helper; the server is already bound to an ephemeral port by `api_grpc`'s autouse `grpc_channel` fixture) |
| Boots test | `tests/overlays/test_streaming_grpc_boots.py` - enters the app lifespan, runs a real bidi `Chat` exchange against the running server |

## Design notes

- No new dependency: `grpcio` and friends come from `api_grpc`.
- The servicer is wired into `api_grpc`'s single co-hosted `grpc.aio` server, not
  a second server. `api_grpc`'s `server.py` does a guarded
  `importlib.import_module("{{ python_package }}.streaming.grpc")` on load; that
  import calls `register_servicer(_add_chat_servicer, "streaming.v1.ChatService")`,
  and `GrpcRuntime.start` adds every registered servicer, advertises it via
  reflection, and marks it SERVING. When this overlay is absent the import fails
  and is suppressed.
- `chat.proto` lives under the shared `proto/` tree, so `proto/regen_proto.py`
  (from `api_grpc`) regenerates `chat_pb2*` alongside `example_pb2*` in one run.
  The committed `chat_pb2*` files carry the `# ruff: noqa` / `# mypy:
  ignore-errors` headers and match a fresh regen; the `api_grpc` CI drift guard
  covers them.
- Offline: the boots test streams three messages and asserts the upper-cased
  echo over loopback. No container, no network beyond loopback.

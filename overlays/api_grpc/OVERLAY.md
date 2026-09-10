# Overlay: api_grpc

An async (`grpc.aio`) gRPC server co-hosted in the FastAPI lifespan, with the
standard health service, server reflection, and committed generated stubs.

- Owner: MessagingEngineer
- Registry key: `api_grpc` (bool, default `false`)
- Overlay id: `api_grpc`
- Milestone: 4 (Phase 2)
- Decisions: D-009 (committed stubs + pinned regen + CI diff guard), D-019 (pins)
- Research: `research/messaging-grpc.md`

## What it adds

| Surface | Contribution |
| --- | --- |
| Gated subtree | `{{ python_package }}/grpc/` - `service.py` (`ExampleServicer`: one unary `Greet`, one server-streaming `Ticks`), `server.py` (`GrpcRuntime`: builds the `grpc.aio` server, wires `ExampleService` + `grpc.health.v1.Health` + reflection, binds a port, sets health to SERVING, graceful shutdown; plus the `set_runtime`/`get_runtime` holder), `client.py` (`open_channel` / `example_stub` async-context helpers), `_pb/example/v1/` (committed generated `example_pb2.py`, `example_pb2.pyi`, `example_pb2_grpc.py`) |
| Gated subtree | `proto/example/v1/example.proto` (schema source of truth), `proto/regen_proto.py` (pinned-toolchain regenerator, repo-relative paths, fixed input order) |
| `pyproject.toml` | runtime: `grpcio`, `grpcio-health-checking`, `grpcio-reflection`, `grpcio-status` all `==1.83.1`, `protobuf==7.36.1`; dev group: `grpcio-tools==1.83.1` (regen only) |
| `config/settings.py` | `grpc_host`, `grpc_port` |
| `.env.example` | `APP_GRPC_HOST`, `APP_GRPC_PORT` |
| `lifespan.py` | startup hook (`GrpcRuntime.start`, put it on `app.state.grpc_server`, register the health holder), shutdown hook (`enter_graceful_shutdown` + `server.stop`, clear holder) |
| `health.py` | `check_api_grpc()` - zero-arg, dials the co-hosted server over loopback and calls `grpc.health.v1.Health/Check` |
| `tests/conftest.py` | `grpc_channel` (autouse mock: pins `APP_GRPC_PORT=0` so the server binds an ephemeral port, no external service; yields the `open_channel` helper) |
| `.github/workflows/ci.yml` | a `test` job step that runs `proto/regen_proto.py` then `git diff --exit-code` so the committed stubs can never drift (D-009) |
| Boots test | `tests/overlays/test_api_grpc_boots.py` |

## Design notes

- The gRPC server runs in the same event loop as the HTTP app, started from the
  lifespan hook. To run it as its own process instead, call `GrpcRuntime.start`
  from a dedicated entrypoint and drop the lifespan hook.
- D-009: `_pb/**` is committed generated code. It carries `# ruff: noqa` and
  `# mypy: ignore-errors` headers. `proto/regen_proto.py` runs only the
  `grpcio-tools` / `protobuf` versions pinned in `pyproject.toml`, feeds protoc
  every `proto/**/*.proto` in sorted order with repo-relative paths only, then
  rewrites the cross-module import to a relative one and runs `ruff format`.
  Output is byte-stable across machines; CI enforces it with `git diff
  --exit-code`.
- Health: the co-hosted `grpc_health.v1` async `HealthServicer` is set to
  SERVING for the empty key and for `example.v1.ExampleService` on startup, and
  `enter_graceful_shutdown()` flips everything to NOT_SERVING on stop. The HTTP
  readiness check calls it over the wire so external probes and `/health/ready`
  agree.
- `grpcio-reflection` is enabled so `grpcurl` and generic probes can discover
  the schema without local protos.
- Offline tests: `grpc_channel` binds an ephemeral port; no network beyond
  loopback, no container. The boots test makes real `Greet` / `Ticks` / health
  calls against the running server.
- `streaming_grpc` (separate overlay) reuses `grpcio` from here and adds a
  bidi-streaming example; `tests_contract` (Phase 3) adds `buf lint` / `buf
  breaking` on top of the same `proto/` tree.

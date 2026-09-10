# Overlay: otel_tracing

OpenTelemetry tracing for the base FastAPI service.

- Owner: Base Template Engineer
- Registry key: `otel_tracing` (bool, default `false`)
- Overlay id: `otel_tracing`
- Milestone: 2 (built in Phase 1 alongside the base, per D-024)
- Decisions: D-011 (OTLP HTTP/protobuf exporter, endpoint `:4318`), D-024

## What it adds

| Surface | Contribution |
| --- | --- |
| Gated subtree | `{{ python_package }}/observability/otel/` - `tracing.py` (`setup_tracing`, `instrument_app`, `shutdown_tracing`) |
| `pyproject.toml` | `opentelemetry-sdk==1.44.0`, `opentelemetry-exporter-otlp-proto-http==1.44.0`, `opentelemetry-instrumentation-fastapi==0.65b0` |
| `config/settings.py` | `otel_exporter_otlp_endpoint`, `otel_service_name` |
| `.env.example` | `APP_OTEL_EXPORTER_OTLP_ENDPOINT`, `APP_OTEL_SERVICE_NAME` |
| `lifespan.py` | startup hook (build provider, instrument app), shutdown hook (flush provider) |
| `tests/conftest.py` | `otel_span_exporter` fixture (in-memory, resets the global provider) |
| Boots test | `tests/overlays/test_otel_tracing_boots.py` |

## Design notes

- Manual in-process setup, not the `opentelemetry-instrument` launcher, so the
  run command is identical whether the overlay is on or off (deterministic).
- HTTP/protobuf exporter (D-011) so the base image never pulls `grpcio`.
- `set_test_span_exporter()` is the only test seam: when set, `setup_tracing`
  wires a `SimpleSpanProcessor` around the in-memory exporter instead of OTLP.
  No network in any test.
- Health probe paths (`health/live`, `health/ready`) are excluded from
  instrumentation.
- No compose service and no readiness check: tracing failure must not take the
  service out of rotation.

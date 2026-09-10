# ci/answers/

Complete, valid answers sets (scope §6): `service_name` plus every answer that
differs from a registry default or is forced by a `validation_rule`. Rendered by:

- `scripts/check_determinism.py` (each file rendered twice, asserted
  byte-identical),
- `scripts/verify_update.sh` (the `copier update` / `msvc-gen update` clean-apply
  gate),
- `harness/run.py` (targeted combinations),
- `docs/usage-examples.md` and `docs/non-interactive.md`.

| File | Shape |
| --- | --- |
| `zero-overlay.yml` | plain FastAPI service, no overlays |
| `otel-only.yml` | one overlay: OpenTelemetry (exercises `_fragments` exclusion + the `tests/overlays/` boots-test subtree) |
| `datastore-postgres-redis.yml` | PostgreSQL + Redis + Redis pub/sub |
| `rag-backend.yml` | Qdrant + OpenAI + LangChain (+ retrieval) + embedding pipeline (openai backend, 1536): a retrieval backend an agent queries |
| `agent-langgraph.yml` | PostgreSQL + Redis + a LangGraph graph checkpointed to Postgres |
| `monorepo-2svc.yml` | two-service monorepo (`api` + `worker`), gRPC + RabbitMQ transport, contract tests. Multi-service: `check_determinism.py` renders it as a degenerate single tree; the real per-service path is exercised by `verify_update.sh` |
| `sample-agent-service.yml` | Postgres + Redis + RabbitMQ + gRPC + OpenTelemetry |

Naming: name the file for the combo. Keep each file small - only the keys that
matter for that combo, plus `service_name`.

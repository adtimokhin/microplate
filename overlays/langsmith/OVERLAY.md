# Overlay: langsmith

LangSmith tracing hooks: `@traceable` re-exported from one place, plus a startup
`configure()` that resolves tracing state from settings and exports the
`LANGSMITH_*` names the SDK reads. Tracing is a zero-overhead pass-through until
an operator turns it on.

- Owner: AI Components Engineer
- Registry key: `langsmith` (bool, default `false`)
- Overlay id: `langsmith`
- Milestone: 5 (Phase 3)
- Requires: `llm_openai or llm_anthropic` (V-10) - LangSmith needs an LLM
  provider to trace
- Decisions: D-013 (offline, no network in tests), D-019 (frozen pins), D-030
  class 2 (`APP_LANGSMITH_API_KEY`: no default, required, secret), D-037 (base
  support for class-2 secret env vars)
- Research: `research/ai-stack.md` section 6

## What it adds

| Surface | Contribution |
| --- | --- |
| Gated subtree | `{{ python_package }}/observability/langsmith/` - `tracing.py` (`TracingConfig`, `configure()`, module-level `_config` holder + `get_tracing_config` / `set_tracing_config`), `pipeline.py` (a sample `@traceable` function), `__init__.py` (re-exports `traceable` + the above) |
| `pyproject.toml` | `langsmith==0.12.2` |
| `config/settings.py` | `langsmith_api_key` (required, no default), `langsmith_project` (`{{ service_slug }}`), `langsmith_tracing` (`"true"`) |
| `.env.example` | `APP_LANGSMITH_API_KEY=`, `APP_LANGSMITH_PROJECT={{ service_slug }}`, `APP_LANGSMITH_TRACING=true` |
| `lifespan.py` | startup hook: `configure()` -> mirror `TracingConfig` onto `app.state.langsmith`; shutdown hook: strip the `LANGSMITH_*` env names |
| `tests/conftest.py` | `langsmith_tracer` (autouse): forces `APP_LANGSMITH_TRACING=off`, seeds the class-2 `APP_LANGSMITH_API_KEY` placeholder, strips every `LANGSMITH_*` / `LANGCHAIN_*` name at teardown so a test that flips tracing on cannot leak |
| Boots test | `tests/overlays/test_langsmith_boots.py` |

## Design notes

- `@traceable` returns the wrapped function unchanged whenever `LANGSMITH_TRACING`
  is not `"true"` (research 6): no span, no client, no network. Generated
  handlers can carry `@traceable` unconditionally.
- `configure()` is I/O-free. It only reads settings and writes `os.environ`
  (`LANGSMITH_TRACING` / `_API_KEY` / `_PROJECT` when enabled; removes
  `LANGSMITH_TRACING` when disabled). Opening the exporter is the SDK's job and
  only happens on the first traced call with tracing on.
- No health check: tracing liveness is not a readiness concern, and a probe that
  hit LangSmith would add network to every readiness poll.
- No compose service (LangSmith is external SaaS).
- The registry default `APP_LANGSMITH_TRACING=true` means a deployed service
  traces out of the box once the key is set; the test fixture is what forces it
  off for the suite, per the boots-test contract.
- This overlay does not decorate the LLM overlays' handlers (overlays never edit
  each other's files). It ships the pattern - a service author adds `@traceable`
  to its own functions.

## Registry notes for RegistryArchitect

- Lifespan hook sets `app.state.langsmith` (a `TracingConfig`); no `health_checks`
  entry (matches the current registry).
- Fixture `langsmith_tracer` is `kind: mock`, autouse.
- `observability/` is an implicit namespace dir (no `__init__.py`), shared with
  `otel_tracing`'s `observability/otel/` when both are selected - same pattern
  `otel_tracing` already uses.

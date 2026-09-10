# Base Stack Research: Async FastAPI Microservice

Scope: current stable versions and minimal wiring notes for a deterministic Python microservice
generator. Target runtime Python 3.12, fully async, FastAPI on uvicorn.

Research date: 2026-09-07. All versions pulled from the PyPI JSON API and upstream docs on that
date. Every package line below is the latest stable release on PyPI as of the access date.

## TL;DR recommendation

- Packaging: `pyproject.toml` with the **hatchling** build backend, dependencies and lock managed
  by **uv** with a committed `uv.lock`. Rationale below in the Packaging section.
- Pin exact versions in generated output for reproducibility. The generator should emit both the
  `pyproject.toml` constraints and a resolved `uv.lock`.
- Run in containers as a **single uvicorn process per container** (`fastapi run` or
  `uvicorn --workers 1`), scale by replicas. Use `--workers N` only for the non-container
  single-VM case.

## Version matrix (latest stable on 2026-09-07)

### Runtime / web

| Package | Version | requires_python | Uploaded | Notes |
|---|---|---|---|---|
| fastapi | 0.141.1 | >=3.10 | 2026-07-29 | depends on `starlette>=0.46.0`, `pydantic>=2.9.0`, `typing-extensions>=4.8.0`, plus new `typing-inspection>=0.4.2`, `annotated-doc>=0.0.2` |
| fastapi-cli | 0.0.32 | >=3.10 | 2026-07-16 | provides `fastapi run` / `fastapi dev`. The `[standard]` extra now also pulls `fastapi-cloud-cli`; use the `standard-no-fastapi-cloud-cli` extra to keep generated services free of the cloud CLI |
| starlette | 1.6.0 | >=3.10 | 2026-08-08 | Starlette went 1.x; FastAPI 0.141.1 is compatible (`>=0.46.0`) |
| uvicorn | 0.52.4 | >=3.10 | 2026-08-19 | install as `uvicorn[standard]` to get uvloop + httptools + websockets + watchfiles |
| uvloop | 0.22.1 | >=3.8.1 | 2025-10-16 | pulled by `uvicorn[standard]` on non-Windows |
| httptools | 0.8.0 | >=3.9 | 2026-05-25 | pulled by `uvicorn[standard]` |
| websockets | 17.1 | >=3.11 | 2026-08-26 | pulled by `uvicorn[standard]`; only if you need WS |
| watchfiles | 1.2.0 | >=3.10 | 2026-05-18 | reload watcher, dev only |
| gunicorn | 26.2.0 | >=3.10 | 2026-08-24 | optional process manager; not needed if you use `uvicorn --workers` or one-process-per-container |

### Config / models

| Package | Version | requires_python | Uploaded |
|---|---|---|---|
| pydantic | 2.13.5 | >=3.9 | 2026-08-28 |
| pydantic-settings | 2.15.0 | >=3.10 | 2026-08-07 |
| typing-extensions | 4.16.0 | >=3.9 | 2026-07-02 |

### Logging

| Package | Version | requires_python | Uploaded | Notes |
|---|---|---|---|---|
| structlog | 26.1.0 | >=3.10 | 2026-06-06 | recommended primary logging library |
| python-json-logger | 4.2.0 | >=3.10 | 2026-08-15 | only if you stay on pure stdlib logging instead of structlog |
| asgi-correlation-id | 5.0.1 | >=3.10 | 2026-06-09 | optional drop-in request/correlation ID middleware; a ~40-line local middleware is also fine and keeps the dependency tree smaller |

### OpenTelemetry

| Package | Version | requires_python | Uploaded | Notes |
|---|---|---|---|---|
| opentelemetry-api | 1.44.0 | >=3.10 | 2026-07-16 | stable line |
| opentelemetry-sdk | 1.44.0 | >=3.10 | 2026-07-16 | stable line |
| opentelemetry-exporter-otlp | 1.44.0 | >=3.10 | 2026-07-16 | meta-package: pulls both gRPC and HTTP OTLP exporters |
| opentelemetry-instrumentation | 0.65b0 | >=3.10 | 2026-07-16 | contrib line is still versioned `0.<N>b0` (beta scheme), released in lockstep with core `1.44.0` |
| opentelemetry-instrumentation-fastapi | 0.65b0 | >=3.10 | 2026-07-16 | |
| opentelemetry-instrumentation-asgi | 0.65b0 | >=3.10 | 2026-07-16 | dependency of the FastAPI instrumentation |
| opentelemetry-semantic-conventions | 0.65b0 | >=3.10 | 2026-07-16 | |

Note on the beta scheme: the OpenTelemetry Python *core* (`api`, `sdk`, OTLP exporter) is stable at
`1.44.0`. The *contrib* / instrumentation packages have kept the `0.NbN` version scheme for years;
`0.65b0` is the matching release for core `1.44.0`. This is normal and considered production usable
by the project; the `b0` is not a pre-release in the pip sense that would be skipped by default
resolvers (it resolves normally). Pin it exactly.

### Testing

| Package | Version | requires_python | Uploaded | Notes |
|---|---|---|---|---|
| pytest | 9.1.1 | >=3.10 | 2026-06-19 | |
| pytest-asyncio | 1.4.0 | >=3.10 | 2026-05-26 | 1.x line; `asyncio_mode` and explicit fixture loop scope now matter (see below) |
| pytest-cov | 7.1.0 | >=3.9 | 2026-03-21 | optional |
| httpx | 0.28.1 | >=3.8 | 2024-12-06 | for `ASGITransport` in-process tests; still the latest 0.x |
| anyio | 4.15.1 | >=3.10 | 2026-09-05 | transitive via Starlette; `anyio.from_thread` / test utilities available |

### Tooling (optional but recommended in generated repo)

| Package | Version | Uploaded |
|---|---|---|
| ruff | 0.16.6 | 2026-09-03 |
| mypy | 2.3.1 | 2026-08-15 |
| uv | 0.12.10 | 2026-09-04 |
| hatchling | 1.32.0 | 2026-08-11 |

### Optional extras

| Package | Version | Uploaded | Use |
|---|---|---|---|
| sse-starlette | 3.4.11 | 2026-09-05 | Server-Sent Events responses (`EventSourceResponse`) |
| orjson | 3.12.0 | 2026-08-14 | fast JSON; use with `ORJSONResponse` as default response class |

## FastAPI wiring notes

### Lifespan handler (current pattern; `on_event` is deprecated)

Use an `asynccontextmanager` passed as `lifespan=`. Everything before `yield` runs at startup
before the server accepts requests; everything after runs at graceful shutdown. Attach shared
resources (DB pools, HTTP clients, otel providers) to `app.state` or a typed context object.

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    app.state.http = make_http_client()
    await app.state.http.__aenter__()
    yield
    # shutdown
    await app.state.http.__aexit__(None, None, None)

app = FastAPI(lifespan=lifespan)
```

If `lifespan=` is given, the deprecated `@app.on_event("startup"/"shutdown")` handlers do not run.
Source: https://fastapi.tiangolo.com/advanced/events/ (accessed 2026-09-07).

### Dependency injection

- `Depends()` with `Annotated` is the current idiom:
  `db: Annotated[Session, Depends(get_db)]`. Define reusable aliases:
  `DbDep = Annotated[AsyncSession, Depends(get_db)]`.
- Async generator dependencies (`async def get_db(): ... yield ... ` with cleanup after yield) are
  the standard way to scope per-request resources.
- App-wide singletons: create in `lifespan`, read from `request.app.state` inside a small
  dependency function rather than importing a global.
- Router-level and app-level dependencies: `APIRouter(dependencies=[Depends(verify_token)])` and
  `FastAPI(dependencies=[...])` for cross-cutting checks.
- `dependency_overrides` on the app object is the supported test seam.

### Router structure

Standard layout for a generated service:

```
app/
  main.py            # create_app(), lifespan, middleware, router includes
  api/
    __init__.py
    router.py        # APIRouter aggregating versioned sub-routers
    v1/
      __init__.py
      health.py      # /healthz, /readyz
      <feature>.py
  core/
    config.py        # pydantic-settings Settings + get_settings()
    logging.py       # structlog configuration
    otel.py          # tracer/meter provider setup
  models/ | schemas/ # pydantic models
```

- Each feature module defines `router = APIRouter(prefix="/things", tags=["things"])`.
- `api/router.py` does `api_router = APIRouter(); api_router.include_router(health.router)` etc.
- `main.py` does `app.include_router(api_router, prefix="/api/v1")`.
- Prefer a `create_app()` factory so tests can build isolated instances.

### Health / readiness endpoints

No built-in helper; define explicitly. Common convention (Kubernetes-aligned):

- `GET /healthz` (liveness): returns `200 {"status": "ok"}` with no dependency checks. Must not
  touch DB or downstream services. Cheap and always fast.
- `GET /readyz` (readiness): checks critical dependencies (DB `SELECT 1`, cache ping, required
  downstream reachable). Returns `200` when ready to serve, `503` with a per-check body otherwise.
- Optional `GET /startupz` for slow init if needed, otherwise fold into readiness.
- Keep these on the app root (not under `/api/v1`) and exclude them from tracing and access logs
  (`excluded_urls="healthz,readyz"` for the otel instrumentation).

```python
from fastapi import APIRouter, Response, status

router = APIRouter(tags=["health"])

@router.get("/healthz")
async def healthz():
    return {"status": "ok"}

@router.get("/readyz")
async def readyz(response: Response):
    checks = {"db": await ping_db()}
    ok = all(checks.values())
    response.status_code = status.HTTP_200_OK if ok else status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if ok else "degraded", "checks": checks}
```

### SSE / streaming responses

- Plain chunked streaming: `from fastapi.responses import StreamingResponse`, return it wrapping an
  async generator; set `media_type`. Built in, no extra dependency.
- Server-Sent Events: use `sse-starlette` (3.4.11), `from sse_starlette.sse import EventSourceResponse`,
  return `EventSourceResponse(event_generator())` where the generator yields `dict(data=..., event=...)`
  or strings. It handles the `text/event-stream` framing, ping keep-alives, and disconnect
  detection via the request's receive channel.
- For long-lived streams, check `await request.is_disconnected()` in the generator loop and break.
- Streaming responses bypass the normal response-model serialization; validate/serialize manually.
- Note: middleware that buffers the full body (some logging or compression middlewares) will break
  streaming; keep streaming routes clear of those or make the middleware pass-through for
  `text/event-stream`.

## uvicorn / uvloop notes

- Install target: `uvicorn[standard]==0.52.4`. On Linux/macOS this pulls `uvloop` and `httptools`,
  which uvicorn selects automatically (`--loop auto --http auto`). No code change needed to use
  uvloop; it is picked when installed.
- Local/dev: `fastapi dev app/main.py` (adds reload) or
  `uvicorn app.main:app --reload --port 8000`.
- Production, container (recommended): one process per container.
  `fastapi run app/main.py --host 0.0.0.0 --port 8000` (this is `uvicorn` under the hood with
  production defaults and `--workers 1` unless told otherwise), or directly
  `uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log --loop uvloop --http httptools`.
  Scale horizontally with more replicas; let the orchestrator handle restarts.
- Production, single VM without an orchestrator: `uvicorn app.main:app --workers $(nproc)` or
  `fastapi run --workers 4 app/main.py`. Uvicorn runs its own multiprocess manager; a separate
  Gunicorn is no longer required. The old `uvicorn.workers.UvicornWorker` Gunicorn worker class is
  deprecated in favor of uvicorn's native `--workers`.
- Graceful shutdown: uvicorn traps SIGTERM/SIGINT, stops accepting new connections, waits for
  in-flight requests up to `--timeout-graceful-shutdown` (seconds; default is to wait
  indefinitely, so set it, e.g. `--timeout-graceful-shutdown 30`). In Docker use exec-form `CMD`
  so the process gets PID 1 signals directly; in Kubernetes set
  `terminationGracePeriodSeconds` >= that timeout and add a `preStop` sleep if you need the
  Service endpoints to drain first. Run lifespan shutdown cleanup (close pools, flush otel) in the
  `lifespan` context after `yield`.
- Sources: https://fastapi.tiangolo.com/deployment/server-workers/ and
  https://fastapi.tiangolo.com/deployment/docker/ (accessed 2026-09-07);
  https://www.uvicorn.org/ deployment section (site returned 502 intermittently on 2026-09-07,
  content cross-checked against the FastAPI deployment docs which mirror it).

## pydantic v2 + pydantic-settings notes

- Version pins: `pydantic==2.13.5`, `pydantic-settings==2.15.0`.
- Settings class uses `SettingsConfigDict` via `model_config` (the v1 inner `class Config` is
  gone):

```python
from functools import lru_cache
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

class DatabaseSettings(BaseModel):
    url: str
    pool_size: int = 10

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",   # DATABASE__URL=... -> settings.database.url
        env_prefix="",               # or "APP_"
        secrets_dir="/run/secrets",  # Docker/K8s file-based secrets; optional
        extra="ignore",
        case_sensitive=False,
    )
    environment: str = "local"
    log_level: str = "INFO"
    database: DatabaseSettings
    otel_exporter_otlp_endpoint: str | None = None

@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
```

- Precedence (highest to lowest): init kwargs, then environment variables, then `.env` file, then
  values from `secrets_dir`, then field defaults. `.env` and real env vars always beat
  `secrets_dir`.
- Nested config: use nested `BaseModel` fields plus `env_nested_delimiter="__"`; env var
  `DATABASE__POOL_SIZE=20` maps to `settings.database.pool_size`. A JSON string in a single env
  var also works for a whole nested object.
- Secrets: `secrets_dir` reads one file per field name (Docker secret / K8s projected volume
  style). For a single field you can also use `pydantic.SecretStr` as the type to keep the value
  out of `repr`/logs.
- To customize source order or add sources (Vault, AWS SSM, TOML), override
  `settings_customise_sources(cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings)`.
- `get_settings()` behind `lru_cache` is the standard DI provider:
  `SettingsDep = Annotated[Settings, Depends(get_settings)]`.
- Source: https://pydantic.dev/docs/validation/latest/concepts/pydantic_settings/ (redirected from
  docs.pydantic.dev; accessed 2026-09-07).

## Structured logging notes

Recommendation: **structlog 26.1.0** as the primary interface, configured to render JSON in
non-local environments and a colored console renderer locally, routed through the stdlib `logging`
module so uvicorn/other library logs share the same formatting.

Key pieces:

- Processor chain includes `structlog.contextvars.merge_contextvars` first so per-request context
  bound with `structlog.contextvars.bind_contextvars(...)` is attached to every log line emitted
  during that request (contextvars are async-task-safe, unlike thread locals).
- Use `structlog.stdlib.ProcessorFormatter` to also format logs coming from stdlib loggers
  (uvicorn, sqlalchemy) with the same JSON renderer. Set uvicorn to not install its own handlers
  or override them after startup.
- Final renderer: `structlog.processors.JSONRenderer()` for prod, `structlog.dev.ConsoleRenderer()`
  for local.
- Standard processors to include: `structlog.processors.add_log_level`,
  `structlog.processors.TimeStamper(fmt="iso", utc=True)`,
  `structlog.processors.StackInfoRenderer()`, `structlog.processors.format_exc_info` (or
  `dict_tracebacks` for structured tracebacks), `structlog.processors.EventRenamer("message")` if
  you want the `event` key called `message`.

```python
import logging, structlog

def configure_logging(json_logs: bool, level: str) -> None:
    timestamper = structlog.processors.TimeStamper(fmt="iso", utc=True)
    shared = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.StackInfoRenderer(),
        timestamper,
    ]
    structlog.configure(
        processors=shared + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(logging.getLevelName(level)),
        cache_logger_on_first_use=True,
    )
    renderer = (
        structlog.processors.JSONRenderer() if json_logs
        else structlog.dev.ConsoleRenderer()
    )
    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared,
        processors=[structlog.stdlib.ProcessorFormatter.remove_processors_meta, renderer],
    )
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        lg = logging.getLogger(name)
        lg.handlers = []
        lg.propagate = True
```

Correlation / request ID middleware pattern for FastAPI:

- Pure-stdlib approach: a small ASGI/BaseHTTPMiddleware that, per request, reads an incoming
  `X-Request-ID` (or `X-Correlation-ID`) header, generates a UUID4 if absent, stores it in a
  module-level `ContextVar`, binds it via `structlog.contextvars.bind_contextvars(request_id=...)`,
  clears contextvars at the end (`structlog.contextvars.clear_contextvars()`), and sets the
  `X-Request-ID` response header.
- Ready-made: `asgi-correlation-id==5.0.1` provides exactly this middleware plus a logging filter;
  add `CorrelationIdMiddleware` and it manages the contextvar and response header. Integrates with
  structlog by binding into contextvars.
- If OpenTelemetry tracing is enabled, also add `trace_id` / `span_id` to the log context by
  pulling `trace.get_current_span().get_span_context()` in a structlog processor, so logs and
  traces correlate.
- Order: request-ID middleware should be outermost (added last) so every downstream log line and
  the access log have the ID.
- Source: https://www.structlog.org/en/stable/getting-started.html and the contextvars /
  standard-library integration pages (accessed 2026-09-07).

## OpenTelemetry Python notes

Two setup styles; the generator should support both but default to **manual in-process setup** for
determinism (auto-instrumentation via the `opentelemetry-instrument` launcher changes the run
command and pulls `opentelemetry-distro`).

Packages to pin: `opentelemetry-api==1.44.0`, `opentelemetry-sdk==1.44.0`,
`opentelemetry-exporter-otlp==1.44.0`, `opentelemetry-instrumentation-fastapi==0.65b0`.

Minimal manual tracer setup:

```python
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

def setup_tracing(service_name: str, environment: str, endpoint: str | None) -> None:
    resource = Resource.create({
        "service.name": service_name,
        "service.version": "0.1.0",
        "deployment.environment.name": environment,
    })
    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(endpoint=endpoint) if endpoint else OTLPSpanExporter()
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
```

FastAPI instrumentation (call after `create_app`, before serving):

```python
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

FastAPIInstrumentor.instrument_app(
    app,
    excluded_urls="healthz,readyz,metrics",
    # server_request_hook=..., to add custom span attributes
)
```

- Configuration precedence: env vars are honored by the SDK directly:
  `OTEL_SERVICE_NAME`, `OTEL_EXPORTER_OTLP_ENDPOINT`, `OTEL_EXPORTER_OTLP_PROTOCOL`
  (`grpc` or `http/protobuf`), `OTEL_RESOURCE_ATTRIBUTES`, `OTEL_TRACES_SAMPLER`. Prefer feeding
  these through `Settings` and passing explicitly, or let the SDK read them. Do not set both ways
  inconsistently.
- OTLP exporter choice: `opentelemetry-exporter-otlp` is a meta-package that installs both the
  gRPC (`...proto.grpc...`) and HTTP (`...proto.http...`) exporters. For a slimmer image depend on
  just `opentelemetry-exporter-otlp-proto-http==1.44.0` and use the HTTP exporter.
- Graceful shutdown: call `trace.get_tracer_provider().shutdown()` in the `lifespan` shutdown path
  so the `BatchSpanProcessor` flushes.
- Auto-instrumentation alternative (if chosen): add `opentelemetry-distro==0.65b0` and
  `opentelemetry-instrumentation-fastapi==0.65b0`, run
  `opentelemetry-bootstrap -a install` at build time, and change the container command to
  `opentelemetry-instrument fastapi run app/main.py`. Env-var driven, no code. Downside for a
  generator: the run command and image now differ between "otel on" and "otel off", and
  `opentelemetry-bootstrap` resolves versions at build time (non-deterministic) unless you freeze
  its output.
- Metrics and logs: analogous `MeterProvider` / `LoggerProvider` setup from `opentelemetry-sdk`;
  wire only if the service needs OTLP metrics/logs, otherwise leave metrics to a Prometheus
  endpoint and logs to structlog stdout.
- Sources: https://opentelemetry.io/docs/languages/python/getting-started/ and
  https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/fastapi/fastapi.html
  (accessed 2026-09-07).

## Packaging and dependency management

Recommendation: `pyproject.toml`, **hatchling** build backend, **uv** for resolution/locking with
a committed `uv.lock`.

Why hatchling as build backend:

- PEP 517 standard, `hatchling` is the reference-quality lightweight backend, no runtime deps, and
  is what the Python Packaging Authority tutorial uses. It is decoupled from any particular
  workflow tool (unlike `poetry-core`, which pairs with Poetry, or `pdm-backend` with PDM).
- uv itself does not (yet) ship its own build backend as the default for libraries; it defaults to
  hatchling when you `uv init --package`. For an application (not a library) that is never built
  into a wheel you can also use `uv init` without a build system at all, but including hatchling
  keeps the option open and makes `pip install .` / Docker `uv sync` uniform.
- `poetry-core` is fine and stable but ties the mental model to Poetry semantics; `setuptools`
  works but needs more config for src layout and is heavier.

Why uv + `uv.lock`:

- uv is the current fast, single-binary resolver/installer; `uv.lock` is a cross-platform,
  hash-pinned, fully-resolved lockfile that is the deterministic artifact a generator wants.
  `uv sync --frozen` / `--locked` gives byte-reproducible environments.
- uv is stable and under active release (0.12.10 on 2026-09-04). It reads standard
  `[project]` metadata, so the `pyproject.toml` stays tool-agnostic and `pip` still works as a
  fallback (`pip install -r` from `uv export`, or `pip install .`).
- Alternative considered: `pip` + `pip-tools` (`requirements.txt` + hashes). Works, widely
  understood, but slower and two-file (`.in` / `.txt`) and no cross-platform resolution. Poetry:
  good UX but its lock format and resolver are Poetry-specific and slower. PDM: fine, smaller
  ecosystem. For a generator that values determinism and speed, uv is the better default; keep the
  `pyproject.toml` clean enough that a consumer can drop uv and use pip.

`pyproject.toml` skeleton the generator should emit:

```toml
[project]
name = "my-service"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi==0.141.1",
    "uvicorn[standard]==0.52.4",
    "pydantic==2.13.5",
    "pydantic-settings==2.15.0",
    "structlog==26.1.0",
]

[project.optional-dependencies]
otel = [
    "opentelemetry-sdk==1.44.0",
    "opentelemetry-exporter-otlp==1.44.0",
    "opentelemetry-instrumentation-fastapi==0.65b0",
]

[dependency-groups]
dev = [
    "pytest==9.1.1",
    "pytest-asyncio==1.4.0",
    "pytest-cov==7.1.0",
    "httpx==0.28.1",
    "ruff==0.16.6",
    "mypy==2.3.1",
]

[build-system]
requires = ["hatchling==1.32.0"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["app"]
```

Use `[dependency-groups]` (PEP 735, supported by uv and pip) for dev deps rather than an
`optional-dependencies` extra, so they never leak into a `pip install my-service`.

## pytest + pytest-asyncio

- Pins: `pytest==9.1.1`, `pytest-asyncio==1.4.0`.
- Recommended mode: `asyncio_mode = "auto"` so every `async def test_*` runs without a per-test
  `@pytest.mark.asyncio` marker. Set it in `pyproject.toml`.
- Explicitly set `asyncio_default_fixture_loop_scope` (currently emits a deprecation warning if
  unset; the future default is `function`). Use `"function"` unless you have an expensive
  session-scoped async fixture, in which case use `"session"` and be deliberate about it.
- Also set `asyncio_default_test_loop_scope` (1.x) to `"function"` for isolation.

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
asyncio_default_fixture_loop_scope = "function"
asyncio_default_test_loop_scope = "function"
addopts = "-ra -q"
testpaths = ["tests"]
```

- Async HTTP tests without a running server: httpx `ASGITransport`:

```python
import httpx, pytest
from app.main import create_app

@pytest.fixture
async def client():
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        # trigger lifespan explicitly if needed via httpx_lifespan or asgi-lifespan
        yield c
```

- To exercise `lifespan` in tests use `asgi-lifespan` (`LifespanManager`) or Starlette's
  `TestClient` (sync) which runs lifespan in a context manager. For fully-async lifespan tests,
  `asgi-lifespan==2.1.0` is the common helper.
- Source: https://pytest-asyncio.readthedocs.io/en/latest/reference/configuration.html
  (accessed 2026-09-07).

## Dockerfile

Recommended base image: `python:3.12-slim-bookworm` (Debian 13 "trixie" slim,
`python:3.12-slim-trixie`, is also available now; bookworm is the conservative choice with the
widest wheel compatibility). Avoid Alpine for a FastAPI service: musl breaks or slows many wheels
(pydantic-core, uvloop, grpc for OTLP) and there is no real size win after you add the toolchain.

Multi-stage uv-based pattern (deterministic, non-root, no build tools in final image):

```dockerfile
# syntax=docker/dockerfile:1

FROM python:3.12-slim-bookworm AS builder
COPY --from=ghcr.io/astral-sh/uv:0.12.10 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# deps layer: cached unless lock/metadata change
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project --no-dev
# project layer
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev

FROM python:3.12-slim-bookworm AS runtime
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
RUN groupadd --system app && useradd --system --gid app --home /app app
WORKDIR /app
COPY --from=builder --chown=app:app /app /app
USER app
EXPOSE 8000
# exec form so SIGTERM reaches the process for graceful shutdown
CMD ["fastapi", "run", "app/main.py", "--host", "0.0.0.0", "--port", "8000"]
```

Notes:

- Pin the uv image by exact tag (`ghcr.io/astral-sh/uv:0.12.10`), not `:latest`, for determinism.
- `--no-install-project` on the first `uv sync` installs only third-party deps so that layer
  caches independently of your source changes. The second `uv sync` installs the project itself.
- `--no-dev` keeps test/lint tools out of the runtime image.
- `UV_PYTHON_DOWNLOADS=never` forces use of the image's system Python 3.12 rather than uv fetching
  its own.
- The venv is copied whole from builder to runtime; `PATH` points at `/app/.venv/bin` so
  `fastapi` / `uvicorn` resolve.
- Single stage is acceptable (the Astral FastAPI guide shows a single-stage
  `uv sync --frozen --no-cache` then `CMD [".venv/bin/fastapi", "run", ...]`); multi-stage is
  preferred here only to keep the uv binary and caches out of the shipped image.
- If OTLP over gRPC is used, `grpcio` ships manylinux wheels so no compiler is needed on
  bookworm/glibc; on Alpine it would need building. Another reason to stay on slim-bookworm.
- Add a `HEALTHCHECK` only if not orchestrated; in K8s use probes instead:
  `HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status==200 else 1)"`.
- Sources: https://docs.astral.sh/uv/guides/integration/docker/ ,
  https://docs.astral.sh/uv/guides/integration/fastapi/ ,
  https://fastapi.tiangolo.com/deployment/docker/ (all accessed 2026-09-07). The FastAPI page's own
  example still uses `pip` + `requirements.txt` and `python:3.14`; the uv pattern above is
  preferred for this generator and matches the Astral guides.

## docker-compose

- The top-level `version:` key is **obsolete**. Compose v2 (v2.40+ in 2026) ignores it and prints a
  deprecation warning if present. Do not emit it. Compose always validates against the latest
  schema (the "Compose Specification"). Optionally emit a top-level `name:` for the project name.
- Healthcheck syntax (current fields): `test`, `interval`, `timeout`, `retries`, `start_period`,
  and `start_interval` (since Compose v2.20.2 / Docker Engine 25). `test` is `["CMD", ...]` or
  `["CMD-SHELL", "..."]`.

```yaml
name: my-service

services:
  api:
    build:
      context: .
      target: runtime
    ports:
      - "8000:8000"
    environment:
      ENVIRONMENT: local
      DATABASE__URL: postgresql+asyncpg://app:app@db:5432/app
      OTEL_EXPORTER_OTLP_ENDPOINT: http://otel-collector:4317
    depends_on:
      db:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz').status==200 else 1)"]
      interval: 10s
      timeout: 3s
      retries: 5
      start_period: 15s
      start_interval: 2s

  db:
    image: postgres:17-bookworm
    environment:
      POSTGRES_USER: app
      POSTGRES_PASSWORD: app
      POSTGRES_DB: app
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U app -d app"]
      interval: 5s
      timeout: 3s
      retries: 10
    volumes:
      - pgdata:/var/lib/postgresql/data

volumes:
  pgdata:
```

- Use `depends_on: { <svc>: { condition: service_healthy } }` so the API waits for a healthy DB.
- Sources: https://docs.docker.com/reference/compose-file/services/ (healthcheck),
  https://docs.docker.com/reference/compose-file/version-and-name/ (version obsolete)
  (accessed 2026-09-07).

## Open questions / follow-ups for the team

- Confirm target Python is 3.12 exactly vs `>=3.12`. All listed packages support 3.12; some now
  also test 3.14/3.15. `requires-python = ">=3.12"` is safe.
- Decide OTLP transport: gRPC (`opentelemetry-exporter-otlp`, larger) vs HTTP
  (`opentelemetry-exporter-otlp-proto-http`, slimmer). Recommend HTTP unless a collector detail
  forces gRPC.
- Decide whether generated services depend on `asgi-correlation-id` or ship a vendored ~40-line
  middleware. Recommend vendored middleware to minimize the dependency surface of a generated repo.
- `sse-starlette` only if streaming/SSE overlay is selected; keep it out of the base.

## Sources

- FastAPI release notes / changelog: https://fastapi.tiangolo.com/release-notes/ (accessed 2026-09-07)
- FastAPI lifespan events: https://fastapi.tiangolo.com/advanced/events/ (accessed 2026-09-07)
- FastAPI server workers: https://fastapi.tiangolo.com/deployment/server-workers/ (accessed 2026-09-07)
- FastAPI in containers: https://fastapi.tiangolo.com/deployment/docker/ (accessed 2026-09-07)
- Uvicorn site / deployment: https://www.uvicorn.org/ (accessed 2026-09-07; 502 intermittently)
- pydantic-settings: https://pydantic.dev/docs/validation/latest/concepts/pydantic_settings/ (accessed 2026-09-07)
- structlog getting started: https://www.structlog.org/en/stable/getting-started.html (accessed 2026-09-07)
- OpenTelemetry Python getting started: https://opentelemetry.io/docs/languages/python/getting-started/ (accessed 2026-09-07)
- OpenTelemetry FastAPI instrumentation: https://opentelemetry-python-contrib.readthedocs.io/en/latest/instrumentation/fastapi/fastapi.html (accessed 2026-09-07)
- uv Docker integration: https://docs.astral.sh/uv/guides/integration/docker/ (accessed 2026-09-07)
- uv FastAPI integration: https://docs.astral.sh/uv/guides/integration/fastapi/ (accessed 2026-09-07)
- pytest-asyncio configuration: https://pytest-asyncio.readthedocs.io/en/latest/reference/configuration.html (accessed 2026-09-07)
- Compose file services / healthcheck: https://docs.docker.com/reference/compose-file/services/ (accessed 2026-09-07)
- Compose version-and-name (version obsolete): https://docs.docker.com/reference/compose-file/version-and-name/ (accessed 2026-09-07)
- PyPI JSON API for all version/date data: https://pypi.org/pypi/<package>/json (accessed 2026-09-07)

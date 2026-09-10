# Usage examples

Four worked examples, each run end to end. Every command and every block of
output below is real: generated with `msvc-gen`, then `uv run pytest`, then the
service booted and `curl`ed. Runs were done on `build/all-phases` (33 registry
keys `build_status: implemented`), Copier 9.18.2, CPython 3.12.11, `uv` 0.7.13,
Docker 27.4.0. Substitute `--vcs-ref v0.4.0` (a release tag) for a pinned run.

Every example is non-interactive: no prompts, answers come from `--data` or
`--answers-file`. See `docs/non-interactive.md` for the full input surface.

---

## 1. A plain service

No overlays. A FastAPI app with health endpoints, JSON logging, correlation IDs,
Docker, and a pytest suite.

### Generate

```sh
msvc-gen new --output ./hello-svc --vcs-ref v0.4.0 \
  --data service_name=hello-svc
```

Output (trimmed):

```
    create  hello_svc/main.py
    create  hello_svc/health.py
    create  hello_svc/lifespan.py
    create  hello_svc/config/settings.py
    create  hello_svc/middleware/correlation.py
    create  hello_svc/api/router.py
    create  tests/test_app_boots.py
    create  pyproject.toml
    create  Dockerfile
    create  docker-compose.yml
    create  .github/workflows/ci.yml
    create  .copier-answers.yml
```

### Test

```sh
cd hello-svc
uv sync
uv run pytest -q
```

```
.....                                                                     [100%]
5 passed, 2 warnings in 0.89s
```

### Run and curl

```sh
uv run uvicorn hello_svc.main:app --port 8000
```

```sh
$ curl -s -i localhost:8000/health/live
HTTP/1.1 200 OK

{"status":"ok"}

$ curl -s localhost:8000/health/ready
{"status":"ready","checks":{}}

$ curl -s -i -H 'X-Request-ID: demo-123' localhost:8000/
HTTP/1.1 200 OK
x-request-id: demo-123

{"service":"hello-svc","environment":"local"}
```

The server logs are structured JSON and carry the request id through:

```
{"event": "Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)", "level": "info", "timestamp": "2026-09-10T01:04:48.356959Z"}
{"event": "127.0.0.1:52704 - \"GET / HTTP/1.1\" 200", "request_id": "demo-123", "level": "info", "timestamp": "2026-09-10T01:04:49.565161Z"}
```

`/health/ready`'s `checks` object is empty because nothing else was selected.
Each overlay adds one entry to it.

---

## 2. A tool server (function-call endpoints + tracing)

`tool_scaffold` for function-call-shaped routes, `otel_tracing` for
OpenTelemetry. Everything here runs offline, no datastore.

### Generate

```sh
cat > tools.yml <<'EOF'
service_name: tool-svc
tool_scaffold: true
otel_tracing: true
EOF

msvc-gen new --output ./tool-svc --vcs-ref v0.4.0 --answers-file tools.yml
```

```
    create  tool_svc/tools/registry.py
    create  tool_svc/tools/examples.py
    create  tool_svc/tools/routes.py
    create  tool_svc/observability/otel/tracing.py
    create  tool_svc/api/router.py
```

### Test

```sh
cd tool-svc && uv sync && uv run pytest -q
```

```
8 passed, 2 warnings in 9.79s
```

### Run and curl

```sh
uv run uvicorn tool_svc.main:app --port 8000
```

`GET /tools` returns the OpenAI function-spec catalogue:

```sh
$ curl -s localhost:8000/tools
[
  {
    "name": "echo",
    "description": "Echo the given text back unchanged.",
    "parameters": {
      "properties": {"text": {"description": "Text to echo back verbatim.", "title": "Text", "type": "string"}},
      "required": ["text"], "title": "EchoRequest", "type": "object"
    }
  },
  {
    "name": "add",
    "description": "Add two numbers and return their sum.",
    "parameters": {
      "properties": {
        "a": {"description": "First addend.", "title": "A", "type": "number"},
        "b": {"description": "Second addend.", "title": "B", "type": "number"}
      },
      "required": ["a", "b"], "title": "AddRequest", "type": "object"
    }
  }
]
```

Call a tool:

```sh
$ curl -s -X POST localhost:8000/tools/add -H 'content-type: application/json' -d '{"a": 2, "b": 3}'
{"sum":5.0}

$ curl -s -X POST localhost:8000/tools/echo -H 'content-type: application/json' -d '{"text": "hi"}'
{"text":"hi"}
```

Each tool is one operation in `/openapi.json` with a stable `operationId`, so a
function-calling client can consume the schema directly:

```
GET  /tools        -> list_tools
POST /tools/echo   -> echo
POST /tools/add    -> add
```

---

## 3. A service with datastores (Postgres + Redis, real containers)

`db_postgres` + `db_redis` + `redis_pubsub`. This one boots under
`docker compose` so the readiness checks hit real databases.

### Generate and test

```sh
msvc-gen new --output ./data-svc --vcs-ref v0.4.0 \
  --answers-file ci/answers/datastore-postgres-redis.yml

cd data-svc && uv sync && uv run pytest -q
```

```
8 passed, 2 warnings in 1.94s
```

The generated `docker-compose.yml` has the `app` service plus `postgres:17.6`
and `redis:8.0`, with `app` waiting on both being healthy. The generated
`.env.example` points the app at the compose service names
(`postgresql+asyncpg://app:app@postgres:5432/app`, `redis://redis:6379/0`).

### Boot the stack

```sh
$ docker compose up -d --build --wait
 Container shop-orders-redis-1     Healthy
 Container shop-orders-postgres-1  Healthy
 Container shop-orders-app-1       Healthy

$ docker compose ps
NAME                     IMAGE             SERVICE    STATUS
shop-orders-app-1        shop-orders-app   app        Up (healthy)   0.0.0.0:8000->8000/tcp
shop-orders-postgres-1   postgres:17.6     postgres   Up (healthy)   0.0.0.0:5432->5432/tcp
shop-orders-redis-1      redis:8.0         redis      Up (healthy)   0.0.0.0:6379->6379/tcp
```

### Curl the aggregated readiness

```sh
$ curl -s localhost:8000/health/ready
{
  "status": "ready",
  "checks": {
    "db_postgres": {"healthy": true, "detail": ""},
    "db_redis": {"healthy": true, "detail": ""}
  }
}
```

Both checks are green because they opened real connections to the running
containers. Tear down with `docker compose down -v`.

---

## 4. A RAG backend (Qdrant + OpenAI + LangChain + embeddings)

`ci/answers/rag-backend.yml`: `db_qdrant` + `llm_openai` + `langchain`
(+ `langchain_retrieval`) + `embedding_pipeline` with the `openai` embedding
backend (vector size 1536). LLM traffic is stubbed offline in tests, so `pytest`
needs no API key.

### Generate and test

```sh
msvc-gen new --output ./rag-search --vcs-ref v0.4.0 \
  --answers-file ci/answers/rag-backend.yml

cd rag-search && uv sync && uv run pytest -q
```

```
13 passed, 1 warning in 28.88s
```

That includes the overlay boots tests: the LangChain summarize chain runs
against a `FakeListChatModel`, the retrieval chain against a fixed document
list, the embedder against fixed zero vectors. No network, no key.

### Run and inspect the wired endpoints

```sh
APP_LLM_OPENAI_API_KEY=sk-... uv run uvicorn rag_search.main:app --port 8000
```

```sh
$ curl -s localhost:8000/openapi.json | jq -r '.paths | keys[]'
/
/health/live
/health/ready
/langchain/retrieve
/langchain/summarize
/llm/openai/summarize
```

`/health/ready` aggregates every selected component. Without a Qdrant server it
reports honestly:

```sh
$ curl -s localhost:8000/health/ready
{
  "status": "not_ready",
  "checks": {
    "db_qdrant": {"healthy": false, "detail": "UnexpectedResponse()"},
    "llm_openai": {"healthy": true, "detail": "api key configured"},
    "embedding_pipeline": {"healthy": true, "detail": ""}
  }
}
```

Bring Qdrant up the same way as example 3 (`docker compose up -d --build
--wait`, the generated compose file includes `qdrant/qdrant`) and `db_qdrant`
goes green. Calling `/langchain/summarize` or `/llm/openai/summarize` for real
needs a valid `APP_LLM_OPENAI_API_KEY` and network; the deterministic tests do
not.

---

## Next

- Full component list: `README.md`.
- Multi-service (`monorepo` / `multi_repo`) generation and `services_config`:
  `docs/non-interactive.md` and `docs/services-config-schema.md`.
- Updating a generated project: `docs/update-verification.md`.

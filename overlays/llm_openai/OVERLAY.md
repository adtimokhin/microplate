# Overlay: llm_openai

Async OpenAI client for the FastAPI service: `AsyncOpenAI` bound to the lifespan,
`tenacity` retry around a deterministic sample call, and one
`POST /llm/openai/summarize` route.

- Owner: AI Components Engineer
- Registry key: `llm_openai` (bool, default `false`)
- Overlay id: `llm_openai`
- Milestone: 5 (Phase 3)
- Decisions: D-002 (OpenAI + Anthropic are the v1 providers), D-004 (async
  stack), D-013 (stub via `*_BASE_URL` redirect / httpx2 `MockTransport`, never
  respx/vcrpy), D-019 (frozen pins), D-030 class 2 (API key: no default,
  `required: true`, `secret: true`), D-032 (`api_router` slot)
- Research: `research/ai-stack.md` sections 1, 2

## What it adds

| Surface | Contribution |
| --- | --- |
| Gated subtree | `{{ python_package }}/llm/openai/` - `client.py` (`init_client` / `get_client` / `close_client`, module-level `_client` holder, `max_retries=0` so tenacity owns retry), `summarize.py` (`@retry`-wrapped one-sentence summary via Chat Completions, `temperature=0`), `routes.py` (`POST /llm/openai/summarize`) |
| `pyproject.toml` | `openai==3.8.0`, `tenacity==9.1.4` |
| `config/settings.py` | `llm_openai_api_key` (required, no default), `llm_openai_model` (`gpt-4o-mini`), `llm_openai_timeout_s` (`30`), `llm_openai_base_url` (`None`) |
| `.env.example` | `APP_LLM_OPENAI_API_KEY=`, `APP_LLM_OPENAI_MODEL=gpt-4o-mini`, `APP_LLM_OPENAI_TIMEOUT_S=30`, `# APP_LLM_OPENAI_BASE_URL=` |
| `{{ python_package }}/api/router.py` | `api_router.py` fragment: imports the `/llm/openai` router and `include_router`s it at import time (D-032) |
| `lifespan.py` | startup hook (`init_client()`, mirror to `app.state.llm_openai`), shutdown hook (`close_client()`) |
| `health.py` | `check_llm_openai()` - client built + API key configured. No network round-trip (an LLM call per readiness poll would burn tokens). |
| `tests/conftest.py` | `openai_client` (autouse). Default (`mock_transport`): patches `init_client` to build an `AsyncOpenAI` over an `httpx2.MockTransport` returning canned Chat Completions JSON, and sets `APP_LLM_OPENAI_API_KEY`. `fake_server`: a stdlib `http.server` stub, `APP_LLM_OPENAI_BASE_URL` pointed at it. |
| Boots test | `tests/overlays/test_llm_openai_boots.py` |

## Design notes

- No compose service: OpenAI is an external SaaS. Nothing to bring up under
  `docker compose`.
- The SDK's built-in retries are disabled (`max_retries=0`); `tenacity`
  (`stop_after_attempt(3)`, `wait_exponential`) wraps the sample call so the
  retry policy is one explicit thing, identical to the Anthropic overlay.
- The base URL is overridable with `APP_LLM_OPENAI_BASE_URL` (or the SDK's own
  `OPENAI_BASE_URL`); tests redirect it to a local fake (D-013). No `respx` /
  `pytest-httpx` / `vcrpy` - the SDK runs on `httpx2`, which those libraries do
  not intercept.
- The sample uses Chat Completions (`temperature=0`) rather than the Responses
  API: its JSON is smaller to fake deterministically and its message typing
  (`ChatCompletionMessageParam`) type-checks cleanly.
- The health check does not call the API. A generated service that selects this
  overlay must supply `APP_LLM_OPENAI_API_KEY` before it boots (class-2 secret,
  D-030); the autouse test fixture supplies a dummy key so the suite runs
  offline.

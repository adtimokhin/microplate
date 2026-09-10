# Overlay: llm_anthropic

Async Anthropic client for the FastAPI service: `AsyncAnthropic` bound to the
lifespan, `tenacity` retry around a deterministic sample call, and one
`POST /llm/anthropic/summarize` route.

- Owner: AI Components Engineer
- Registry key: `llm_anthropic` (bool, default `false`)
- Overlay id: `llm_anthropic`
- Milestone: 5 (Phase 3)
- Decisions: D-002, D-004, D-013, D-019, D-030 class 2, D-032, D-037 (base
  `pydantic.mypy` plugin + lazy `create_app` import)
- Research: `research/ai-stack.md` sections 1, 3

## What it adds

| Surface | Contribution |
| --- | --- |
| Gated subtree | `{{ python_package }}/llm/anthropic/` - `client.py` (`init_client` / `get_client` / `close_client`, module-level `_client`, `max_retries=0`), `summarize.py` (`@retry`-wrapped one-sentence summary via the Messages API, fixed `system` prompt), `routes.py` (`POST /llm/anthropic/summarize`) |
| `pyproject.toml` | `anthropic==1.4.0`, `tenacity==9.1.4` |
| `config/settings.py` | `llm_anthropic_api_key` (required, no default), `llm_anthropic_model` (`claude-sonnet-5`), `llm_anthropic_timeout_s` (`30`), `llm_anthropic_base_url` (`None`) |
| `.env.example` | `APP_LLM_ANTHROPIC_API_KEY=`, `APP_LLM_ANTHROPIC_MODEL=claude-sonnet-5`, `APP_LLM_ANTHROPIC_TIMEOUT_S=30`, `# APP_LLM_ANTHROPIC_BASE_URL=` |
| `{{ python_package }}/api/router.py` | `api_router.py` fragment: imports the `/llm/anthropic` router and `include_router`s it at import time (D-032) |
| `lifespan.py` | startup hook (`init_client()`, mirror to `app.state.llm_anthropic`), shutdown hook (`close_client()`) |
| `health.py` | `check_llm_anthropic()` - client built + API key configured, no network round-trip |
| `tests/conftest.py` | `anthropic_client` (autouse). Default (`mock_transport`): patches `init_client` to build an `AsyncAnthropic` over an `httpx2.MockTransport` returning a canned Messages response, and sets `APP_LLM_ANTHROPIC_API_KEY`. `fake_server`: a stdlib `http.server` stub. |
| Boots test | `tests/overlays/test_llm_anthropic_boots.py` |

## Design notes

- Symmetric with `llm_openai` by design: same client-holder shape, same
  `tenacity` policy, same `/summarize` route contract, so a service can carry
  both providers with no surprises.
- No compose service (external SaaS).
- SDK retries disabled (`max_retries=0`); `tenacity` owns retry/backoff.
- Base URL overridable via `APP_LLM_ANTHROPIC_BASE_URL` (or the SDK's
  `ANTHROPIC_BASE_URL`); tests redirect it (D-013). No `respx` / `vcrpy` - the
  SDK runs on `httpx2`.
- `max_tokens` for the sample call is a module constant (512); the registry does
  not expose it as an env var.
- `anthropic` 1.x removed the top-level `temperature` argument to
  `messages.create` (verified against the pinned `anthropic==1.4.0`
  `inspect.signature`); the sample relies on a fixed system instruction plus the
  stubbed test transport for determinism (research/ai-stack.md 3).
- The Messages response is read with a `block.type == "text"` guard so
  `mypy --strict` narrows the content-block union cleanly.
- The health check does not call the API. A generated service that selects this
  overlay must supply `APP_LLM_ANTHROPIC_API_KEY` before it boots (class-2
  secret, D-030); the autouse test fixture supplies a dummy key so the suite
  runs offline.

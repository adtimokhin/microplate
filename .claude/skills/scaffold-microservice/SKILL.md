---
name: scaffold-microservice
description: Turns a plain-language description of a microservice (or a multi-service system) into the exact registry answer keys and a copy-paste-ready `msvc-gen new` command for this repo's Copier generator. Use when the user describes a service they want scaffolded/generated (e.g. "a service with Postgres CRUD and an OpenAI chat endpoint", "two services talking over gRPC, one with RabbitMQ") rather than asking to run the generator directly.
---

# Scaffold a microservice from a plain-language description

You turn a free-form description of a desired service (or set of services) into
a concrete, runnable `msvc-gen new` invocation for this repo's generator.

**Do not guess registry keys from memory or from this file.** The registry
evolves; the only authoritative source for key names, defaults, dependencies,
`requires`/`conflicts` rules, env vars, and invocation syntax is
`docs/component-reference.md` at the repo root. Read it fresh every time this
skill runs — do not rely on a cached mental model of it from earlier in the
conversation if significant time/edits have passed. If the file has moved,
search the repo for it before giving up.

## Procedure

1. **Read `docs/component-reference.md` in full** (or re-read it if you last
   read it more than a few turns ago / the repo may have changed since).
   Section 1 covers invocation conventions (`msvc-gen new`, `--vcs-ref`
   pinning, `--data` vs `--answers-file`, non-interactive mode). Section 2
   covers topology and `services_config`. Section 3 is the per-key reference
   (what each key ships, its default, its env vars, and its `requires`/
   `conflicts`). Section 4 has worked recipes — mirror their style.

2. **Map the user's description to registry keys.** For each capability the
   user names, find the matching key(s) in section 3 and note:
   - the key(s) and value(s) needed to turn it on,
   - any `requires` it carries (e.g. `crud_scaffold` requires one of
     `db_postgres`/`db_mongodb`/`db_redis`; `langchain` requires
     `llm_openai or llm_anthropic`; `langgraph` requires `db_postgres or
     db_redis` and its `langgraph_checkpoint` sub-option must name a store
     that's actually enabled; `embedding_pipeline` requires `db_qdrant`),
   - any `conflicts` it carries,
   - sub-options that need explicit values (e.g. `crud_entity`,
     `embedding_backend`, `langgraph_checkpoint`).

   If the user's description implies a capability but omits a dependency it
   requires (e.g. "add a chat endpoint with LangChain" but no LLM provider
   named), pick a sensible default (prefer `llm_openai` unless the user's
   wording leans Anthropic/Claude) and say so explicitly in your answer —
   don't render it invisibly.

3. **Decide topology.** Default to `topology: single`. Only choose
   `monorepo` or `multi_repo` when the user clearly describes more than one
   service (naming them, or describing distinct responsibilities that talk to
   each other). If multiple services are needed:
   - assign each service a short, sensible name for `service_names`,
   - split requested capabilities into each service's `services_config`
     submap per section 2's shared-vs-per-service key table — shared keys
     (`topology`, `service_names`, `services_config`, `transport_grpc`,
     `transport_rabbitmq`, `tests_contract`, `service_name`, `license`, `ci`,
     `iac`, `claude_hooks`/`hook_*`, etc.) go at the top level, never inside a
     submap; everything else (databases, AI overlays, `api_grpc`,
     `crud_*`, `tests_unit`/`tests_integration`, `docker`, etc.) goes inside
     the per-service submap,
   - pick `monorepo` unless the user asks for fully independent repos, in
     which case use `multi_repo`,
   - set at least one of `transport_grpc` / `transport_rabbitmq` explicitly —
     remember the gotcha in section 2: `msvc-gen`'s orchestrator does **not**
     apply the templated `transport_rabbitmq` default, so an explicit
     transport is required or validation (V-1) rejects the run,
   - if `transport_grpc` is set, at least one service must set `api_grpc`
     (V-18) — otherwise there's nothing to call over gRPC.

4. **Produce the exact command.** Follow section 1's conventions:
   - Prefer `--data KEY=VALUE` flags for a small/medium key set; use
     `--answers-file` (and show the YAML content) when the answer set is
     large, or when the user seems likely to want a reusable file.
   - Always include `--output DIR` with a sensible directory name derived
     from `service_name` (or the project name for multi-service).
   - Always include `--vcs-ref` pinned to an explicit ref. If the user names
     a version/tag, use it; otherwise use a clear placeholder like `v0.4.0`
     and tell the user to substitute the tag they actually want (or `main`
     for pre-v1 iteration), matching section 1's guidance never to rely on
     Copier's implicit "latest tag" default.
   - For multi-service topology, `services_config` is JSON — pass it either
     as the `services_config:` key of an `--answers-file` YAML doc, or as a
     single `--data 'services_config={...}'` JSON string (YAML parser
     accepts JSON), per section 2's worked example.
   - The command must be copy-paste runnable as written, not a template with
     unresolved placeholders beyond the `--vcs-ref` value itself.

5. **Flag requires/conflicts and defaults you resolved.** After the command,
   list in plain language:
   - any dependency you added automatically to satisfy a `requires` rule
     (e.g. "added `db_postgres` because `crud_scaffold` needs a datastore"),
   - any default you picked where the user didn't specify (e.g. LLM provider,
     `crud_entity` name, `embedding_backend`, `langgraph_checkpoint` store),
   - required env vars the generated service will need at runtime (e.g.
     `APP_LLM_OPENAI_API_KEY`, `APP_LLM_ANTHROPIC_API_KEY`,
     `APP_LANGSMITH_API_KEY`) — pull these from each key's env var list in
     section 3, not from memory,
   - anything the user asked for that isn't implemented (`build_status` other
     than `implemented`, or not in the registry at all) — say so rather than
     silently dropping or silently inventing it.

## Worked examples (style reference — always regenerate from the live doc)

These mirror `docs/component-reference.md` section 4 and show the expected
shape of an answer; don't paste them verbatim without re-checking the current
doc, since defaults/versions can change.

### Example: "A service with Postgres CRUD and an OpenAI-backed endpoint"

Single service, `db_postgres` + `crud_scaffold` (needs a datastore — satisfied
by `db_postgres`) + `llm_openai`:

```sh
msvc-gen new --output ./orders-api --vcs-ref v0.4.0 \
  --data service_name=orders-api \
  --data db_postgres=true \
  --data crud_scaffold=true \
  --data crud_entity=order \
  --data llm_openai=true
```

Flags to call out: `crud_entity` defaulted to `order` from context (registry
default is `item`, rename freely); `POST /llm/openai/summarize` needs
`APP_LLM_OPENAI_API_KEY` set at runtime — no key is needed to run the test
suite (LLM calls are stubbed offline by `llm_response_mode: mock_transport`,
the default).

### Example: "Two services talking over gRPC, one with RabbitMQ"

Two services, `monorepo`, `transport_grpc` (needs one service exposing
`api_grpc` — satisfied by `api`) plus `messaging_rabbitmq` on the worker:

```sh
msvc-gen new --output ./mesh-demo --vcs-ref v0.4.0 \
  --data service_name=mesh-demo \
  --data topology=monorepo \
  --data 'service_names=[api, worker]' \
  --data transport_grpc=true \
  --data transport_rabbitmq=true \
  --data 'services_config={"api": {"api_grpc": true}, "worker": {"messaging_rabbitmq": true}}'
```

Flags to call out: `transport_rabbitmq` was set explicitly rather than relying
on its templated default, since `msvc-gen`'s multi-service orchestrator does
not apply that default (see section 2's gotcha) and V-1 requires at least one
transport; `api`'s `api_grpc: true` satisfies V-18 (a `transport_grpc` mesh
needs at least one gRPC-serving member).

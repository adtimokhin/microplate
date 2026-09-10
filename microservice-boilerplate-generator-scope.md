# Project Scope: Deterministic Microservice Boilerplate Generator

## 1. Summary

A collection of prewritten boilerplate elements plus a command-line generator that assembles them into a runnable backend microservice. Running a single terminal command scaffolds a new service into a local folder (e.g. a directory on the desktop). The generated service can arrive with preconfigured components already wired in: message queues, databases, caches, vector stores, LLM clients, observability hooks, tests, Docker, and CI.

The services produced by this tool are intended to be building blocks of AI agentic systems developed at work. They are regular backend services (APIs, data stores, messaging) that an agent system calls, extends, or is composed from. The initial scope therefore includes optional components that make it possible to build AI systems on top of the template, not just plain CRUD services.

Two properties are non-negotiable:

- **The generator is deterministic.** Component selection happens through explicit, structured inputs (CLI flags, a Copier question file, or an answers file). Every input maps 1:1 to a registry entry. There is no natural-language interpretation and no LLM call anywhere in the generation path. The same inputs always produce the same output.
- **Every component is configurable from the terminal command.** Nothing is added to a generated service unless it was explicitly selected, and everything that can be added can be selected from the command line.

---

## 2. Goals

- [ ] Generate a working, runnable backend microservice into a target folder with one terminal command, with zero ambiguity about what was included.
- [ ] Every included component comes pre-wired with sane defaults (client setup, health checks, config, tests), not just installed as a dependency.
- [ ] Component selection is explicit and deterministic: the same set of flags or answers always produces the same output. No LLM in the generation path.
- [ ] All components are selectable via the terminal command (flags or answers file), including all AI-related components.
- [ ] Config choices are composable: any valid combination of options produces a working service, not just the "happy path" combos.
- [ ] The registry is the single source of truth for the flag/prompt schema (CLI and any future wrapper). No schema drift.
- [ ] Support regenerating and updating previously scaffolded services as the template evolves (via Copier `update`).
- [ ] Service topology (single deployable service vs. multiple communicating services) is a first-class, explicit option.
- [ ] The v1 scope includes enough AI-system building blocks (LLM clients, vector store, tool-shaped endpoints, tracing, optional workflow/agent overlay) that an AI agentic system can be assembled from generated services without hand-wiring these pieces every time.

## 3. Non-Goals (for v1)

- No LLM-based intent extraction or "AI skill" that turns natural language into config. Selection is explicit flags/params only.
- No visual/UI builder. CLI and structured config file input only.
- No auto-deployment to cloud (IaC output only, not `terraform apply`).
- No cross-language support in v1. Python only; revisit TS/JS after v1 is stable.
- No opinionated agent architecture baked into the base template. AI-related components are opt-in overlays; a service generated with none of them selected is a plain backend service.

---

## 4. Tech Stack Coverage

### 4.1 API layer
- [ ] FastAPI: REST endpoints, async request handling
- [ ] gRPC: protobuf service definitions, generated stubs, for internal service-to-service calls or high-throughput external calls
- [ ] Tool/function-call-shaped endpoint scaffold: a documented endpoint pattern (OpenAPI schema shaped for function-calling / MCP tool definitions) so an external agent can consume this service as a tool
- [ ] Streaming support (SSE and/or gRPC streaming) for services that return incremental results to a calling agent

### 4.2 Data layer
- [ ] PostgreSQL: SQLAlchemy (async) + Alembic migrations
- [ ] MongoDB: Motor/PyMongo client, schema-less document models
- [ ] Redis: caching, session/short-term state store, pub/sub option
- [ ] Qdrant: vector store client, collection bootstrap script, embedding pipeline stub (for retrieval/search services, e.g. a RAG backend an agent queries)
- [ ] Registry must support combining PostgreSQL, MongoDB, Redis, and/or Qdrant in one service as independently toggleable options

### 4.3 Messaging
- [ ] RabbitMQ: publisher/consumer scaffolding, dead-letter queue defaults
- [ ] Retry/backoff defaults for consumers
- [ ] Used as the default transport when service topology = multiple services

### 4.4 AI system components (opt-in overlays)

These are the elements that let generated services participate in, or form part of, an AI agentic system. Each is an independent registry option selectable from the terminal command. None are included unless selected.

- [ ] LLM provider client: configured client(s) for one or more providers (e.g. OpenAI, Anthropic), with API key config, retry, timeout, and a sample deterministic endpoint (summarization / classification)
- [ ] LangChain: client-library integration for calling LLMs, prompt templates, output parsers, and retrieval chains against the selected vector store
- [ ] LangGraph (optional workflow/agent overlay): scaffold for a stateful graph or agent loop exposed behind the service's API, with checkpointing wired to the selected store (Postgres or Redis). Off by default; when selected, it is the only place agent-style control flow appears in the generated service
- [ ] LangSmith: tracing/observability hook so calls into and out of this service are traceable by whatever agent system is calling it
- [ ] Embedding pipeline: embedding model client + ingestion job wired to Qdrant (requires Qdrant selected)
- [ ] MCP server scaffold: expose selected endpoints as MCP tools so the service can be plugged directly into an agent runtime as a tool server
- [ ] Prompt/config management: versioned prompt files and settings loader so prompts are not hardcoded in handlers

### 4.5 Testing
- [ ] Unit test scaffolding (pytest) with fixtures per selected component (DB session mock, vector store mock, message broker mock, LLM client mock)
- [ ] Integration test scaffolding (pytest + testcontainers) that spins up real Postgres/Mongo/Redis/RabbitMQ/Qdrant containers as needed based on config
- [ ] Contract tests for gRPC interfaces when topology = multiple services
- [ ] Recorded/stubbed LLM responses for deterministic tests of AI overlays

### 4.6 Cross-cutting
- [ ] Structured logging + correlation IDs
- [ ] OpenTelemetry tracing
- [ ] Health/readiness endpoints
- [ ] Dockerfile + docker-compose (with only the selected dependencies stubbed)
- [ ] CI pipeline template (lint, unit tests, integration tests, build)

---

## 5. Configuration & Registry Design

- [ ] Define `registry.yaml` schema covering all sections in §4, structured as option → dependencies, files/overlays, env vars
- [ ] Define validation rules / invalid combinations, e.g.:
  - topology = multiple services requires at least one transport (gRPC and/or RabbitMQ)
  - tool/function-call endpoint scaffold and MCP server scaffold require FastAPI (or gRPC)
  - embedding pipeline requires Qdrant
  - LangGraph overlay requires a checkpoint store (Postgres or Redis)
  - LangChain retrieval chain requires a vector store
- [ ] `copier.yml` question file generated/derived from `registry.yaml`, so every prompt shown to the user corresponds exactly to a registry key. No prompt exists that doesn't map to a deterministic file/dependency set
- [ ] Support two equivalent input modes, both deterministic:
  1. **Interactive prompts** (Copier's own Q&A, run in a terminal)
  2. **Non-interactive params** (a YAML/JSON answers file or CLI flags, e.g. `--database=postgres --messaging=rabbitmq --vector-store=qdrant --llm=anthropic --tracing=langsmith --topology=multi --output=~/Desktop/my-service`) for scripted/CI-driven generation
- [ ] `--output` (target folder) is a required, explicit parameter with a sensible default

## 6. Deterministic Component Selection

- [ ] No NL parsing, no LLM call, no inference step in the selection path
- [ ] Every component is chosen by an explicit, named flag/prompt defined in `registry.yaml`. The mapping from "answer" to "files pulled in" is a static lookup, fully reproducible and auditable
- [ ] If a wrapper (script, internal tool, CI job) wants to pre-fill answers, it must supply a complete, valid answers file matching the registry schema. The generator does not guess or infer values
- [ ] Any future convenience layer (a form, a config wizard) must still bottom out in the same explicit answers file, keeping generation itself deterministic and independent of how the answers were produced

## 7. Storage & Distribution

- [ ] Single private GitHub repo for template + registry + overlays + hooks
- [ ] Semantic version tags for releases; `main` used during pre-v1 iteration
- [ ] `.copier-answers.yml` retained in generated projects to support `copier update` later
- [ ] Decide access model (SSH key vs token) for private repo pulls from CI runners
- [ ] Generator installable as a single CLI command (pipx or similar) so scaffolding is one terminal invocation

---

## 8. Milestones

1. **Registry v0**: schema for API layer, data layer, messaging, topology, and AI component keys (keys defined even if overlays are not yet built)
2. **Base template**: minimal FastAPI service, no optional overlays, boots and passes a smoke test, generated into a target folder from one command
3. **Overlay set 1**: PostgreSQL, MongoDB, Redis, RabbitMQ
4. **Overlay set 2**: Qdrant, gRPC, tool/function-call endpoint scaffold
5. **Overlay set 3 (AI components)**: LLM provider client, LangChain, LangSmith tracing, embedding pipeline, MCP server scaffold
6. **Overlay set 4**: multi-service topology (service split, inter-service gRPC/RabbitMQ wiring, contract tests)
7. **Overlay set 5**: LangGraph workflow/agent overlay with checkpointing
8. **Testing scaffolds**: unit + integration wired per selected combo, including LLM stubs
9. **Non-interactive mode**: answers-file / flag-driven generation for CI and scripted use
10. **Update path**: verify `copier update` works cleanly against a generated service after a template change

## 9. Open Questions

- Confirm Qdrant as the v1 vector store, or a different/additional one.
- Which LLM providers to support in v1 (OpenAI and Anthropic as a minimum?).
- When topology = multiple services, is the output a monorepo with multiple service folders, or does the generator run once per service producing separate repos?
- Should the tool/function-call endpoint scaffold target MCP specifically, plain OpenAPI, or both?
- How much of the LangGraph overlay belongs in v1 vs. deferred until the deterministic core is stable?
- Minimum Python version / async framework assumptions; affects every overlay.
- Any target cloud (AWS/GCP/Azure) to bias default IaC/deploy overlays, or stay cloud-agnostic for v1?

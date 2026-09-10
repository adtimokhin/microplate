# Overlay Contract

Version 0. Owner: Registry & Copier Architect. Status: authoritative for all overlay work.

Every overlay engineer must follow this document. If something here blocks you, raise it with the Lead; do not deviate silently. Determinism and clean `copier update` are the two properties every rule below protects.

Reference: `research/copier-architect-notes.md` for the Copier facts this is built on. Copier version floor: `9.18.2`.

---

## 1. Definitions

- **Base template**: the minimal FastAPI service produced when no optional key is selected. Always present. Not an overlay.
- **Overlay**: a self-contained unit of functionality selected by one or more registry keys. It contributes files, dependencies, env vars, compose services, health checks, fixtures, tests, and CI steps. It is off unless its key is selected.
- **Registry key**: a single answer in `registry.yaml`. One key gates one overlay. Every v1 overlay is gated by a boolean key whose name is the overlay id; `in` tests against a list answer are supported by the mechanism but unused in v1 (D-020).
- **Fragment**: a Jinja partial that an overlay contributes to a shared file (pyproject, compose, settings, health, CI, env, conftest). Fragments are assembled during Copier's render pass, not by a post hook.
- **Shared file**: a file in the generated project that more than one overlay plus the base all write into.

---

## 2. Template repository layout

Single Copier template, single `_subdirectory`, single answers file. Multi-service topology is handled inside this one template, not by multiple templates.

```
repo root/
  copier.yml                     # GENERATED from registry.yaml by scripts/gen_copier_yml.py. Never hand-edited.
  registry.yaml                  # single source of truth
  scripts/
    gen_copier_yml.py            # derivation script (interface defined in registry-schema.md; not built yet)
    validate_registry.py         # lints registry.yaml against the schema
  includes/                      # shared Jinja macros and partials, OUTSIDE _subdirectory (never rendered)
    slugify.jinja
    answers_helpers.jinja        # overlay_order list, selected_overlays(), selected_overlay_ids, overlay_enabled(id)
    fragment_loops.jinja         # include_slot('<slot>'): walk selected_overlay_ids in overlay_order, include each _fragments/<id>/<slot>.jinja
  template/                      # _subdirectory: the only thing that gets rendered
    {{ _copier_conf.answers_file }}.jinja
    ... base files ...
    _fragments/                  # per-overlay fragment partials, EXCLUDED from output
      <overlay-id>/
        deps.toml.jinja
        dev-deps.toml.jinja
        compose.yml.jinja
        compose.app-deps.yml.jinja
        settings.py.jinja
        health.py.jinja
        lifespan.py.jinja
        env.example.jinja
        conftest.py.jinja
        ci-steps.yml.jinja
    {% if <gate> %}{{ _pkg }}{% endif %}/    # one gated subtree PER overlay, see 3.2
      ...overlay source files at final paths...
  overlays/                      # overlay metadata and docs, NOT rendered (outside _subdirectory)
    <overlay-id>/
      OVERLAY.md                 # human description, owner, decisions
```

Key points:

- `_subdirectory: template`. Everything the user gets is under `template/`.
- `_exclude` carries the Copier defaults plus `/_fragments` and `/_fragments/**`. Exclude patterns match destination-relative paths (after `_subdirectory` strips `template/`), and they follow gitignore semantics: an unanchored bare name matches a directory of that name at ANY depth. The fragment directory is a root-level `_fragments/` in the destination, so the pattern is ANCHORED with a leading slash (`/_fragments`). A bare `_fragments` would also match, e.g., a rendered `tests/_fragments/`.
- `includes/` and `overlays/` sit outside `_subdirectory`, so they never render and MUST NOT be listed in `_exclude`. A bare `overlays` entry silently drops the rendered `tests/overlays/` subtree (every overlay's proves-it-boots test lives there, §7) - this was a real bug in the first generated `copier.yml`, caught 2026-09-08. Copier's Jinja loader is rooted at the template source root (the repo root), so `{% from 'includes/...' import ... with context %}` still resolves from `copier.yml` and from files inside `template/`.
- Fragment partials live at `template/_fragments/<id>/<slot>.jinja`. They are pulled in by `include_slot('<slot>')` from `includes/fragment_loops.jinja`, which owns the exact include path. `_exclude` (`/_fragments`, destination-relative) and the Jinja `include` (loader-root-relative) use different strings by design.
- General rule for `gen_copier_yml.py`: never emit an unanchored bare directory name in `_exclude`. Anchor anything that must stay excluded (`/_fragments`); a glob that already contains a slash (`_fragments/**`) is fine.
- `copier.yml` is generated. The generator reads `registry.yaml` and emits questions, `_exclude`, `_skip_if_exists`, `_tasks`, and computed values. Nobody edits `copier.yml` by hand. CI fails if `copier.yml` is out of sync with `registry.yaml`.

---

## 3. Overlay inclusion mechanism

**Chosen mechanism: Jinja-conditional path segments, one gated subtree per overlay, merged by Copier into the shared service source tree. No post-generation file deletion. No `_exclude`-driven selection.**

### 3.1 Why this and not the alternatives

| Approach | Rejected because |
| --- | --- |
| Post-hook deletes unselected files | Output depends on hook execution, not just answers. Harder to audit. A crashed hook leaves a half-built tree. Breaks "static lookup" requirement. |
| `_exclude` computed from answers | `_exclude` in `copier.yml` replaces defaults, so every default must be re-listed and kept in sync. A large templated exclude block is the least readable place to encode selection. Errors fail open (file silently ships). |
| `_subdirectory` switch per profile | Resolves to one directory. Cannot compose N independent overlays. |
| `{% yield %}` loops for everything | Great for N-of-a-kind (service folders in monorepo topology). Overkill and less readable for one-of toggles. Used only where topology needs it. |
| Conditional path segments (chosen) | Selection is a pure function of answers, evaluated in Copier's single render pass. Unselected subtree is never written. Each overlay is one isolated directory in the template repo, so engineers work without stepping on each other. Rendered output paths are stable across versions, which is what `copier update` needs. |

### 3.2 How an overlay subtree is gated

Each overlay owns exactly one top-level directory under `template/` whose name is a gate expression that renders to the service package directory name when the overlay is on, and to the empty string when it is off:

```
template/{% if db_postgres %}{{ python_package }}{% endif %}/
    db/
      postgres/
        __init__.py.jinja
        engine.py.jinja
        session.py.jinja
      migrations/
        env.py.jinja
        ...
```

- Gate on: renders to `myservice/db/postgres/engine.py` and merges with the base `myservice/` tree and every other selected overlay's `myservice/` subtree.
- Gate off: directory name renders empty, the whole subtree is skipped. Nothing to clean up.
- Two overlays both rendering their root to `{{ python_package }}` is fine and expected. Copier merges same-named destination directories.

Rules:

1. One overlay = one gated top-level directory under `template/`. Do not scatter an overlay's files across multiple gated roots.
2. The gate expression is a single boolean answer or a `in` test against a multiselect answer. No compound business logic in the path. If you need compound logic, add a computed key in `registry.yaml` (`when: false`) and gate on that.
3. Inside the gated subtree, lay files out at their FINAL destination-relative paths. What you see is where it lands.
4. Files that need per-answer content still use `.jinja` and branch internally. The gate is only for presence.
5. Never gate a file that the base also ships. If the base owns `myservice/main.py`, an overlay must not also ship `myservice/main.py`. Overlays extend shared files only through fragments (section 4).
6. If an overlay contributes files outside the service package (for example `proto/`, `.github/`), it gets a second gated top-level directory following the same rule, for example `template/{% if api_grpc %}proto{% endif %}/`. Keep the count minimal.
7. Directory names never carry the `.jinja` suffix. File names carry `.jinja` outside the condition.

### 3.3 Multi-service topology (D-036, supersedes the single-run mechanism)

`topology` is `single`, `monorepo`, or `multi_repo` (D-005). Multi-service output is produced by **orchestration in the generator**, not by one large Copier render. There is no `{% yield %}` loop over `service_names` and no gate expression anywhere reads `services_config`. The base tree and every overlay subtree are byte-for-byte the same files used for `single`; `topology != 'single'` changes nothing under `template/`.

- **`single`**: one Copier render. The service package renders at `template/{{ python_package }}/` (base) plus the selected overlay subtrees, exactly as sections 3.2 and 4 describe. `cli.py` runs this directly.

- **`monorepo`**: `msvc_gen/topology.py` (invoked by `cli.py` only when `topology != 'single'`) runs, in frozen `service_names` list order:
  1. **One `single`-style Copier render per service**, driven by that service's *effective answer set* (registry defaults, then the shared top-level keys, then `services_config[<svc>]`, then the derived per-service identity `service_name` / `service_slug` / `python_package`; full merge order in `docs/services-config-schema.md` section 3). Each renders into `services/<svc>/` and keeps its **own** `.copier-answers.yml` (Copier's native one-answers-file-per-run model). Because the effective answer set is a complete, valid `single` answer set, each per-service render is literally a `single` generation - same `copier.yml`, same `_subdirectory`, same gating.
  2. **One root-layer render** from `msvc_gen/root_templates/` (a small Copier template distinct from `template/`, owned by TopologyEngineer): root `docker-compose.yml` (one app block per service, wired by service name over the selected transport, plus each service's backing services), root `README.md`, the shared `proto/` tree + `buf.yaml`, and the root CI workflow (matrix over the service folders + the `tests_contract` job). It also writes a **root manifest `.copier-answers.yml`** carrying `topology`, `service_names`, `services_config`, and the shared keys (services-config-schema section 2.1).

- **`multi_repo`**: identical to `monorepo` except each per-service render targets a separate output directory (its own repo) instead of `services/<svc>/`, and the root-layer artifacts that make sense per repo (README, `proto/`, `buf.yaml`) are emitted into every repo. The shared `proto/` tree is generated once from the top-level `service_names` + `transport_grpc` and is byte-identical across the repos in one generation. Same code path as `monorepo`, different destination.

**`.copier-answers.yml` for multi-service**: one per `services/<svc>/` (or per repo) from that service's own render, **plus** the root manifest. This supersedes D-017's "one root answers file, no per-service answers files". D-017's `services_config` intent (per-service overlay selection, the shared-vs-per-service key split) is unchanged and is specified in `docs/services-config-schema.md`.

**`copier update` for multi-service**: `msvc_gen/topology.py` runs `copier update` inside each `services/<svc>/` (or each repo) against its own `.copier-answers.yml`, then re-renders the root layer from the root manifest. Per-service update granularity falls out for free (removes the Phase 1 BACKLOG item).

**Determinism**: N deterministic `single` renders in frozen `service_names` order, then one deterministic root render. The effective submap is a pure dict merge over a fixed key list. No iteration over unordered answer data reaches an output path. Rendering the same root answers file twice produces byte-identical trees for every service folder and the root layer.

Transport wiring (`transport_grpc`, `transport_rabbitmq`, per-peer client stubs) and `tests_contract` are an overlay / root-template set owned by TopologyEngineer. `transport_grpc` / `transport_rabbitmq` are **shared** top-level keys (every service in the mesh gets the transport wiring uniformly); a service exposes its own gRPC server only if its submap sets `api_grpc`. The gating and fragment rules in sections 3.2 and 4 apply to the per-service overlays unchanged, because each per-service render is a plain `single` render.

---

## 4. Shared-file contribution mechanism

**Chosen mechanism: Jinja-assembled shared files. Each shared file is a base-owned `.jinja` template that iterates the canonical ordered overlay list and `{% include %}`s each selected overlay's fragment for that file. Assembly happens in Copier's render pass. No marker-splicing hook.**

### 4.1 Why this and not marker blocks or a concat hook

- Marker blocks edited by a hook: output depends on hook order and on the user not touching the block. Non-deterministic under partial failure. `copier update` fights the hook.
- Concat-by-hook of generated fragment files: adds a task (arbitrary code) and a sorting contract that lives in Python instead of in the template. One more place for drift.
- Jinja assembly: the shared file is a normal rendered artifact. Its bytes are a pure function of the answers, given a fixed iteration order. `copier update` treats it like any other file. The only discipline required is that overlays never write the same shared file directly.

### 4.2 The canonical ordered list

`registry.yaml` defines `overlay_order`: an explicit, fixed list of every overlay id. `includes/answers_helpers.jinja` hardcodes the same list (append-only, kept in sync) and exposes:

- `selected_overlays()`: returns the ids from `overlay_order` whose boolean gate answer is true, in `overlay_order` sequence, as a JSON array string. Built from a `_gates` dict of `<overlay-id> | default(false)` (the D-020 one-key-one-overlay invariant keeps this a flat lookup).
- `overlay_enabled(id)`: boolean test for one overlay.

The helper is also imported once by `copier.yml` to compute the `selected_overlays` answer (a `when: false` computed key, `type: json`) so the resolved list is recorded in `.copier-answers.yml` for audit and `copier update`.

Shared-file skeletons assemble fragments through one indirection, `includes/fragment_loops.jinja`:

```jinja
{% from 'includes/fragment_loops.jinja' import include_slot with context %}
{{ include_slot('deps') }}
```

`include_slot('<slot>')` walks `selected_overlay_ids` (from `includes/answers_helpers.jinja`, `with context`) in `overlay_order` sequence and `{% include %}`s each selected overlay's `_fragments/<id>/<slot>.jinja`, skipping missing ones. Importing from `includes/` inside a template file works (`with context` is required because the helpers read answer vars). This keeps the loop body in one place instead of repeated across every skeleton. Iterating the `selected_overlays` answer variable directly produces identical bytes and is also allowed; `include_slot` is the default because it is less boilerplate. Never iterate a `set`, a dict, or a raw answer list in any other order than `overlay_order`.

Adding an overlay means appending its id to BOTH `registry.yaml` `overlay_order` AND the list in `includes/answers_helpers.jinja`. Position is chosen once and never changed (reordering changes rendered bytes and breaks `copier update`). New overlays append unless there is a hard reason to insert.

### 4.3 The shared files and how each is assembled

Every shared file below is base-owned. The base ships the skeleton and the include loop. Overlays ship only fragments under `template/_fragments/<overlay-id>/`.

| Shared file (generated path) | Base skeleton provides | Fragment file | Fragment must contain |
| --- | --- | --- | --- |
| `pyproject.toml` | `[project]`, base deps, hatchling build backend config, tool config, `include_slot('deps')` inside `[project].dependencies` and `include_slot('dev-deps')` inside `[dependency-groups]` | `_fragments/<id>/deps.toml.jinja`, `_fragments/<id>/dev-deps.toml.jinja` | Zero or more `"pkg==X.Y.Z",` lines, each on its own line, trailing comma, exact pins. No section headers. Extras use the array form `"qdrant-client[fastembed]==1.19.0",`. Dev-only deps go in the dev-deps fragment. |
| `docker-compose.yml` | `services:` with the `app` service (its `depends_on:` block runs a loop including `compose.app-deps.yml.jinja`), then a loop including `compose.yml.jinja` for sibling services | `_fragments/<id>/compose.yml.jinja` | One or more compose service blocks, 2-space indented to sit under `services:`. Named `<overlay-id>` or `<overlay-id>-<role>`. Pinned image tags. |
| `docker-compose.yml` `app.depends_on` | `depends_on:` key on the `app` service with the include loop | `_fragments/<id>/compose.app-deps.yml.jinja` | Zero or more `<svc>: {condition: service_healthy}` lines, indented to sit under `app.depends_on`. Only overlays that add a service the app talks to at startup contribute here. Renders nothing otherwise. Resolves the Phase 1 BACKLOG item on `app` `depends_on`. |
| `{{ python_package }}/config/settings.py` | `Settings` base class (pydantic-settings), then loop including `settings.py.jinja` inside the class body | `_fragments/<id>/settings.py.jinja` | Field declarations only, 4-space indented, typed, with defaults or `...` for required. Prefixed env names (section 5). No imports at class scope; put shared imports in the base skeleton or request them via `settings_imports.jinja` (see 4.4). |
| `{{ python_package }}/health.py` | `readiness()` aggregator that awaits a list of check callables, loop including `health.py.jinja` | `_fragments/<id>/health.py.jinja` | One async check function `async def check_<id>(...) -> HealthResult:` and one line appending it to the registry list. Must not raise; return a structured failure. |
| `{{ python_package }}/api/router.py` | base `api_router` `APIRouter` + the base `root` router, then a module-level `_include_overlay_routers()` that runs `include_slot('api_router.py')` and is CALLED at import time (before `create_app()` returns; no lifespan mount, no `app.openapi_schema` reset). The slot output is wrapped `\| trim('\n')` and the base skeleton owns the surrounding blank lines (D-032) | `_fragments/<id>/api_router.py.jinja` | A 4-space-indented block: local import(s) of the overlay's router plus one or more `api_router.include_router(<router>)` calls. NO leading newline. MUST end with exactly `\n\n` (block content, then one blank line) - this is what separates successive fragments; ending with a single `\n` or none runs the next fragment onto the same line (MessagingEngineer hit this in D-032). Applies to every contributor to this slot (`streaming_sse`, `tool_scaffold`, and `mcp_server` in Phase 3). Keep imports local (inside the assembled function body) to avoid E402. |
| `{{ python_package }}/.env.example` (rendered to `.env.example`) | base vars, then loop including `env.example.jinja` | `_fragments/<id>/env.example.jinja` | `KEY=value` lines, one per env var the overlay reads, with a safe non-secret placeholder. Order matches `settings.py` fields. |
| `tests/conftest.py` | base fixtures, then loop including `conftest.py.jinja` | `_fragments/<id>/conftest.py.jinja` | Pytest fixtures for this overlay (mock client, optional testcontainer). Fixture names namespaced `<id>_<thing>` (for example `postgres_session`, `redis_client`). No collection-time side effects. |
| `.github/workflows/ci.yml` | lint job, test job, build job, loop including `ci-steps.yml.jinja` into the test job `steps:` and `services:` | `_fragments/<id>/ci-steps.yml.jinja` | Optional `services:` entries and optional extra `steps:`. Indented to match the anchor. **Integration-test** additions (a `services:` container plus the steps that hit it) must be a no-op when `tests_integration` is false. **Carve-out:** §4.4b drift-guard steps that verify committed generated artifacts (e.g. `api_grpc`'s `regen_proto.py` then `git diff --exit-code`) are always-on and are EXEMPT from the `tests_integration` no-op rule — only integration-test steps are gated. |

### 4.4 Fragment authoring rules

1. A fragment is a partial. It has no front matter, no file-level structure, only the snippet described above. It renders in the context of the shared file, so all answers are in scope.
2. A fragment must render to nothing when its own sub-options are off. Wrap internal optional parts in `{% if %}`.
3. Whitespace is load-bearing. Use `{%- ... -%}` control and match the indentation column stated in the table. The base skeleton controls the surrounding newlines.
4. A fragment must be idempotent and self-contained: including it zero times or one time are the only cases. It is never included twice.
5. If an overlay needs an import in a shared file, it adds a line to `_fragments/<id>/<file>_imports.jinja` and the base skeleton has a dedicated import loop at the top of that file. Imports are sorted by the base loop via `overlay_order`, not by the fragment.
6. Fragments must not read files, call `_tasks`, or depend on generation order beyond `overlay_order`.
7. Exact version pins only. No ranges, no `^`, no `~`, no unpinned names. Pins come from the overlay's registry entry, not typed into the fragment by hand where avoidable (the derivation script may inline them later; for now copy the registry value exactly).

### 4.4a Packaging and lockfile (D-010)

Generated projects use `pyproject.toml` + the hatchling build backend + `uv` with a committed `uv.lock`. CI runs `uv sync --locked`.

- Overlay runtime deps go straight into `[project].dependencies` via the `deps.toml.jinja` fragment. They are not optional-extras: an overlay is either selected (its deps are hard deps of the generated service) or absent. `[project.optional-dependencies]` is reserved for genuinely optional runtime features a user toggles after generation, which v1 has none of.
- Overlay dev/test deps (test fixtures needing `testcontainers`, a fake-server lib, etc.) go into a PEP 735 `[dependency-groups]` group via a `dev-deps.toml.jinja` fragment, assembled the same way, so they never leak into `pip install` / `[project].dependencies` (D-010 detail).
- `uv.lock` cannot be shipped pre-resolved for every overlay combination. The base template ships a single post-generation task, `_tasks: [["uv", "lock"]]`, gated `when: "{{ _copier_operation == 'copy' }}"`, plus a documented `uv lock` step in the generated README and CI. This lock step is the one sanctioned non-deterministic action in the pipeline: it reads the live index at generation time. It runs after rendering, never changes rendered files, and its output (`uv.lock`) is committed by the user. Overlays must not add their own lock or install tasks.
- On `copier update`, `uv.lock` is regenerated by the user (`uv lock`) after the merge, not by a task, so update conflicts on the lockfile are avoided.

### 4.4b Committed generated files (D-009)

An overlay may ship generated source that is committed into the output rather than produced at build time (the gRPC overlay commits `*_pb2.py`, `*_pb2_grpc.py`, `*_pb2.pyi`).

- The generated files live in the overlay's gated subtree as normal `.jinja` (or plain) files at their final paths.
- The overlay also ships a pinned regeneration script (for example `scripts/gen_proto.sh` pinning the `grpcio-tools` / `protoc` version) and a CI step in its `ci-steps.yml.jinja` that runs the script and then `git diff --exit-code` to prove the committed output is current.
- The regen script's tool versions come from the overlay's `python_deps` in the registry, so there is one source of truth.

### 4.5 Lifespan and DI wiring

Client startup and shutdown is a shared concern (the FastAPI lifespan). Handle it exactly like `health.py`:

- Base ships `{{ python_package }}/lifespan.py` with an ordered list of async startup callables and async shutdown callables.
- Each overlay ships `_fragments/<id>/lifespan.py.jinja` contributing one startup and one shutdown function plus the lines registering them.
- Startup order is `overlay_order`. Shutdown order is reverse `overlay_order`. The base loop enforces both. Overlays never reorder.

---

## 5. Naming conventions

### 5.1 Registry keys

- Snake case, lowercase, ASCII. `db_postgres`, `messaging_rabbitmq`, `llm_openai`, `langgraph_checkpoint`.
- Group prefix where a group exists: `db_`, `api_`, `llm_`, `tests_`, `topology`/`transport` for topology.
- Boolean keys are named for the thing, not the question: `db_redis`, not `use_redis` or `redis_enabled`.
- A key that selects among alternatives is a `str` with `choices`, named for the axis: `ci`, `topology`, `langgraph_checkpoint`.
- An independent on/off overlay is a boolean key, never a `multiselect` member (D-020): `streaming_sse`, `streaming_grpc`, `transport_grpc`, `transport_rabbitmq`.
- `multiselect` / open list types are reserved for a genuinely open-ended set of values. The only v1 case is `service_names`, a `yaml`-typed free list.
- Computed keys (`when: false`) are prefixed with a single underscore only if they are pure internals not meant for answers files. Selection-relevant computed keys have normal names so they are recorded and auditable.

### 5.2 Answer values

- Enum values are lowercase snake case: `github_actions`, `multi_repo`, `postgres`, `grpc_streaming`.
- Never use `true`/`false` strings as enum values. Booleans are `bool` type.
- Value spellings are frozen once shipped. Renaming a value breaks `copier update`. Add a new value and a migration instead.

### 5.3 Overlay ids

- The overlay id equals its primary gate key when it has one (`db_postgres`).
- Every v1 overlay id equals a boolean gate key. `streaming_sse`, `streaming_grpc`, `transport_grpc`, `transport_rabbitmq` follow the `<axis>_<value>` shape but are still plain booleans (D-020).
- Fragment directory name, `overlay_order` entry, `overlays/<id>/OVERLAY.md`, and health check suffix all use this same id.

### 5.4 Env vars

- Upper snake case, service-namespaced with a fixed prefix from the base (`APP_`), then overlay group, then field: `APP_DB_POSTGRES_DSN`, `APP_REDIS_URL`, `APP_LLM_OPENAI_API_KEY`, `APP_LANGSMITH_API_KEY`.
- Three classes of env var (D-030):
  1. **Credential-bearing connection string for a bundled compose service** (`APP_DB_POSTGRES_DSN`, `APP_DB_MONGODB_URI`, `APP_REDIS_URL`, `APP_QDRANT_URL`, `APP_RABBITMQ_URL`): `required: false`, `secret: true` (redaction still applies), `default:` = the compose value using the SERVICE NAME as host (`postgresql+asyncpg://app:app@postgres:5432/app`, `mongodb://mongodb:27017`, `redis://redis:6379/0`, `http://qdrant:6333`, `amqp://guest:guest@rabbitmq:5672/`). Non-secret companion settings like `APP_DB_MONGODB_DATABASE` default to `{{ service_slug }}` (per-service, precedent `APP_LANGSMITH_PROJECT`). Rationale: goal #1 (generate a working, runnable service) and working agreement #5 (pre-wired, sane defaults, boots) - `docker compose up` must work with no `.env` step. Host is the compose service name, NOT `localhost`; the app container reaches the backing container by service name.
  2. **True external-credential secret with no meaningful local default** (`APP_LLM_OPENAI_API_KEY`, `APP_LLM_ANTHROPIC_API_KEY`, `APP_LANGSMITH_API_KEY`): no default (`...` in `settings.py`), `secret: true`, and `required: true` when the overlay cannot function without it.
  3. **Optional-auth key** (`APP_QDRANT_API_KEY`): no default, `secret: true`, `required: false` - set only if the backing service enforces auth. Unchanged.
- The env var name, the `settings.py` field default, and the `.env.example` line are declared together in the overlay's `registry.yaml` `env_vars` block and must match byte-for-byte. For class-1 vars `.env.example` shows the compose default value, not a bare placeholder. (`validate` will enforce the match once wired.)

### 5.5 Generated files

- Python modules snake case. Compose services kebab or snake matching the overlay id. Test files `test_<area>.py`.

---

## 6. What an overlay declares in `registry.yaml`

Every overlay contributes one option entry (or a small group of related entries). The entry carries all of the following. See `docs/registry-schema.md` for the field-by-field schema and `registry.yaml` for live examples.

- `key`, `type`, `choices`, `default`, `prompt`, `group`.
- `gate`: the Jinja expression that turns the overlay on (for booleans this is just the key).
- `requires`: list of registry conditions that must hold (for example `db_qdrant == true`, or `llm_openai or llm_anthropic`). Encoded both as prose in registry-schema.md and as machine-checkable `requires` structure here.
- `conflicts`: list of registry conditions that must NOT hold.
- `overlay_id` and the template paths it owns (`template_paths`).
- `python_deps`: map of `package` to exact pinned `version`, verified against upstream with an `as_of` date.
- `env_vars`: list of `{ name, type, required, default, secret, description }`.
- `compose_services`: list of `{ name, image, ports, healthcheck }` (image tags pinned).
- `fixtures`: list of pytest fixture names the overlay registers, with `kind` (`mock` or `container`).
- `health_checks`: list of check function ids the overlay adds to readiness.
- `ci_steps`: description of steps/services the CI fragment adds, and the answer that gates them.
- `boots_test`: path to the overlay's proves-it-boots test (section 7).
- `build_status`: `planned` or `implemented`.
- `milestone`: the scope milestone that builds it.

Dependencies and conflicts are declared in the registry. An overlay may assume another overlay's files exist only if it declares that overlay in `requires`. Nothing else.

---

## 7. Proves-it-boots test contract

Every overlay ships at least one test that proves the overlay is wired, not just installed. This is a hard gate for marking `build_status: implemented`.

Requirements:

1. Location: `tests/overlays/test_<overlay_id>_boots.py`, shipped inside the overlay's gated subtree so it only exists when the overlay is selected.
2. It must exercise the real wiring path, not a hand-built object:
   - Import the generated app and enter its lifespan (`async with lifespan(app)` or the FastAPI test client as context manager).
   - Assert the overlay's client/handle is present on app state and is the expected type.
   - Call the overlay's health check function and assert it returns a healthy result against a real backing service.
3. Backing service:
   - If `tests_integration` is selected, use the testcontainer fixture from `conftest.py` and hit a real container.
   - If not, the test uses the overlay's mock fixture and asserts the wiring and the health check code path, with the external call stubbed. The test still runs and still passes in the mock configuration.
4. AI overlays use recorded or stubbed responses only. No network LLM calls in any test. Determinism is mandatory (scope §4.5).
5. The test must pass in at least these configurations: overlay alone on the base, and overlay plus every overlay it declares in `requires`.
6. Runtime budget: the mock-mode boots test runs in under 2 seconds.
7. No skips, no xfail. If it cannot run in a configuration, that configuration is invalid and belongs in the registry `conflicts`.

The base template ships its own smoke test (`tests/test_app_boots.py`): app imports, `/health/live` returns 200, `/health/ready` returns 200 with no overlays selected.

---

## 8. `.copier-answers.yml` retention and update stability

### 8.1 Retention

- The template ships `template/{{ _copier_conf.answers_file }}.jinja` containing exactly:
  ```
  # Changes here will be overwritten by Copier; NEVER EDIT MANUALLY
  {{ _copier_answers|to_nice_yaml -}}
  ```
- Default answers file name: `.copier-answers.yml`.
- **`single`**: one `.copier-answers.yml` at the project root, from the one Copier render.
- **`monorepo` (D-036, supersedes D-017)**: each `services/<svc>/` keeps its **own** `.copier-answers.yml`, written by that service's own `single`-style render (Copier's native one-file-per-run model). In addition, the generator writes a **root manifest `.copier-answers.yml`** at the monorepo root carrying `topology`, `service_names`, `services_config`, and the shared keys (see `docs/services-config-schema.md` section 2.1). `copier update` runs per `services/<svc>/` against its own answers file, then the root layer is re-rendered from the root manifest. There is no single whole-monorepo Copier render to update.
- **`multi_repo`**: each generated repo is its own `single`-style render and keeps its own `.copier-answers.yml`. The root manifest is emitted into each repo as well (the shared-key + `services_config` record is identical across the set).
- The generated project MUST commit every one of these files (each `services/<svc>/.copier-answers.yml` and the root manifest). The generated README and the base `.gitignore` are set up so they are tracked. CI in the generated project fails if any is missing.

### 8.2 What must stay stable across template versions

`copier update` keys customizations by rendered output path and replays a diff. To keep updates clean, across versions we do NOT:

- Rename a registry key. Add a new key, keep the old as a computed alias (`when: false`, `default` derived from the new key) for one minor cycle, then drop it with a `_migrations` entry.
- Rename or re-spell an answer value.
- Change a rendered output path for a file that is likely user-edited (anything under the service package, tests, compose, pyproject, CI). If a path must move, ship a `_migrations` `git mv` for the exact old-to-new mapping, gated on version.
- Reorder `overlay_order`. Append only.
- Change the answers file name.
- Change fragment indentation contracts in a way that reflows an unchanged selection's output. Byte-stability for a fixed answers set is the test.
- Remove a `default` such that an old answers file no longer validates. New keys get a `default` that reproduces prior behavior (usually `false` or the empty list).

We MAY freely:

- Add new keys with safe defaults.
- Add new overlays (append to `overlay_order`).
- Add fields to a fragment as long as an unchanged selection renders unchanged bytes.
- Bump pinned versions (this is a normal update the user pulls).

### 8.3 Migrations

Version-crossing structural changes go in `_migrations` in `registry.yaml`, emitted into `copier.yml` by the derivation script. Each migration states `version`, `when` stage, and the exact command. Migrations are the only sanctioned way to move or delete user-facing files across versions.

---

## 9. Determinism checklist (every overlay PR)

- [ ] Selection is gated only by answers, via a path segment or the `selected_overlays` answer. No hook deletes files.
- [ ] Shared files are touched only through fragments in `overlay_order` position.
- [ ] No iteration over unordered collections in any template.
- [ ] All package and image versions are exact pins with an `as_of` date in the registry.
- [ ] `requires` and `conflicts` fully declared in the registry; no undeclared assumption about another overlay.
- [ ] Proves-it-boots test present, runs in mock and (if applicable) container mode, no skips.
- [ ] Rendering the same answers file twice produces byte-identical trees (CI check).
- [ ] No rename of an existing key, value, or rendered path without a `_migrations` entry.
- [ ] `copier.yml` regenerated from `registry.yaml`; sync check passes.
- [ ] Plain-language docs, no em dashes.

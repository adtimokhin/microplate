# Combinatorial verification harness

The integration gate for every milestone. It turns `registry.yaml` into a set of
answers files, renders each with the generator, and runs the generated project's
own tests. Same registry plus same mode always produces the same result.

Status: Phase 1 skeleton. Wired end to end against the zero-overlay base template.
Every overlay slot is scaffolded with a TODO tied to the milestone that fills it.

## Files

| File | Role |
| --- | --- |
| `registry_model.py` | Reads `registry.yaml`. Builds the axis list, evaluates `when` / `requires` / `conflicts` / `validation_rules`, canonicalizes an assignment, validates it, lists selected overlays. No Copier, no network. |
| `combinations.py` | Generates the set of valid answers files. `full` and `pairwise` modes. Writes `<hash>.yml` files plus `manifest.json`. |
| `run.py` | For each answers file: render twice and diff, `uv lock` + `uv sync`, `pytest`, `docker compose config`. Writes `report.json` and `report.md`. |
| `fixture_registry.py` | The overlay -> pytest fixtures map, built from `registry.yaml`, plus a lint of the conftest-fragment contract. See `docs/fixture-registry.md`. |

## Running

Everything runs under `uv`. The scripts carry PEP 723 inline dependencies, so
`uv run harness/<script>.py` works from a bare checkout; inside `uv run python
harness/<script>.py` the project environment is used instead (this is what CI
does).

```
uv run harness/combinations.py full                       # print the full count
uv run harness/combinations.py pairwise --out .out/pw     # write the pairwise set
uv run harness/combinations.py full --include db_postgres,db_redis --out .out/data
uv run harness/combinations.py full --pin topology=single --include langgraph,langgraph_checkpoint

uv run harness/combinations.py singletons --out .out/sg   # per-overlay isolation set

uv run python harness/run.py --mode pairwise              # pairwise + singletons, run
uv run python harness/run.py --mode singletons            # just the singletons
uv run python harness/run.py --answers ci/answers/zero-overlay.yml
uv run python harness/run.py --manifest .out/pw           # run an existing set
uv run harness/fixture_registry.py                        # print the fixture map
```

## Modes

- `full` — every valid distinct combination (exact count; materializes only when
  small enough, so narrow with `--include` / `--pin`).
- `pairwise` — a deterministic greedy 2-wise covering set. `run.py --mode
  pairwise` also folds in the `singletons` set (disable with `--no-singletons`),
  so a newly `implemented` overlay always executes even if the greedy never
  isolated it.
- `singletons` — the base-only combination plus, for each overlay, the minimal
  valid combination that turns its gate on. This is the per-overlay Definition of
  Done from `docs/boots-test-contract.md`: "overlay alone on the base" and
  "overlay plus every overlay it names in `requires`" (validity forces the latter
  when needed, e.g. `langchain` pulls in `llm_openai`, `embedding_pipeline` pulls
  in `db_qdrant`).

## Determinism

- Axes are processed in a fixed order: registry group `order`, then key name.
- Every domain is iterated in registry order (`bool` is `[false, true]`).
- Output file names are `sha256(answers-yaml)[:12]`; `manifest.json` and the file
  list are sorted by that hash.
- No `set` iteration reaches an output path, a file name, or the manifest.
- `pairwise` and `singletons` use deterministic greedy selection, no RNG.
- `full` enumeration is exhaustive backtracking in a fixed axis order.

## `combinations.py` algorithm

### Axis derivation

Each `options` entry becomes an axis unless it is a computed key (`when: false`),
a free-form string (`service_name`), or a `json` / `yaml` typed key
(`services_config`, `service_names`). Those are pinned to a fixed value that still
lands in every answers file. `bool` -> `[false, true]`; `str` with `choices` ->
the choice values; `int` -> a fixed candidate list (`embedding_vector_size` is the
only one, `[384, 1536, 3072]`).

An axis is **coupled** if it has its own `when` / `requires` / `conflicts` or its
key appears in any constraint expression anywhere in the registry. Otherwise it is
**independent**: nothing constrains it, so it contributes a plain multiplicative
factor.

### `full`

The coupled axes are partitioned into **constraint components** by union-find:
two axes are linked if they appear together in the same constraint string. Two
components share no constraint, so each is enumerated on its own by backtracking
(fixed axis order, `when`-false conditional axes pinned, early prune when a
`validation_rule`'s keys are all bound), then canonicalized and validated at the
leaf, then de-duplicated.

```
full_count = product(valid combos per component) * product(len(independent domains))
```

This is an exact count. On the current registry it is a nine-figure number, so
`full` only writes answers files when the count is at or below `--max-materialize`
(default 200). Narrow the axis set with `--include` (keep only these axes
variable) and `--pin key=value` (fix an axis) for a per-milestone `full` run that
is small enough to materialize and execute.

### `pairwise`

A deterministic greedy 2-wise covering array built over the constraint
components, not single axes:

1. Enumerate every component's full set of valid canonical sub-assignments (as in
   `full`). Independent axes are 1-axis components.
2. A target pair `(ka=va, kb=vb)` is **feasible** iff, when `ka` and `kb` are in
   the same component, some sub-assignment has both; or, when they are in
   different components, `va` is reachable for `ka` and `vb` for `kb`
   independently. Cross-component choices never interact, so this is exact.
   Infeasible pairs (for example `redis_pubsub=true` with `db_redis=false`, or
   `topology=single` with `transport_grpc=true`) are listed in the manifest and
   excluded from the coverage goal.
3. While feasible pairs are uncovered, seed a case from the first uncovered pair
   (sorted order), then for each component in order pick the valid sub-assignment
   (its enumerated order breaks ties) that is consistent with the seed and covers
   the most still-uncovered pairs. Every case is valid by construction.

Terminates because each case covers at least its seed pair. IPOG or a
constraint-aware SAT-backed covering-array tool would give a smaller set; the
greedy is enough for the skeleton and stays trivially deterministic.

## `run.py` behavior

- Renders with `copier copy --force --trust --skip-tasks --data-file <f> <src> <dest>`.
  With no `--vcs-ref` and a local template path this renders the working tree
  (template-development mode); pass `--vcs-ref <tag>` for a pinned CI run (D-012).
  `run.py` drives `uv lock` itself instead of Copier's `_tasks`, so the lock step
  is captured and can be skipped with `--no-lock`.
- The determinism comparison hashes every rendered file. `.copier-answers.yml`
  has its `_commit` and `_src_path` lines normalized out first: rendering a dirty
  worktree makes Copier mint a throwaway snapshot commit per render, which is not
  a content change. In pinned `--vcs-ref` mode nothing is normalized.
- A combination that selects an overlay whose `build_status` is not `implemented`
  is reported `skip` with the milestone number. No code change here is needed as
  overlays land.
- `boot_under_compose()` (Phase 2): when the combination selects a datastore /
  broker overlay (one with `compose_services` in the registry) and Docker is
  reachable, the runner does not stop at `docker compose config`. It runs
  `docker compose up -d --wait --wait-timeout <n>` for the backing services
  (every compose service without a `build:` section, so the app image is not
  built), asserts they reach healthy, and always tears down with
  `docker compose down -v`. Skip-safe: if the `docker` CLI, the Compose plugin,
  or a reachable daemon is missing, the step is `skip`, not `fail`. Disable with
  `--no-compose-boot`; tune the wait with `--compose-timeout` (default 180s).
- Skip-safe: if `copier` is missing or the template has no `copier.yml`, the run
  prints a notice and exits 0 unless `--strict`.

## `topology != single` orchestration (Phase 7 task 1)

A `monorepo` / `multi_repo` combination no longer renders as one degenerate
Copier tree. `run_combination` detects `canon["topology"] != "single"` and
switches to `render_topology()`, which calls
`msvc_gen.topology.run_multi_service_new()` in-process - the exact function
`msvc-gen new` uses: N per-service Copier renders in `service_names` order
into `services/<svc>/` (`monorepo`) or `<svc>/` (`multi_repo`), then the root
wiring layer (root `docker-compose.yml`, `README.md`, CI workflow, and - when
`transport_grpc` is on or a service ships `api_grpc` - the shared `proto/` +
`buf.yaml`). Both renders in the double-render determinism check go through
this same path, so the comparison covers every service directory and the root
layer, not just a single tree.

Everything downstream is per-project:

- **Per service**: `uv lock` / `uv sync` / `uv run pytest` / the boots-tests
  guard run once per `services/<svc>/` (or `<svc>/`), using **that service's
  own effective overlay selection** - registry defaults, the shared top-level
  keys (`license`/`ci`/`iac`/`docker`), then `services_config[svc]` (mirrors
  `msvc_gen.topology.effective_answers`). Step names are suffixed `[svc]`
  (`uv_lock[api]`, `pytest[worker]`, ...) so a multi-service record's steps
  stay attributable. The record also carries `per_service_overlays`.
- **Root layer**: `docker compose config` (`root_compose_config`), then
  `boot_under_compose()` against the SAME root `docker-compose.yml` - it
  already only starts services without a `build:` section, so this reuses the
  existing function unchanged and boots the union of every selected service's
  datastores/brokers plus the shared transport broker for real.
- **`tests_contract`**: `contract_check()`, see below.

`services_config` is a free-form `json` key that `combinations.py` pins to
`{}` for every generated combo (it is not modeled as an axis), so a
`transport_grpc=true` combo can reach render time with no service carrying
`api_grpc` and be rejected by V-18
(`docs/services-config-schema.md` §5 / `scripts/validate_registry.py`).
`_fixup_services_config_for_v18()` mirrors what a real user is required to do:
if `transport_grpc` is on and no submap already sets `api_grpc`, it turns
`api_grpc` on for the first service, and the record's `per_service_overlays`
reflects that so the report stays honest about what actually rendered. It
never touches `combinations.py`'s axis model.

For real multi-service coverage (more than the harness's own pinned/degenerate
1-service topology combos), run the dedicated fixture:

```
uv run python harness/run.py --answers ci/answers/monorepo-2svc.yml --report-dir .harness-out/topology-2svc
```

Two services (`api`, `worker`), both transports on, `tests_contract: true` -
exercises every part of the orchestration: per-service overlay divergence
(`api` gets postgres + gRPC + tool scaffold, `worker` gets redis + rabbitmq),
the root compose union (postgres + redis + rabbitmq all boot together), and
the contract check.

## `tests_contract` real wiring (Phase 7 task 3)

`contract_check()` (called only for `topology != single` combos with
`tests_contract: true`) runs the two mechanisms from
`docs/grpc-contract-tests.md` for real against the rendered root `proto/`
tree, not just checking the files exist:

- **`buf lint`**, for real, when the `buf` binary is on PATH. Skip-safe
  otherwise (`buf` is not installed in every environment, including the one
  this was verified in - the step records `buf lint: skip (buf not on PATH)`
  rather than failing).
- **The no-toolchain descriptor-set fallback**, always run for real:
  `proto/gen_descriptor_set.py` is executed via `uv run` from whichever
  service directory ships `api_grpc` (the root layer has no Python project of
  its own - `grpcio-tools` lives in that overlay's dev-deps). Asserts
  `proto/descriptor.pb` is non-empty and that regenerating it twice back to
  back is byte-identical - the determinism half of D-009's "regenerate, then
  `git diff --exit-code`" contract; there is no prior git history to diff
  against in a fresh scratch render, so this checks the generator is a pure
  function of the `proto/` tree, which is the property the real CI guard
  depends on.

Verified against `ci/answers/monorepo-2svc.yml` (`transport_grpc` +
`tests_contract`, both services): `descriptor-set fallback: pass (326 bytes,
regen byte-stable)`.

## `tests_integration` container-mode pytest (Phase 7 task 2, D-031)

Every `tests_integration: true` combination previously ERRORed:
`testcontainers` fixtures (`postgres_container`, `redis_container`, ...) open
containers directly through the Docker Python SDK, and on this Docker
Desktop-for-Mac setup `testcontainers`' `ryuk` reaper sidecar fails to start
with `error while creating mount source path
'/host_mnt/.../docker.sock': operation not supported` - reproduced directly: a
`db_postgres` + `tests_integration` combo ERRORs in `PostgresContainer.start()`
with exactly that message, and goes 10/10 green with `ryuk` disabled. `run.py`
now runs the pytest step for any `tests_integration: true` project (single or
per-service, topology or not) with `TESTCONTAINERS_RYUK_DISABLED=true`
(`TESTS_INTEGRATION_ENV`) set on the subprocess environment.

Ryuk is only the orphan-container reaper for processes that die abnormally;
every fixture already stops its own container via its `with
...Container(...)` context manager on normal exit (which a harness pytest run
always reaches), so disabling it does not weaken cleanup here. If a future
environment does not exhibit this specific Docker Desktop quirk, the env var
is harmless - ryuk simply isn't needed as a backstop for a process that always
exits cleanly.

With this fix, the Phase 6 `tests_integration=false` pin is no longer required
for the axis to pass; see "Phase 7 gate" below for the unpinned run.

## Known gaps

- The compose boot proves the assembled compose file is runnable. Running an
  overlay's boots test against the compose-provided services (rather than the
  testcontainers path pytest already uses) is a possible later addition; it needs
  the overlay settings env-var-to-published-port contract.
- `buf` itself is not installed in the environment this was verified in, so
  `contract_check()`'s `buf lint` step has not been exercised for real here -
  only the no-toolchain descriptor-set fallback has. Both paths are wired;
  install `buf` to exercise the first for real.
- `rabbitmq:4.1-management`'s healthcheck is flaky under `boot_under_compose`
  on this Docker Desktop setup independent of any overlay or topology code
  (observed both via the dedicated `rabbitmq`-only isolation test and the
  `monorepo-2svc` combo: one run times out waiting for `healthy`, the very
  next run - no code change - is clean). Not a defect in this repo; a retry
  clears it. Investigate the image / healthcheck timing if it recurs often in
  CI (owner: Data Layer / Messaging, image pin D-023-adjacent).
- `uv` in this environment is older than the registry pin (`0.12.10`); the
  skeleton works with it but CI pins the newer one.
- **A live `isolation: "worktree"` agent worktree under `.claude/worktrees/`
  breaks every dirty-worktree (`vcs_ref=None`) Copier render** - `git worktree
  list` shows it `locked`; Copier's dirty-tree clone runs `git submodule
  update --init --recursive --force` and the worktree's nested `.git` gitlink
  has no `.gitmodules` entry, so that step fails for every combination, not
  just topology ones. Not a code defect (see "Phase 7 gate" below for the full
  diagnosis and reproduction). Check `git worktree list` before trusting a red
  gate or an empty-looking `services/<svc>/` from `msvc-gen new`; pin
  `--vcs-ref` to sidestep it if a worktree must stay live.

## Phase 6 gate (combinatorial verification)

The authoritative Phase 6 command is a pinned pairwise run:

```
uv run harness/combinations.py pairwise --pin tests_integration=false --out .harness-out/phase6-pw
uv run python harness/run.py --manifest .harness-out/phase6-pw --report-dir .harness-out/phase6-gate
```

Run it against a committed, quiescent tree (no concurrent edits to `template/`,
`registry.yaml`, `copier.yml` or `includes/` while it renders — the double-render
determinism check will spuriously fail if a fragment changes between render 1 and
render 2). Docker must be up so the compose-boot step exercises the datastore /
broker stacks for real.

`tests_integration=false` is pinned deliberately: the `tests_integration=true`
branch renders the `testcontainers`-backed overlay fixtures and an
integration-mode readiness path that are **Phase 7 / milestone 8 scope**
(container-mode pytest wiring, D-031; and the base
`tests/test_app_boots.py::test_health_ready` assertion is not yet
integration-mode-aware). Those combinations fail today by construction, not
because of an overlay defect. Phase 7 flips the axis back on after that work
lands — nothing here needs reverting, `run.py`'s own defaults are unchanged.

For the deferred-axis picture, a full unpinned `run.py --mode pairwise` is still
useful: it additionally folds in the `singletons` set and every
`tests_integration=true` pair, so it shows exactly which combinations are blocked
on Phase 7.

## Phase 7 gate (topology orchestration + container-mode pytest + buf wiring)

Phase 7 task 2 (`TESTCONTAINERS_RYUK_DISABLED`, above) removes the reason the
Phase 6 gate pinned `tests_integration=false`. The authoritative command is now
the SAME pairwise run with the axis unpinned:

```
uv run python harness/run.py --mode pairwise --report-dir .harness-out/phase7-gate
```

(equivalent to `combinations.py pairwise --out <dir>` piped into `run.py
--manifest <dir>`, folding in the `singletons` set as `--mode pairwise` always
does.) Same quiescent-tree and Docker-up preconditions as the Phase 6 gate.

First result (2026-09-11, this environment, tree not fully quiescent - see
below): 51 combinations (pairwise + folded singletons), 38 pass, 13 fail, 0
skip. Every `tests_integration=true` combination in the set passed (previously
deferred by the Phase 6 pin) - task 2 verified in the standing gate, not just
in isolation. The set includes `monorepo` / `multi_repo` combinations rendered
through the real orchestration path (task 1) - though, per the note above, the
harness's own axis model always pins `service_names` to `["api"]`, so those
particular combos exercise the orchestration code path with one service. The
dedicated `monorepo-2svc` / `multi_repo-2svc` fixture runs (two services,
divergent overlays, both transports, `tests_contract`) are the multi-service
coverage; both fully green - see above.

All 13 failures in that run, and a full 29/29 failure on an immediate
re-run, traced to **one external cause unrelated to this repo's code**: a
teammate's `isolation: "worktree"` agent left a *locked* git worktree at
`.claude/worktrees/agent-<id>/` (visible via `git worktree list`) nested
inside this checkout while the gate was rendering. Copier's dirty-worktree
clone (`vcs_ref=None`, "template-development mode") runs `git submodule
update --checkout --init --recursive --force` over the snapshotted tree; the
worktree's nested `.git` gitlink file has no matching `.gitmodules` entry, so
that step fails with `fatal: No url found for submodule path
'.claude/worktrees/...'`. This affects **every** dirty-worktree render, not
just topology combos - reproduced on a plain `streaming_sse`-only combo with
the identical traceback. It does not affect a `--vcs-ref`-pinned render
(Copier fetches a specific commit instead of cloning the live working
directory), which is why a direct `msvc-gen new ... --vcs-ref HEAD`
reproduction with the same `monorepo-2svc` answers rendered both services in
full (74 + 55 files - `main.py`, `config/`, `grpc/`, `transport/`, `tests/`,
`pyproject.toml`, ...), not just `.claude/`. Do not re-run the gate (or trust
a dirty-tree `msvc-gen new`) while a worktree is live under `.claude/`; wait
for it to clear or pin `--vcs-ref`.

One `compose_boot` re-run was also needed earlier, unrelated to the above:
`rabbitmq` failed to reach `healthy` within its wait window once (see Known
gaps) and passed clean on retry with no code change - a pre-existing
environment flake.

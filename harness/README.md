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

## Known gaps (Phase 2+)

- The compose boot proves the assembled compose file is runnable. Running an
  overlay's boots test against the compose-provided services (rather than the
  testcontainers path pytest already uses) is a possible later addition; it needs
  the overlay settings env-var-to-published-port contract.
- gRPC contract tests: spec only, see `docs/grpc-contract-tests.md`.
- The temporary hand-written `copier.yml` only carries the base plus
  `otel_tracing` questions, so overlay answer keys are currently ignored by
  Copier. Once `scripts/gen_copier_yml.py` emits the full `copier.yml`, the
  pairwise and full runs exercise real overlay selection.
- `uv` in this environment is older than the registry pin (`0.12.10`); the
  skeleton works with it but CI pins the newer one.

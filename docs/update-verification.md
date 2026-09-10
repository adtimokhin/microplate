# `copier update` verification

Owner: DevOps & Distribution Engineer (harness), Release & Docs Engineer
(Phase 5 slice results). Builds the scope milestone 10 gate: "`copier update`
applies cleanly against a generated service after a template change".

## What is verified

Given the template at release N and a project generated from it, applying a
trivial template change tagged N+1 and running the update must:

1. exit 0,
2. leave no conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`) in any file,
3. leave no `.rej` reject files,
4. actually apply the change (the canary file appears in the project - once per
   service tree for a multi-service project),
5. leave the generated project's test suite passing.

This is the concrete form of the two working agreements: determinism and clean
update. It complements `scripts/check_determinism.py` (same inputs -> same bytes)
by checking the cross-version diff replay.

## The harness

`scripts/verify_update.sh`:

1. Copies the template repo working tree into a scratch dir, `git init`,
   commits, tags `v9000.0.0`.
2. Generates a project at `v9000.0.0` into a second scratch dir, `git init` +
   commits it.
   - **single service** (`topology: single`, or no `topology:` in the answers
     file): `copier copy --data-file <answers> --vcs-ref v9000.0.0`.
   - **multi-service** (`topology: monorepo` / `multi_repo` in the answers
     file): `msvc-gen new --template-src <scratch> --vcs-ref v9000.0.0`, which
     renders one single-service tree per `service_names` entry plus the root
     wiring layer (D-036).
3. Adds one trivial file to the template (`template/.update_canary.jinja`),
   commits, tags `v9000.0.1`.
4. Applies the update against `v9000.0.1`:
   - single: `cd project && copier update --defaults --trust --skip-tasks
     --conflict rej --vcs-ref v9000.0.1`.
   - multi-service: `msvc-gen update --output project --vcs-ref v9000.0.1
     --skip-tasks --conflict rej`, which re-runs `copier update` in every
     `services/<svc>/` (frozen order) and re-renders the root layer wholesale.
     The roster and per-service config are read from the root
     `.copier-answers.yml` manifest.
5. Asserts exit 0, greps for conflict markers, finds `.rej` files, checks the
   canary landed (per service for multi-service).
6. Runs `uv sync && uv run pytest -q` in the generated project (in each
   `services/<svc>/` for multi-service) and asserts it passes.

All tags are local to the throwaway scratch clone. The script never creates
tags in the real repo and never pushes. The scratch dir is resolved with
`pwd -P` so `copier update` on a project rendered into a subdirectory (the
monorepo `services/<svc>/` case) does not trip over the macOS
`/var` -> `/private/var` symlink when it compares against `git rev-parse
--show-toplevel`.

### Usage

```sh
# Against the real generator template, one overlay slice:
scripts/verify_update.sh --template-repo . --answers ci/answers/datastore-postgres-redis.yml

# A monorepo slice (switches to the msvc-gen orchestration path automatically):
scripts/verify_update.sh --template-repo . --answers ci/answers/monorepo-2svc.yml

# Keep the scratch dir for inspection:
scripts/verify_update.sh --template-repo . --answers ci/answers/rag-backend.yml --keep
```

Flags: `--template-repo PATH` (default `.`), `--answers PATH` (default: Copier
`--defaults`), `--subdir NAME` (default `template`), `--keep`.

Exit codes: `0` pass, `1` verification failed, `2` environment problem
(no `copier` / `git`, or a multi-service answers file with no `msvc-gen` on
PATH). When `--template-repo` has no `copier.yml` the script exits 0 with a
skip notice.

## Phase 5 slice results (2026-09-09)

Run against the working-tree template on `build/all-phases` (33 registry keys
`build_status: implemented`), Copier 9.18.2, CPython 3.12.11, `uv` 0.7.13.

| Slice | Answers file | Selection | Update path | Result |
| --- | --- | --- | --- | --- |
| Datastore | `ci/answers/datastore-postgres-redis.yml` | `db_postgres` + `db_redis` + `redis_pubsub` | `copier update` | clean apply, canary present, generated `pytest` 8 passed |
| AI / RAG | `ci/answers/rag-backend.yml` | `db_qdrant` + `llm_openai` + `langchain` + `langchain_retrieval` + `embedding_pipeline` (`embedding_backend: openai`, vector size 1536) | `copier update` | clean apply, canary present, generated `pytest` 13 passed |
| LangGraph | `ci/answers/agent-langgraph.yml` | `db_postgres` + `db_redis` + `langgraph` (`langgraph_checkpoint: postgres`) | `copier update` | clean apply, canary present, generated `pytest` 9 passed |
| Monorepo | `ci/answers/monorepo-2svc.yml` | 2 services - `api` (`api_grpc` + `db_postgres` + `tool_scaffold`), `worker` (`messaging_rabbitmq` + `db_redis`); `transport_grpc` + `transport_rabbitmq` + `tests_contract` at the top level | `msvc-gen update` (per-service `copier update` x2 + root re-render) | clean apply, canary present in both service trees, `services/api` `pytest` 14 passed, `services/worker` `pytest` 13 passed |

No conflict markers, no `.rej` files, and no path-move / reflow issues in any
slice. The monorepo root layer (`docker-compose.yml`, `proto/`, `buf.yaml`,
root CI, `.copier-answers.yml` manifest) re-rendered wholesale without error.

### Harness change made in Phase 5

`scripts/verify_update.sh` gained the multi-service path (topology detection
from the answers file -> `msvc-gen new` / `msvc-gen update`, per-service canary
and pytest assertions) and the `pwd -P` scratch-dir fix described above. The
single-service path is unchanged.

### Generator issue found (for the Lead)

`msvc_gen/topology.py` `run_multi_service_new` / `run_multi_service_update` pass
`output` (and `service_dest(output, ...)`) into `copier.run_update` without
resolving it. `copier update` on a subdirectory project computes
`local_abspath.relative_to(git_rev_parse_show_toplevel)`; when `output` is under
a symlink (macOS `mktemp` `/var/...`, or any user path with a symlinked parent)
the two sides disagree and Copier raises `ValueError: ... is not in the subpath
of ...`. The harness works around it with `pwd -P`; the durable fix is
`output = Path(output).resolve()` at the top of both `run_multi_service_*`
functions. Low risk, one line each.

## CI wiring

`.github/workflows/generator-ci.yml` job `update-verify` runs the harness
against `tests/fixtures/determinism_fixture` (strict) and against the repo root
(skip-safe). It can be extended to loop the curated `ci/answers/*.yml` slices
above once CI runners have Docker-free `uv` + `copier`. Once real release tags
exist, a follow-up job can additionally verify `copier update` between the two
most recent real tags.

## Known failure modes this catches

- A rendered output path moved without a `_migrations` `git mv`
  (overlay-contract §8.2): update leaves the old file and writes the new one, or
  conflicts.
- `overlay_order` reordered: unrelated shared files reflow, update conflicts on
  them.
- A fragment indentation contract changed so an unchanged selection renders
  different bytes: update conflicts on `pyproject.toml` / compose / settings.
- A registry key or value renamed without a computed alias: the old answers file
  no longer validates, update aborts.
- Non-list-form `_tasks` or a time/random Jinja extension: output varies between
  the two clones, update replays a spurious diff.
- A multi-service root manifest that drops `topology` / `service_names` /
  `services_config`: `msvc-gen update` can no longer re-drive the per-service
  renders.

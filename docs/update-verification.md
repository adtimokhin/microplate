# `copier update` verification

Owner: DevOps & Distribution Engineer. Builds the Phase 5 milestone 10 gate:
"`copier update` applies cleanly after a trivial template change".

## What is verified

Given the template at release N and a generated project from it, applying a
trivial template change tagged N+1 and running `copier update` must:

1. exit 0,
2. leave no conflict markers (`<<<<<<<`, `=======`, `>>>>>>>`) in any file,
3. leave no `.rej` reject files,
4. actually apply the change (the canary file appears in the project),
5. leave the generated project's test suite passing (once the base template
   ships one).

This is the concrete form of the two working agreements: determinism and clean
update. It complements `scripts/check_determinism.py` (same inputs -> same bytes)
by checking the cross-version diff replay.

## The harness

`scripts/verify_update.sh`:

1. Copies the template repo working tree into a scratch dir, `git init`,
   commits, tags `v0.0.0-verify`.
2. `copier copy --vcs-ref v0.0.0-verify` into a second scratch dir; `git init` +
   commit the generated project.
3. Adds one trivial file to the template (`<subdir>/.update_canary.jinja`),
   commits, tags `v0.0.1-verify`.
4. `cd project && copier update --force --vcs-ref v0.0.1-verify --defaults`.
5. Asserts exit 0, greps for conflict markers, finds `.rej` files, checks the
   canary landed.
6. If the generated project has `pyproject.toml` and a `tests/` dir, runs
   `uv sync && uv run pytest -q` and asserts it passes. Skips with a notice
   otherwise.

All tags are local to the throwaway scratch clone. The script never creates
tags in the real repo and never pushes.

### Usage

```sh
# End to end against the bundled fixture (works today):
scripts/verify_update.sh \
  --template-repo tests/fixtures/determinism_fixture \
  --answers tests/fixtures/determinism_fixture/answers/default.yml

# Against the real generator template (skip-safe until it lands):
scripts/verify_update.sh --template-repo . --answers ci/answers/zero-overlay.yml

# Keep the scratch dir for inspection:
scripts/verify_update.sh --template-repo . --keep
```

Flags: `--template-repo PATH` (default `.`), `--answers PATH` (default: use
Copier `--defaults`), `--subdir NAME` (default `template`), `--keep`.

Exit codes: `0` pass, `1` verification failed, `2` environment problem
(no `copier` / `git`). When `--template-repo` has no `copier.yml` yet the script
exits 0 with a skip notice.

## CI wiring

`.github/workflows/generator-ci.yml` job `update-verify` runs the harness twice:

- against `tests/fixtures/determinism_fixture` (strict, proves the harness),
- against the repo root (skip-safe until the base template lands).

Once real release tags exist, a follow-up job can additionally verify
`copier update` between the two most recent real tags on a project generated
from the older one. That job is deferred until there are two tags to compare.

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

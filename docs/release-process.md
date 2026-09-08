# Release process

Owner: DevOps & Distribution Engineer. Operationalizes D-010, D-012, D-019, and
scope §7.

## Branching and tags

- Pre-v1 iteration happens on `main`. Feature work lands on `main` via PR.
- Every release is an annotated SemVer git tag `vMAJOR.MINOR.PATCH` on `main`.
- Tags are immutable. Never move or delete a published tag. Copier `update`
  resolves customer projects against these tags; a moved tag silently corrupts
  every downstream `copier update` (D-012, research/copier.md "Known gotchas").
- Pre-release tags (`v0.3.0-rc1`) are allowed but the CLI never selects them
  automatically. Copier's own "highest PEP 440 tag" default is never relied on:
  the generator CLI always passes an explicit `--vcs-ref <tag>` on both
  `copier copy` and `copier update` (D-012).

## Versioning rules (pre-v1)

While the major is `0`:

- PATCH (`v0.x.Z+1`): overlay bug fixes, pin bumps, docs, new answers files,
  fragment additions that render unchanged bytes for an unchanged selection.
- MINOR (`v0.Y+1.0`): new overlay, new registry key, new answer value, anything
  that adds a question or changes rendered output for some selection. Must ship
  with safe defaults so old answers files still validate (overlay-contract §8.2).
- A change that renames a key or value, reorders `overlay_order`, or moves a
  rendered output path is NOT allowed without a `_migrations` entry in
  `registry.yaml` (overlay-contract §8.3). If unavoidable, it is a MINOR bump
  carrying that migration.

`meta.registry_version` in `registry.yaml` is a separate integer. Bump it only on
a breaking change to the registry file's own shape (schema of the schema), not on
every release. It is stamped into generated answers files as `_registry_version`
for update diagnostics.

## Cutting a release

Prerequisites: on `main`, working tree clean, CI green on the release commit.

1. `git switch main && git pull`
2. Decide the version per the rules above.
3. If `meta.registry_version` shape changed, bump it in `registry.yaml` in a
   prior commit.
4. Run the helper (creates the changelog entry, the release commit, and the
   annotated tag; does not push):

   ```sh
   scripts/tag_release.sh v0.Y.Z            # add --dry-run first to preview
   ```

   The script refuses if: not on `main`, tree dirty, tag exists, or the new tag
   does not sort strictly after the latest `vN.N.N` tag. It also runs
   `scripts/validate_registry.py`.
5. Review `CHANGELOG.md` and the release commit.
6. Get Lead sign-off, then push:

   ```sh
   git push origin main v0.Y.Z
   ```

   Pushing tags to origin always needs explicit Lead approval (team working
   agreement). CI has no tag-push automation.

## Manual fallback (no script)

1. Update `CHANGELOG.md`: new `## v0.Y.Z - YYYY-MM-DD` section, bullets from
   `git log --no-merges <prev-tag>..HEAD`.
2. `git commit -m "release: v0.Y.Z"`
3. `git tag -a v0.Y.Z -m "v0.Y.Z (YYYY-MM-DD)"`
4. `python scripts/validate_registry.py`
5. Lead sign-off, then `git push origin main v0.Y.Z`.

## Refreshing dependency pins (D-019)

v0 pins are frozen. Overlay engineers use the registry pin as-is and never
re-pin to latest at build time. Bumps happen only through this task:

- Automation: `.github/workflows/refresh-pins.yml` runs weekly (Mondays 06:00
  UTC) and on demand (`workflow_dispatch`). It runs `scripts/refresh_pins.py`,
  which checks every `python_deps` entry in `registry.yaml` and every `==` pin in
  `pyproject.toml` against the PyPI JSON API, bumps outdated pins to the latest
  stable, stamps `as_of` with the run date, writes `pin-refresh-report.md`, and
  opens a single PR on branch `chore/refresh-pins`.
- The PR review IS the per-pin upstream re-verification D-019 requires. The
  reviewer checks each bump against its upstream changelog for breaking changes
  before merging. Record the merge in `STATUS.md`.
- Compose image pins (Docker Hub tags / digests) are owned by the Data Layer
  Engineer (D-023) and are not yet covered by the script - listed as TODO in the
  report.
- If a pin is found yanked or broken, raise it to the Lead rather than bumping
  silently (D-019).

## Private repo and CLI pinning

- The template repo is a single private GitHub repo (scope §7).
- The generator is installed as one command (`uv tool install` / `pipx install`)
  and every invocation pins `--vcs-ref` to a release tag.
- CI runners in downstream projects that run `copier update` authenticate to
  this private repo per `docs/private-template-access.md`.

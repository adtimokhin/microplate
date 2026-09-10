# Copier research notes (Registry & Copier Architect)

All URLs accessed 2026-09-07.

## Version pin

- Copier latest release: **9.18.2** (2026-09-07). Prior: 9.18.1 (2026-09-01), 9.18.0 (2026-09-01), 9.17.2 (2026-08-19), 9.17.1 (2026-08-04).
  Source: https://copier.readthedocs.io/en/stable/changelog/
- Decision for this project: require `copier >= 9.18.2` in the generator. Rationale: `multiselect: true` (9.1.0), `validator` on questions and choices, `{% yield %}` dynamic file structures (9.5.0), `_copier_operation` in task `when` conditions, and `--conflict rej` are all needed and all present by 9.5.x; pinning to the current release keeps behavior stable.

## Overlay inclusion

- Conditional file names: `{% if use_precommit %}.pre-commit-config.yaml{% endif %}.jinja`. The template suffix (`.jinja`) MUST sit outside the Jinja condition or the file is not treated as a template.
  Source: https://copier.readthedocs.io/en/stable/configuring/
- Conditional directory names: `{% if ci == 'github' %}.github{% endif %}`. Directories MUST NOT end with the template suffix.
  Source: https://copier.readthedocs.io/en/stable/creating/
- If a templated file or directory name renders to an empty string, that file or directory is skipped, and for a directory its contents are skipped too (they are NOT relocated to the parent).
  Sources: https://github.com/copier-org/copier/issues/216 , https://github.com/copier-org/copier/issues/315
- Two sibling directories in the template repo whose templated names render to the same destination string are merged into one destination directory. This is what lets isolated overlay subtrees land in a single service source tree.
  Source: https://copier.readthedocs.io/en/stable/creating/
- `_exclude` in `copier.yml` REPLACES the built-in defaults (`copier.yaml`, `copier.yml`, `~*`, `*.py[co]`, `__pycache__`, `.git`, `.DS_Store`, `.svn`). Passing excludes via CLI/API EXTENDS them instead. Each pattern is Jinja-rendered and supports gitignore-style negation (`!keep`).
  Source: https://copier.readthedocs.io/en/stable/configuring/
- `_exclude` patterns use gitignore/pathspec semantics: an unanchored bare name (no slash) matches a directory of that name at ANY depth. Anchor a root-only exclude with a leading slash (`/_fragments`). A bare `overlays` in `_exclude` matched and dropped the rendered `tests/overlays/` boots-test subtree (bug found + fixed 2026-09-08). Only exclude paths that are actually inside `_subdirectory`.
- `_skip_if_exists`: listed paths are created if missing but never overwritten on `copier copy` or `copier update`. Use for user-owned files the template seeds once.
  Source: https://copier.readthedocs.io/en/stable/configuring/
- `_subdirectory`: single directory used as the template root. Value may be templated but resolves to exactly one path, so it cannot compose multiple overlays. Use it only to separate template metadata from the rendered tree.
  Source: https://copier.readthedocs.io/en/stable/configuring/

## Shared Jinja partials and macros

- Shared includes go in a dedicated folder (convention: `includes/`) referenced with `{% include 'includes/foo.jinja' %}` or `{% from 'includes/slugify.jinja' import slugify %}`, usable both inside templated files and inside `copier.yml` defaults/validators.
- That folder must be added to `_exclude` so the partials are not copied into the generated project. Copier's Jinja `FileSystemLoader` is rooted at the template root, so excluded partials are still resolvable by `include`/`import`.
  Source: https://copier.readthedocs.io/en/stable/configuring/ (section: "Include other templates" / "Import Jinja macros")

## Tasks, extensions, migrations

- `_tasks`: shell strings or arg arrays, run after copy AND after update. Support `when`, `working_directory`. Env `$STAGE=task`. `when` can read `{{ _copier_operation }}` (`copy` or `update`).
- `_jinja_extensions`: arbitrary import paths, loaded into the render environment. `jinja2_ansible_filters.AnsibleCoreFiltersExtension` is always loaded (gives `to_nice_yaml`, `regex_search`, etc.). Extensions run arbitrary code and must be installed in the same environment as Copier.
- `_migrations`: version-gated commands, run only when `old_version < declared_version <= new_version`. Variables: `_stage` (`before`/`after`), `_version_from`, `_version_to`, `_version_current`.
  Source: https://copier.readthedocs.io/en/stable/configuring/

## Questions

- Types: `str`, `bool`, `int`, `float`, `json`, `yaml`, `path`.
- `multiselect: true` makes the answer a `list[T]`; default should be a list.
- `validator`: Jinja rendered with all answers in scope. Renders empty = valid. Renders non-empty = that text is the rejection message.
- Computed values: set `when: false` and put the expression in `default`. Never prompted, always recorded in answers.
- Dict-form `choices` show a label to the user and store the mapped value. A choice can carry its own `validator`.
  Source: https://copier.readthedocs.io/en/stable/configuring/

## Updating

- `copier update` does a three-way merge: (1) regenerate from the OLD template version using the recorded answers, (2) diff that against the current working tree to capture user edits, (3) regenerate from the NEW template version and replay the user diff onto it.
- `.copier-answers.yml` is the anchor. It must be committed and never hand-edited; editing it makes the smart-diff believe a different input produced the tree.
- Conflicts: `--conflict inline` (default) writes git-style conflict markers; `--conflict rej` writes `.rej` files. A pre-commit guard against committing either is recommended.
- Stability requirements for clean updates: do not rename questions, do not rename rendered output paths, keep answer value spellings stable, keep the answers-file name stable. Renames break customization tracking because the diff is path-keyed.
- Files the user deleted stay deleted on update unless matched by `_skip_if_exists`.
  Source: https://copier.readthedocs.io/en/stable/updating/

## Package versions verified 2026-09-07 (PyPI live)

Base/API: fastapi 0.141.1, uvicorn 0.52.4, pydantic 2.13.5, pydantic-settings 2.15.0, httpx 0.28.1, orjson 3.12.0, structlog 26.1.0, tenacity 9.1.4.
Data: sqlalchemy 2.0.52, asyncpg 0.31.0, alembic 1.19.2, greenlet 3.5.5, pymongo 4.18.0 (async API, D-008), redis 8.1.0, qdrant-client 1.19.0.
Messaging: aio-pika 10.0.1.
gRPC/MCP: grpcio 1.83.1, grpcio-tools 1.83.1, mcp 2.2.0.
AI: openai 3.8.0, anthropic 1.4.0, langchain 1.4.0, langchain-core 1.6.2, langchain-openai 1.6.0, langchain-anthropic 1.7.1, langchain-qdrant 1.1.0, langgraph 1.2.11, langgraph-checkpoint-postgres 3.1.2, langgraph-checkpoint-redis 0.5.2, langsmith 0.12.2.
Observability: opentelemetry-sdk 1.44.0, opentelemetry-exporter-otlp-proto-http 1.44.0 (HTTP exporter per D-011), opentelemetry-instrumentation-fastapi 0.65b0.
AI checkpoint drivers: psycopg 3.3.5, psycopg-pool 3.3.1, langgraph-checkpoint 4.2.0, langgraph-checkpoint-postgres 3.1.2, langgraph-checkpoint-redis 0.5.2, fastembed 0.8.0, sse-starlette 3.4.11.
Testing/lint: pytest 9.1.1, pytest-asyncio 1.4.0, pytest-cov 7.1.0, coverage 7.16.0, testcontainers 4.15.0, ruff 0.16.6.

Note: these are the pins recorded in `registry.yaml` v0. Each overlay engineer re-verifies against upstream at build time and updates the registry if a pin moved.

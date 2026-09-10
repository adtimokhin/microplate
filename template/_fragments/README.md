# template/_fragments/

Per-overlay Jinja partials that contribute to base-owned shared files
(`pyproject.toml`, `docker-compose.yml`, `settings.py`, `health.py`,
`.env.example`, `conftest.py`, `ci.yml`, `lifespan.py`).

One directory per overlay id: `_fragments/<overlay-id>/`. Added to `_exclude` in
the generated `copier.yml`; never copied into a project.

Fragment authoring rules: `docs/overlay-contract.md` §4.3, §4.4.

Placeholder file; remove once real fragments land.

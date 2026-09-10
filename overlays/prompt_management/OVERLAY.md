# Overlay: prompt_management

Versioned prompt files plus a load-time registry scoped to prompts. The base
pydantic-settings loader stays base-owned (D-021); this overlay adds only the
`prompts_dir` setting and the registry that reads it.

- Owner: AI Components Engineer
- Registry key: `prompt_management` (bool, default `false`)
- Overlay id: `prompt_management`
- Milestone: 5 (Phase 3)
- Decisions: D-021 (settings loader base-owned, this overlay adds only the prompt
  layer), D-019 (frozen pins), D-032-adjacent (lifespan slot, not runtime mount)
- Requires: nothing

## What it adds

| Surface | Contribution |
| --- | --- |
| Gated subtree | `{{ python_package }}/prompts/` - `registry.py` (`Prompt` schema with `extra="forbid"`, `PromptRegistry` indexed by `(name, version)`, module-level `_registry` holder + `get_registry` / `set_registry`, `load_registry(dir=None)`, `PromptError`), `__init__.py` (exports), `__main__.py` (`python -m {{ python_package }}.prompts --check` CLI for CI) |
| Gated subtree | `prompts/` (project root) - example prompt files `summarize.toml`, `classify.toml` |
| `config/settings.py` | `prompts_dir: str = "prompts"` |
| `.env.example` | `APP_PROMPTS_DIR=prompts` |
| `lifespan.py` | startup hook: `load_registry()` then `set_registry(...)` and mirror onto `app.state.prompt_registry`; shutdown hook: reset the holder to an empty registry |
| `tests/conftest.py` | `prompt_registry` (autouse): points `APP_PROMPTS_DIR` at the shipped `prompts/` dir by absolute path so the loader works from any pytest working directory |
| `.github/workflows/ci.yml` | test job step `uv run python -m {{ python_package }}.prompts --check` - a malformed prompt file fails the build |
| Boots test | `tests/overlays/test_prompt_management_boots.py` |

## Design notes

- Prompt files are TOML, parsed with the standard-library `tomllib`, so the
  overlay adds no Python dependency. TOML multi-line strings hold the prompt
  templates cleanly; placeholders are `str.format` style (`{text}`).
- One file per prompt version. `PromptRegistry.get(name)` returns the highest
  version when no version is passed; `get(name, version=N)` pins one.
- `Prompt` (the pydantic model) IS the prompt-file schema. `extra="forbid"`
  makes an unknown key a validation error, which is what the CI `--check` step
  and the schema test assert.
- No health check (nothing to probe - the registry is in-process data). No
  route. No compose service. No network in any configuration.
- The registry is loaded once at startup, not on every request, and lives in a
  module-level holder mirrored onto `app.state.prompt_registry` - the same
  client-overlay wiring shape used elsewhere, minus the readiness check.
- `load_registry` raises `PromptError` (not a bare `KeyError` / `OSError`) for a
  missing directory, an unparseable file, a duplicate `(name, version)`, or an
  empty directory, so the CI step prints one clear line and exits 1.

## Registry notes for RegistryArchitect

- `template_paths` should list a second gated subtree for the example prompt
  files: `template/{% raw %}{% if prompt_management %}prompts{% endif %}{% endraw %}` (root-level `prompts/`), alongside the existing
  `template/{% raw %}{% if prompt_management %}{{ python_package }}{% endif %}{% endraw %}/prompts`.
- Fixture `prompt_registry` is `kind: mock` (loads shipped files, no container).
- Lifespan hook sets `app.state.prompt_registry`; no `health_checks` entry.
- `ci_steps`: the `--check` step is always-on (not `tests_integration`-gated) -
  it is a schema/lint guard on committed files, the same carve-out class as
  `api_grpc`'s proto drift check (overlay-contract 4.3).

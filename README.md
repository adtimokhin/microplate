# Microservice Boilerplate Generator

Skeleton README. The Lead writes the final version in Phase 5. This stub records
just enough for a contributor to orient.

## What this is

A deterministic, Copier-based generator that assembles a runnable Python backend
microservice from prewritten boilerplate. One terminal command scaffolds a
service into a target folder. Component selection is explicit (CLI flags or an
answers file), maps 1:1 to `registry.yaml`, and involves no LLM in the
generation path. The same inputs always produce the same output.

See `microservice-boilerplate-generator-scope.md` for full scope.

## Repository layout

| Path | Purpose | Owner |
| --- | --- | --- |
| `registry.yaml` | Single source of truth for the question schema | Registry Architect |
| `copier.yml` | Generated from `registry.yaml`. Never hand-edited | derivation script |
| `scripts/` | Derivation, validation, release, and verification scripts | DevOps |
| `includes/` | Shared Jinja macros, excluded from output | Registry Architect |
| `template/` | The Copier `_subdirectory`; everything the user gets | Base + overlay engineers |
| `template/_fragments/` | Per-overlay shared-file fragments, excluded from output | overlay engineers |
| `overlays/` | Overlay metadata and docs, not rendered | overlay engineers |
| `docs/` | Contracts and process docs | mixed |
| `research/` | Upstream research notes | research agents |

## Contributor quickstart

```sh
uv sync
uv run ruff check .
uv run mypy
uv run pytest
```

## Releases

Pre-v1 iteration happens on `main`. Every release is an annotated SemVer tag
`vMAJOR.MINOR.PATCH`. The CLI always pins `--vcs-ref` to a tag. See
`docs/release-process.md`.

## Key process docs

- `docs/overlay-contract.md` - authoritative rules for overlay work
- `docs/registry-schema.md` - registry file structure and validation rules
- `docs/release-process.md` - tagging, changelog, pin refresh
- `docs/private-template-access.md` - how CI runners in downstream projects authenticate to this private template
- `docs/update-verification.md` - the `copier update` clean-apply gate
- `DECISIONS.md` - every resolved ambiguity

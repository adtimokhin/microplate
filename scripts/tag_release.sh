#!/usr/bin/env bash
# tag_release.sh - cut an annotated SemVer release tag for the generator template.
#
# Copier `update` resolves against git tags, so every release MUST be a tag and
# the CLI always pins --vcs-ref to one (D-012). This script does the local half:
# it validates state, updates the changelog stub, and creates the annotated tag.
# It never pushes. Pushing tags to origin needs explicit Lead sign-off.
#
# Usage:
#   scripts/tag_release.sh v0.2.0            # tag HEAD as v0.2.0
#   scripts/tag_release.sh v0.2.0 --dry-run
#
# Preconditions checked:
#   * on `main` (pre-v1 release branch, scope §7)
#   * working tree clean
#   * tag does not already exist
#   * new tag sorts strictly after the latest existing vN.N.N tag
#   * scripts/validate_registry.py passes
#
# Exit: 0 ok | 1 precondition failed | 2 usage

set -euo pipefail

DRY_RUN=0
VERSION="${1:-}"
[ "${2:-}" = "--dry-run" ] && DRY_RUN=1

case "$VERSION" in
  v[0-9]*.[0-9]*.[0-9]*) : ;;
  *) echo "usage: $0 vMAJOR.MINOR.PATCH [--dry-run]" >&2; exit 2 ;;
esac

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
if [ "$BRANCH" != "main" ]; then
  echo "[tag_release] refusing: on '$BRANCH', releases are cut from 'main' (scope 7)" >&2
  exit 1
fi

if [ -n "$(git status --porcelain)" ]; then
  echo "[tag_release] refusing: working tree not clean" >&2
  exit 1
fi

if git rev-parse -q --verify "refs/tags/$VERSION" >/dev/null; then
  echo "[tag_release] refusing: tag $VERSION already exists (tags are immutable, D-012)" >&2
  exit 1
fi

LATEST="$(git tag --list 'v[0-9]*.[0-9]*.[0-9]*' | sort -V | tail -n1 || true)"
if [ -n "$LATEST" ]; then
  HIGH="$(printf '%s\n%s\n' "$LATEST" "$VERSION" | sort -V | tail -n1)"
  if [ "$HIGH" != "$VERSION" ] || [ "$VERSION" = "$LATEST" ]; then
    echo "[tag_release] refusing: $VERSION does not sort after latest tag $LATEST" >&2
    exit 1
  fi
fi

if [ -f scripts/validate_registry.py ]; then
  echo "[tag_release] validating registry"
  # Prefer the project's own uv-managed env (has pyyaml); a bare `python`/
  # `python3` on PATH may have neither pyyaml nor even exist (macOS/CI ships
  # `python3` only). Without this, the check aborts release prep with a
  # confusing "PyYAML is required" error on any machine that has not run
  # `uv sync` and activated the venv.
  if command -v uv >/dev/null 2>&1 && [ -f pyproject.toml ]; then
    uv run python scripts/validate_registry.py registry.yaml
  elif command -v python3 >/dev/null 2>&1; then
    python3 scripts/validate_registry.py registry.yaml
  else
    python scripts/validate_registry.py registry.yaml
  fi
fi

DATE="$(date -u +%Y-%m-%d)"
CHANGELOG="CHANGELOG.md"
RANGE_FROM="${LATEST:-$(git rev-list --max-parents=0 HEAD | tail -n1)}"
NOTES="$(git log --no-merges --pretty='- %s' "${RANGE_FROM}..HEAD" || true)"

echo "[tag_release] $VERSION ($DATE)"
echo "--- changelog entry ---"
printf '## %s - %s\n\n%s\n\n' "$VERSION" "$DATE" "${NOTES:-- (no commits since $RANGE_FROM)}"

if [ "$DRY_RUN" -eq 1 ]; then
  echo "[tag_release] dry run: no changelog write, no tag created"
  exit 0
fi

TMP="$(mktemp)"
{
  echo "# Changelog"
  echo
  printf '## %s - %s\n\n%s\n\n' "$VERSION" "$DATE" "${NOTES:-- (no commits since $RANGE_FROM)}"
  if [ -f "$CHANGELOG" ]; then
    tail -n +2 "$CHANGELOG" | sed '1{/^$/d;}'
  fi
} > "$TMP"
mv "$TMP" "$CHANGELOG"
git add "$CHANGELOG"
git commit -q -m "release: $VERSION"

git tag -a "$VERSION" -m "$VERSION ($DATE)"
echo "[tag_release] created annotated tag $VERSION and release commit."
echo "[tag_release] NOT pushed. After Lead sign-off:  git push origin main $VERSION"

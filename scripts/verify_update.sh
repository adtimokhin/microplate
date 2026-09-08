#!/usr/bin/env bash
# verify_update.sh - prove `copier update` applies cleanly after a trivial template change.
#
# Phase 5 milestone 10 gate. Steps:
#   1. Copy the template repo into a scratch dir, git init, commit, tag vBASE.
#   2. Generate a project from vBASE into a scratch dir; git init + commit it.
#   3. Make a trivial template change (add one canary file), commit, tag vNEXT.
#   4. Run `copier update --vcs-ref vNEXT` on the generated project.
#   5. Assert: update exit 0, no conflict markers, no .rej files.
#   6. If the project has a test suite, run it and assert it passes.
#
# Runs end to end today against tests/fixtures/determinism_fixture. Once the real
# template lands, CI runs it against the repo root.
#
# Usage:
#   scripts/verify_update.sh [--template-repo PATH] [--answers PATH] [--subdir NAME] [--keep]
#
# Exit codes: 0 ok | 1 verification failed | 2 environment problem

set -euo pipefail

TEMPLATE_REPO="."
ANSWERS=""
SUBDIR="template"
KEEP=0

while [ $# -gt 0 ]; do
  case "$1" in
    --template-repo) TEMPLATE_REPO="$2"; shift 2 ;;
    --answers) ANSWERS="$2"; shift 2 ;;
    --subdir) SUBDIR="$2"; shift 2 ;;
    --keep) KEEP=1; shift ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

command -v copier >/dev/null 2>&1 || { echo "copier not on PATH" >&2; exit 2; }
command -v git >/dev/null 2>&1 || { echo "git not on PATH" >&2; exit 2; }

TEMPLATE_REPO="$(cd "$TEMPLATE_REPO" && pwd)"
[ -f "$TEMPLATE_REPO/copier.yml" ] || [ -f "$TEMPLATE_REPO/copier.yaml" ] || {
  echo "[verify_update] no copier.yml under $TEMPLATE_REPO -> skip (base template not landed)"
  exit 0
}

WORK="$(mktemp -d)"
cleanup() { [ "$KEEP" -eq 1 ] || rm -rf "$WORK"; }
trap cleanup EXIT
[ "$KEEP" -eq 1 ] && echo "[verify_update] scratch dir: $WORK"

TPL="$WORK/template"
PRJ="$WORK/project"
# PEP 440 valid tags in a throwaway scratch clone; never touch the real repo.
BASE_TAG="v9000.0.0"
NEXT_TAG="v9000.0.1"

# --- 1. scratch template repo -------------------------------------------------
mkdir -p "$TPL"
# copy tracked + untracked working tree, excluding VCS and scratch noise
tar -C "$TEMPLATE_REPO" \
    --exclude='./.git' --exclude='./.venv' --exclude='./node_modules' \
    --exclude='./.determinism-out' --exclude='./.update-verify-out' \
    -cf - . | tar -C "$TPL" -xf -

git -C "$TPL" init -q
git -C "$TPL" config user.email verify@example.com
git -C "$TPL" config user.name "update-verify"
git -C "$TPL" add -A
git -C "$TPL" commit -q -m "base template"
git -C "$TPL" tag -a "$BASE_TAG" -m "$BASE_TAG"

# --- 2. generate project at vBASE ------------------------------------------------
GEN_ARGS=(copier copy --force --vcs-ref "$BASE_TAG")
if [ -n "$ANSWERS" ]; then
  ANSWERS="$(cd "$(dirname "$ANSWERS")" && pwd)/$(basename "$ANSWERS")"
  GEN_ARGS+=(--data-file "$ANSWERS")
else
  GEN_ARGS+=(--defaults)
fi
GEN_ARGS+=("$TPL" "$PRJ")
"${GEN_ARGS[@]}"

git -C "$PRJ" init -q
git -C "$PRJ" config user.email verify@example.com
git -C "$PRJ" config user.name "update-verify"
git -C "$PRJ" add -A
git -C "$PRJ" commit -q -m "generated at $BASE_TAG"

# --- 3. trivial template change + vNEXT ---------------------------------------
CANARY="$TPL/$SUBDIR/.update_canary.jinja"
mkdir -p "$(dirname "$CANARY")"
printf 'update canary: {{ service_name | default("svc") }} v0.0.1\n' > "$CANARY"
git -C "$TPL" add -A
git -C "$TPL" commit -q -m "trivial change: add update canary"
git -C "$TPL" tag -a "$NEXT_TAG" -m "$NEXT_TAG"

# --- 4. copier update ---------------------------------------------------------
# copier update: -f/--defaults (no --force switch); --trust allows list-form
# _tasks / migrations the real template will carry; --conflict rej makes an
# unclean apply show up as .rej files rather than inline markers.
set +e
UPDATE_OUT="$(cd "$PRJ" && copier update --defaults --trust --conflict rej --vcs-ref "$NEXT_TAG" 2>&1)"
UPDATE_RC=$?
set -e
echo "$UPDATE_OUT"
if [ $UPDATE_RC -ne 0 ]; then
  echo "[verify_update] FAIL: copier update exited $UPDATE_RC" >&2
  exit 1
fi

# --- 5. assert clean apply --------------------------------------------------------
FAIL=0
if grep -RIlZ -e '^<<<<<<< ' -e '^>>>>>>> ' -e '^=======$' "$PRJ" \
     --exclude-dir=.git 2>/dev/null | grep -qz .; then
  echo "[verify_update] FAIL: conflict markers present:" >&2
  grep -RIl -e '^<<<<<<< ' -e '^>>>>>>> ' "$PRJ" --exclude-dir=.git >&2 || true
  FAIL=1
fi
if find "$PRJ" -path "$PRJ/.git" -prune -o -name '*.rej' -print | grep -q .; then
  echo "[verify_update] FAIL: .rej files present:" >&2
  find "$PRJ" -path "$PRJ/.git" -prune -o -name '*.rej' -print >&2
  FAIL=1
fi
if [ ! -e "$PRJ/.update_canary" ]; then
  echo "[verify_update] FAIL: canary file was not applied by update" >&2
  FAIL=1
fi
[ $FAIL -eq 0 ] && echo "[verify_update] update applied cleanly (no conflicts, canary present)"

# --- 6. run the generated project's tests if it has any ----------------------
if [ -f "$PRJ/pyproject.toml" ] && { [ -d "$PRJ/tests" ] || ls "$PRJ"/test_*.py >/dev/null 2>&1; }; then
  echo "[verify_update] running generated project tests"
  set +e
  if command -v uv >/dev/null 2>&1; then
    (cd "$PRJ" && uv sync --quiet && uv run pytest -q)
  else
    (cd "$PRJ" && python -m pytest -q)
  fi
  TEST_RC=$?
  set -e
  if [ $TEST_RC -ne 0 ]; then
    echo "[verify_update] FAIL: generated project tests failed ($TEST_RC)" >&2
    FAIL=1
  else
    echo "[verify_update] generated project tests passed"
  fi
else
  echo "[verify_update] no test suite in generated project yet -> skipping pytest step"
fi

exit $FAIL

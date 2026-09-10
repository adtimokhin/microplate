#!/usr/bin/env bash
# verify_update.sh - prove `copier update` / `msvc-gen update` applies cleanly
# after a trivial template change.
#
# Phase 5 milestone 10 gate. Steps:
#   1. Copy the template repo into a scratch dir, git init, commit, tag vBASE.
#   2. Generate a project from vBASE into a scratch dir; git init + commit it.
#   3. Make a trivial template change (add one canary file), commit, tag vNEXT.
#   4. Run the update (`copier update` for a single service, `msvc-gen update`
#      for a monorepo / multi_repo project) against vNEXT.
#   5. Assert: update exit 0, no conflict markers, no .rej files, canary applied.
#   6. If the generated project has a test suite, run it and assert it passes.
#
# Single-service vs multi-service is chosen from the answers file: a `topology:`
# value of `monorepo` or `multi_repo` switches to the `msvc-gen` orchestration
# path (N per-service `copier update` runs in frozen `service_names` order plus a
# wholesale root-layer re-render, D-036); anything else uses raw `copier update`.
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
    -h|--help) sed -n '2,33p' "$0"; exit 0 ;;
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

# --- resolve the answers file + read its topology --------------------------------
TOPOLOGY="single"
if [ -n "$ANSWERS" ]; then
  ANSWERS="$(cd "$(dirname "$ANSWERS")" && pwd)/$(basename "$ANSWERS")"
  [ -f "$ANSWERS" ] || { echo "answers file not found: $ANSWERS" >&2; exit 2; }
  T="$(sed -n 's/^topology:[[:space:]]*//p' "$ANSWERS" | head -1 | tr -d '"'\'' ' )"
  [ -n "$T" ] && TOPOLOGY="$T"
fi

MULTI=0
case "$TOPOLOGY" in
  monorepo|multi_repo)
    MULTI=1
    command -v msvc-gen >/dev/null 2>&1 || command -v python >/dev/null 2>&1 || {
      echo "[verify_update] topology=$TOPOLOGY needs msvc-gen (or python -m msvc_gen.cli) on PATH" >&2
      exit 2
    }
    ;;
esac

command -v uv >/dev/null 2>&1 || echo "[verify_update] note: uv not on PATH, pytest step will fall back to 'python -m pytest'"

# `pwd -P` resolves symlinks: on macOS `mktemp -d` hands back /var/folders/... which
# is a symlink to /private/var/folders/... . `git rev-parse --show-toplevel` (used
# by `copier update`) always reports the physical path, so an unresolved scratch
# dir makes Copier's `local_abspath.relative_to(git_toplevel)` blow up for a
# project rendered into a subdirectory (the monorepo services/<svc>/ case).
WORK="$(cd "$(mktemp -d)" && pwd -P)"
cleanup() { [ "$KEEP" -eq 1 ] || rm -rf "$WORK"; }
trap cleanup EXIT
[ "$KEEP" -eq 1 ] && echo "[verify_update] scratch dir: $WORK"

TPL="$WORK/template"
PRJ="$WORK/project"
# PEP 440 valid tags in a throwaway scratch clone; never touch the real repo.
BASE_TAG="v9000.0.0"
NEXT_TAG="v9000.0.1"

msvc_gen() {
  if command -v msvc-gen >/dev/null 2>&1; then
    msvc-gen "$@"
  else
    python -m msvc_gen.cli "$@"
  fi
}

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
# --trust / unsafe: template ships list-form _tasks (D-012). --skip-tasks: the
# copy-time `uv lock` task reads the live index and needs no network here.
if [ "$MULTI" -eq 1 ]; then
  # msvc-gen resolves the template from a source checkout by default; force the
  # scratch clone and the vBASE tag explicitly (D-012).
  msvc_gen new --output "$PRJ" --answers-file "$ANSWERS" \
    --template-src "$TPL" --vcs-ref "$BASE_TAG" --skip-tasks --force
else
  GEN_ARGS=(copier copy --force --trust --skip-tasks --vcs-ref "$BASE_TAG")
  if [ -n "$ANSWERS" ]; then
    GEN_ARGS+=(--data-file "$ANSWERS")
  else
    GEN_ARGS+=(--defaults)
  fi
  GEN_ARGS+=("$TPL" "$PRJ")
  "${GEN_ARGS[@]}"
fi

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

# --- 4. update -------------------------------------------------------------------
# --conflict rej makes an unclean apply show up as .rej files rather than inline
# markers; --skip-tasks since the template's _tasks are copy-only anyway.
set +e
if [ "$MULTI" -eq 1 ]; then
  # msvc-gen update reads topology + roster from the root .copier-answers.yml
  # manifest; each services/<svc>/ carries its own answers file and _src_path.
  UPDATE_OUT="$(msvc_gen update --output "$PRJ" --vcs-ref "$NEXT_TAG" \
      --skip-tasks --conflict rej 2>&1)"
  UPDATE_RC=$?
else
  UPDATE_OUT="$(cd "$PRJ" && copier update --defaults --trust --skip-tasks \
      --conflict rej --vcs-ref "$NEXT_TAG" 2>&1)"
  UPDATE_RC=$?
fi
set -e
echo "$UPDATE_OUT"
if [ $UPDATE_RC -ne 0 ]; then
  echo "[verify_update] FAIL: update exited $UPDATE_RC" >&2
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

# The canary lands in every generated service tree. For a single-service project
# that is $PRJ/.update_canary; for a multi-service project it is one per service
# directory (discovered by the per-service .copier-answers.yml).
CANARY_HITS=0
CANARY_MISS=0
if [ "$MULTI" -eq 1 ]; then
  while IFS= read -r ANSFILE; do
    SVC_DIR="$(dirname "$ANSFILE")"
    [ "$SVC_DIR" = "$PRJ" ] && continue   # the root manifest, not a service
    if [ -e "$SVC_DIR/.update_canary" ]; then
      CANARY_HITS=$((CANARY_HITS + 1))
    else
      CANARY_MISS=$((CANARY_MISS + 1))
      echo "[verify_update] FAIL: canary missing in $SVC_DIR" >&2
    fi
  done < <(find "$PRJ" -path "$PRJ/.git" -prune -o -name '.copier-answers.yml' -print)
  [ "$CANARY_HITS" -ge 1 ] || { echo "[verify_update] FAIL: no service picked up the canary" >&2; FAIL=1; }
  [ "$CANARY_MISS" -eq 0 ] || FAIL=1
else
  if [ ! -e "$PRJ/.update_canary" ]; then
    echo "[verify_update] FAIL: canary file was not applied by update" >&2
    FAIL=1
  fi
fi
[ $FAIL -eq 0 ] && echo "[verify_update] update applied cleanly (no conflicts, canary present)"

# --- 6. run the generated project's tests if it has any ----------------------
run_pytest_in() {
  local dir="$1"
  ( cd "$dir" || return 1
    if command -v uv >/dev/null 2>&1; then
      uv sync --quiet && uv run pytest -q
    else
      python -m pytest -q
    fi )
}

if [ "$MULTI" -eq 1 ]; then
  while IFS= read -r ANSFILE; do
    SVC_DIR="$(dirname "$ANSFILE")"
    [ "$SVC_DIR" = "$PRJ" ] && continue
    [ -f "$SVC_DIR/pyproject.toml" ] || continue
    echo "[verify_update] running tests in $SVC_DIR"
    set +e; run_pytest_in "$SVC_DIR"; TEST_RC=$?; set -e
    if [ $TEST_RC -ne 0 ]; then
      echo "[verify_update] FAIL: tests failed in $SVC_DIR ($TEST_RC)" >&2
      FAIL=1
    else
      echo "[verify_update] tests passed in $SVC_DIR"
    fi
  done < <(find "$PRJ" -path "$PRJ/.git" -prune -o -name '.copier-answers.yml' -print)
elif [ -f "$PRJ/pyproject.toml" ] && { [ -d "$PRJ/tests" ] || ls "$PRJ"/test_*.py >/dev/null 2>&1; }; then
  echo "[verify_update] running generated project tests"
  set +e; run_pytest_in "$PRJ"; TEST_RC=$?; set -e
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

#!/usr/bin/env python3
"""Render a Copier template twice from the same answers and assert byte-identical output.

This is the determinism gate from the DevOps working agreement: CI must catch
non-determinism. For each answers file in ``--answers-dir`` it runs
``copier copy`` twice into separate temp dirs and compares the two trees.

Usage:
    check_determinism.py --template . --answers-dir ci/answers
    check_determinism.py --template tests/fixtures/determinism_fixture \\
        --answers-dir tests/fixtures/determinism_fixture/answers

If ``--template`` has no ``copier.yml`` yet (base template not landed), the script
exits 0 with a skip notice unless ``--strict`` is passed.

Comparison ignores ``.git/`` and the Copier answers file (it records a timestamp-
free ``_commit`` but path normalisation keeps this robust). Any other byte
difference fails the run.
"""

from __future__ import annotations

import argparse
import filecmp
import hashlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

IGNORE_DIRS = {".git"}


def _run_copier(template: Path, answers: Path, dest: Path, vcs_ref: str | None) -> None:
    cmd = [
        "copier",
        "copy",
        "--force",
        # --trust: the template legitimately declares list-form `_tasks` (D-012),
        # which Copier classifies as an "unsafe" feature; without --trust Copier
        # exits 4 without rendering.
        # --skip-tasks: the one sanctioned non-deterministic step is the post-copy
        # `uv lock` task (overlay-contract §4.4a); it reads the live index, so its
        # `uv.lock` output can differ between runs. The RENDER is deterministic,
        # which is what this check proves, so tasks are skipped.
        # --defaults: keep the run non-interactive (answers files are complete;
        # this only stops a hang if one is ever missing an answer).
        "--trust",
        "--skip-tasks",
        "--defaults",
        "--data-file",
        str(answers),
    ]
    if vcs_ref:
        cmd += ["--vcs-ref", vcs_ref]
    cmd += [str(template), str(dest)]
    subprocess.run(cmd, check=True, capture_output=True, text=True)


def _tree_digest(root: Path) -> list[tuple[str, str]]:
    """Sorted list of (relative posix path, sha256) for every file under root."""
    entries: list[tuple[str, str]] = []
    for path in sorted(root.rglob("*")):
        if any(part in IGNORE_DIRS for part in path.relative_to(root).parts):
            continue
        if path.is_file():
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            entries.append((path.relative_to(root).as_posix(), digest))
    return entries


def _diff(a: Path, b: Path) -> list[str]:
    da, db = dict(_tree_digest(a)), dict(_tree_digest(b))
    problems: list[str] = []
    for rel in sorted(set(da) | set(db)):
        if rel not in da:
            problems.append(f"only in run 2: {rel}")
        elif rel not in db:
            problems.append(f"only in run 1: {rel}")
        elif da[rel] != db[rel]:
            problems.append(f"differs: {rel}")
    return problems


def _strip_commit_line(dest: Path) -> None:
    """Drop the `_commit:` line from a rendered `.copier-answers.yml`.

    Only used on the unpinned/dirty-template path. Copier snapshots a dirty
    template into a throwaway commit whose SHA changes on every invocation, so
    `_commit` there is Copier bookkeeping, not a function of template content.
    On the pinned path `_commit` is stable and is compared normally.
    """
    ans = dest / ".copier-answers.yml"
    if not ans.exists():
        return
    kept = [ln for ln in ans.read_text().splitlines(keepends=True) if not ln.startswith("_commit:")]
    ans.write_text("".join(kept))


def check_one(template: Path, answers: Path, vcs_ref: str | None) -> list[str]:
    with tempfile.TemporaryDirectory() as tmp:
        d1, d2 = Path(tmp) / "run1", Path(tmp) / "run2"
        _run_copier(template, answers, d1, vcs_ref)
        _run_copier(template, answers, d2, vcs_ref)
        if vcs_ref is None:
            _strip_commit_line(d1)
            _strip_commit_line(d2)
        problems = _diff(d1, d2)
        # filecmp cross-check for good measure
        if not problems:
            cmp = filecmp.dircmp(d1, d2, ignore=list(IGNORE_DIRS))
            if cmp.diff_files or cmp.left_only or cmp.right_only:
                problems.append(
                    f"filecmp mismatch: {cmp.diff_files} {cmp.left_only} {cmp.right_only}"
                )
        return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, default=Path("."))
    parser.add_argument("--answers-dir", type=Path, default=Path("ci/answers"))
    parser.add_argument("--vcs-ref", default=None, help="Template ref (D-012: always pin in prod)")
    parser.add_argument(
        "--strict", action="store_true", help="Fail instead of skip when no copier.yml"
    )
    args = parser.parse_args(argv)

    if shutil.which("copier") is None:
        print("[determinism] copier not on PATH", file=sys.stderr)
        return 2

    if not (args.template / "copier.yml").exists():
        msg = f"[determinism] no copier.yml under {args.template}; base template not landed yet"
        if args.strict:
            print(msg, file=sys.stderr)
            return 1
        print(msg + " -> skip")
        return 0

    answers_files = sorted(args.answers_dir.glob("*.yml")) + sorted(args.answers_dir.glob("*.yaml"))
    if not answers_files:
        print(f"[determinism] no answers files in {args.answers_dir}", file=sys.stderr)
        return 1

    # A determinism check is only meaningful at a fixed template ref (D-012).
    # When the template dir is its own git repo, no --vcs-ref was given, and
    # `copier.yml` is committed at HEAD, pin BOTH renders to that one commit
    # (resolved once here) so `.copier-answers.yml`'s `_commit` field cannot drift
    # if something else commits to the repo between the two renders.
    # If `copier.yml` is only in the working tree (not yet committed), pinning
    # would make Copier miss it, so fall back to an unpinned worktree render.
    vcs_ref = args.vcs_ref
    if vcs_ref is None and (args.template / ".git").exists():
        tracked = subprocess.run(
            ["git", "-C", str(args.template), "ls-files", "--error-unmatch", "copier.yml"],
            capture_output=True,
            text=True,
        )
        if tracked.returncode == 0:
            head = subprocess.run(
                ["git", "-C", str(args.template), "rev-parse", "HEAD"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            vcs_ref = head
            print(f"[determinism] pinning both renders to {args.template}@{head[:12]}")
        else:
            print(
                "[determinism] copier.yml is not committed at HEAD; rendering from the "
                "working tree unpinned (a concurrent commit can make _commit differ)"
            )

    failed = False
    for answers in answers_files:
        problems = check_one(args.template, answers, vcs_ref)
        if problems:
            failed = True
            print(f"[determinism] FAIL {answers.name}:", file=sys.stderr)
            for p in problems:
                print(f"    {p}", file=sys.stderr)
        else:
            print(f"[determinism] ok   {answers.name}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

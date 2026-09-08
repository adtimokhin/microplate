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


def check_one(template: Path, answers: Path, vcs_ref: str | None) -> list[str]:
    with tempfile.TemporaryDirectory() as tmp:
        d1, d2 = Path(tmp) / "run1", Path(tmp) / "run2"
        _run_copier(template, answers, d1, vcs_ref)
        _run_copier(template, answers, d2, vcs_ref)
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

    failed = False
    for answers in answers_files:
        problems = check_one(args.template, answers, args.vcs_ref)
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

#!/usr/bin/env python3
"""Derive ``copier.yml`` from ``registry.yaml``.

STATUS: NOT IMPLEMENTED. Interface is specified in
``docs/registry-schema.md`` §6. Owner: Registry & Copier Architect (Phase 5,
scope milestone 9 / non-interactive mode work, but needed earlier by the CI
sync check).

This stub exists so:
  * the path is stable and referenced by CI now
  * ``ruff``/``mypy`` have something to check
  * the CI "copier.yml sync" job can call it and be a clean skip until it is real

Contract (from registry-schema.md §6):
  input:  registry.yaml (path arg, default repo root)
  output: copier.yml at repo root, byte-deterministic for a given registry.yaml
  guarantees: no network, no randomness, stable key ordering, idempotent
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

NOT_IMPLEMENTED_EXIT = 3


def build_copier_yml(registry_path: Path) -> str:  # noqa: ARG001  (stub)
    """Return the ``copier.yml`` text derived from ``registry.yaml``.

    TODO(RegistryArchitect, milestone 9): implement per registry-schema.md §6.
    """
    raise NotImplementedError(
        "gen_copier_yml.py is not implemented yet. See docs/registry-schema.md 6."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "registry",
        nargs="?",
        default="registry.yaml",
        type=Path,
        help="Path to registry.yaml (default: ./registry.yaml)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Compare generated output against copier.yml on disk; exit 1 on drift.",
    )
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="Exit 0 (skip) instead of erroring while this script is a stub.",
    )
    args = parser.parse_args(argv)

    try:
        rendered = build_copier_yml(args.registry)
    except NotImplementedError as exc:
        if args.allow_missing:
            print(f"[gen_copier_yml] skip: {exc}")
            return 0
        print(f"[gen_copier_yml] {exc}", file=sys.stderr)
        return NOT_IMPLEMENTED_EXIT

    target = Path("copier.yml")
    if args.check:
        current = target.read_text() if target.exists() else ""
        if current != rendered:
            print("[gen_copier_yml] copier.yml is out of sync with registry.yaml", file=sys.stderr)
            return 1
        print("[gen_copier_yml] copier.yml is in sync")
        return 0

    target.write_text(rendered)
    print(f"[gen_copier_yml] wrote {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

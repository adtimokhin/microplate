#!/usr/bin/env python3
"""Lint ``registry.yaml`` against the schema in ``docs/registry-schema.md``.

STATUS: PARTIAL. Owner: Registry & Copier Architect (full implementation,
registry-schema.md §6). DevOps ships a thin set of structural checks now so the
CI step is real rather than a placeholder; the Registry Architect extends this
with the full rule set (renamed-value detection vs previous tag, requires/conflicts
expr key resolution, default type-matching, etc.).

Implemented today:
  * file parses as YAML
  * required top-level sections present
  * every overlay_order id has an options entry whose overlay_id matches
  * overlay_order has no duplicates
  * every option's map key equals its `key` field
  * every option `group` refers to a defined group
  * python_deps versions are exact pins (no range operators)

TODO(RegistryArchitect): full §6 rule set.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover
    print("PyYAML is required: `uv sync` or `pip install pyyaml`", file=sys.stderr)
    raise SystemExit(2) from None

REQUIRED_SECTIONS = ("meta", "overlay_order", "groups", "options")
RANGE_TOKENS = ("^", "~", ">=", "<=", ">", "<", "*", ",", "!=")


def _load(path: Path) -> dict[str, Any]:
    with path.open() as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError("registry.yaml top level must be a mapping")
    return data


def validate(path: Path) -> list[str]:
    problems: list[str] = []
    try:
        reg = _load(path)
    except (yaml.YAMLError, ValueError) as exc:
        return [f"parse error: {exc}"]

    for section in REQUIRED_SECTIONS:
        if section not in reg:
            problems.append(f"missing top-level section: {section}")
    if problems:
        return problems

    groups = reg.get("groups") or {}
    options = reg.get("options") or {}
    overlay_order = reg.get("overlay_order") or []

    if len(overlay_order) != len(set(overlay_order)):
        problems.append("overlay_order contains duplicate ids")

    overlay_ids = {
        opt.get("overlay_id")
        for opt in options.values()
        if isinstance(opt, dict) and opt.get("overlay_id")
    }
    # overlay_order ids may also be multiselect-derived (e.g. transport_grpc);
    # accept an id if any option declares it OR names it in template_paths/derived ids.
    derived_ok = overlay_ids | _multiselect_derived_ids(options)
    for oid in overlay_order:
        if oid not in derived_ok:
            problems.append(f"overlay_order id has no matching option/overlay_id: {oid}")

    for key, opt in options.items():
        if not isinstance(opt, dict):
            problems.append(f"option {key!r} is not a mapping")
            continue
        if opt.get("key") != key:
            problems.append(f"option {key!r} has mismatched 'key' field: {opt.get('key')!r}")
        grp = opt.get("group")
        if grp is not None and grp not in groups:
            problems.append(f"option {key!r} references undefined group {grp!r}")
        for pkg, spec in (opt.get("python_deps") or {}).items():
            version = spec.get("version") if isinstance(spec, dict) else spec
            if not isinstance(version, str) or any(t in version for t in RANGE_TOKENS):
                problems.append(f"option {key!r} dep {pkg!r} is not an exact pin: {version!r}")
            if isinstance(spec, dict) and not spec.get("as_of"):
                problems.append(f"option {key!r} dep {pkg!r} missing as_of date")

    return problems


def _multiselect_derived_ids(options: dict[str, Any]) -> set[str]:
    derived: set[str] = set()
    for opt in options.values():
        if not isinstance(opt, dict) or not opt.get("multiselect"):
            continue
        key = opt.get("key")
        choices = opt.get("choices") or []
        values = choices.values() if isinstance(choices, dict) else choices
        for val in values:
            derived.add(f"{key}_{val}")
    return derived


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("registry", nargs="?", default="registry.yaml", type=Path)
    args = parser.parse_args(argv)

    if not args.registry.exists():
        print(f"[validate_registry] not found: {args.registry}", file=sys.stderr)
        return 2

    problems = validate(args.registry)
    if problems:
        print(f"[validate_registry] {len(problems)} problem(s):", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print("[validate_registry] ok (structural checks only; full rule set is TODO)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

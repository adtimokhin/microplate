# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml==6.0.2"]
# ///
"""Fixture registry: the overlay -> pytest-fixtures map, built FROM `registry.yaml`.

This module does not duplicate the registry. It reads every overlay's `fixtures`
block and exposes:

  * `fixture_map(reg)` -> {overlay_id: [FixtureSpec, ...]}
  * `conftest_fragment_path(overlay_id)` -> the `_fragments/<id>/conftest.py.jinja`
    path that overlay must ship (overlay-contract section 4.3)
  * `lint(reg)` -> contract violations the Data / Messaging / AI engineers must
    fix before their conftest fragment is accepted.

The contract each `_fragments/<id>/conftest.py.jinja` must satisfy
(overlay-contract section 4.3 and section 7, restated in `docs/fixture-registry.md`):

  1. Fixture names are namespaced `<area>_<thing>` (for example `postgres_session`,
     `redis_client`, `rabbitmq_channel`) and are globally unique. The base
     conftest `{% include %}`s every selected overlay's fragment into one file,
     so two overlays must never define the same fixture name.
  2. A mock fixture is ALWAYS provided, so the proves-it-boots test and unit
     tests run with no container (overlay-contract section 7, mock mode).
  3. A container fixture is provided ONLY for an overlay that has a backing
     service (a `compose_services` entry) and is used only when `tests_integration`
     is selected. It must not be collected or built when `tests_integration` is
     false.
  4. No collection-time side effects: fixture bodies may open sockets / spawn
     containers, module top-level may not. Importing the conftest must be free.

Run it:
    uv run harness/fixture_registry.py            # print the map + lint
    uv run harness/fixture_registry.py --lint     # lint only, non-zero on error
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from registry_model import Registry, load_registry  # noqa: E402

DEFAULT_REGISTRY = Path(__file__).resolve().parent.parent / "registry.yaml"
FRAGMENTS_ROOT = "template/_fragments"

_SNAKE = re.compile(r"^[a-z][a-z0-9_]*$")


@dataclasses.dataclass(frozen=True)
class FixtureSpec:
    overlay_id: str
    name: str
    kind: str  # "mock" | "container"
    fragment: str  # conftest fragment path this fixture must live in


def conftest_fragment_path(overlay_id: str) -> str:
    return f"{FRAGMENTS_ROOT}/{overlay_id}/conftest.py.jinja"


def _overlay_specs(reg: Registry) -> list[dict[str, Any]]:
    out = []
    for spec in reg.options.values():
        if spec.get("overlay_id") and spec.get("gate"):
            out.append(spec)
    return out


def fixture_map(reg: Registry) -> dict[str, list[FixtureSpec]]:
    """overlay_id -> list of FixtureSpec, in `overlay_order` then declared order."""
    order = {oid: i for i, oid in enumerate(reg.overlay_order)}
    result: dict[str, list[FixtureSpec]] = {}
    for spec in _overlay_specs(reg):
        oid = spec["overlay_id"]
        fixtures = spec.get("fixtures") or []
        result[oid] = [
            FixtureSpec(oid, f["name"], f.get("kind", "mock"), conftest_fragment_path(oid))
            for f in fixtures
        ]
    return dict(sorted(result.items(), key=lambda kv: order.get(kv[0], 999)))


def _has_compose_service(spec: dict[str, Any]) -> bool:
    return bool(spec.get("compose_services"))


def lint(reg: Registry) -> list[str]:
    """Back-compat: all issues as a flat list. Prefer `lint_split`."""
    errors, warnings = lint_split(reg)
    return errors + warnings


def lint_split(reg: Registry) -> tuple[list[str], list[str]]:
    """(errors, warnings). An issue on an `implemented` overlay is an error (the
    contract gates marking it implemented); the same issue on a `planned` overlay
    is a warning until that overlay is built.
    """
    errors: list[str] = []
    warnings: list[str] = []
    seen: dict[str, str] = {}  # fixture name -> overlay that first declared it

    for spec in _overlay_specs(reg):
        oid = spec["overlay_id"]
        bucket = errors if spec.get("build_status") == "implemented" else warnings
        problems: list[str] = []
        fixtures = spec.get("fixtures") or []
        kinds = [f.get("kind", "mock") for f in fixtures]

        if not fixtures:
            problems.append(f"{oid}: declares no fixtures (need at least one mock)")
        if "mock" not in kinds:
            problems.append(f"{oid}: no `mock` fixture (rule 2: a mock fixture is always provided)")
        if "container" in kinds and not _has_compose_service(spec):
            problems.append(
                f"{oid}: has a `container` fixture but no `compose_services` "
                f"(rule 3: container fixtures need a backing service)"
            )
        if _has_compose_service(spec) and "container" not in kinds:
            problems.append(
                f"{oid}: has a compose service but no `container` fixture for the "
                f"tests_integration tier (rule 3)"
            )

        for f in fixtures:
            name = f["name"]
            if not _SNAKE.match(name):
                problems.append(f"{oid}: fixture name {name!r} is not lower_snake_case")
            if name in seen and seen[name] != oid:
                # A collision breaks conftest assembly regardless of build_status.
                errors.append(
                    f"fixture name collision: {name!r} declared by both {seen[name]} and {oid} "
                    f"(rule 1: names must be globally unique for conftest assembly)"
                )
            seen.setdefault(name, oid)
            kind = f.get("kind", "mock")
            if kind not in ("mock", "container"):
                problems.append(f"{oid}: fixture {name!r} has unknown kind {kind!r}")

        bucket.extend(problems)

    return errors, warnings


def to_json(reg: Registry) -> dict[str, Any]:
    fmap = fixture_map(reg)
    return {
        "registry_sha256": reg.sha256,
        "fragments_root": FRAGMENTS_ROOT,
        "overlays": {
            oid: {
                "conftest_fragment": conftest_fragment_path(oid),
                "boots_test": next(
                    (
                        s.get("boots_test")
                        for s in reg.options.values()
                        if s.get("overlay_id") == oid
                    ),
                    None,
                ),
                "fixtures": [{"name": f.name, "kind": f.kind} for f in specs],
            }
            for oid, specs in fmap.items()
        },
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    p.add_argument("--lint", action="store_true", help="lint only; exit non-zero on any violation")
    args = p.parse_args(argv)

    reg = load_registry(args.registry)
    errors, warnings = lint_split(reg)

    if not args.lint:
        print(json.dumps(to_json(reg), indent=2, sort_keys=True))
        print()

    if warnings:
        print(
            f"[fixture-registry] {len(warnings)} warning(s) on planned overlays:", file=sys.stderr
        )
        for w in warnings:
            print(f"  - {w}", file=sys.stderr)
    if errors:
        print(
            f"[fixture-registry] {len(errors)} contract violation(s) on implemented overlays:",
            file=sys.stderr,
        )
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print("[fixture-registry] ok: no contract violations on implemented overlays")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

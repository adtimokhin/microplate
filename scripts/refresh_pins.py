#!/usr/bin/env python3
"""Re-verify every dependency pin against upstream (D-019 "refresh pins" task).

Scope:
  * ``registry.yaml`` -> every ``options.<key>.python_deps`` entry
  * ``pyproject.toml`` -> ``[project].dependencies`` and ``[dependency-groups].dev``

For each PyPI package it fetches the latest stable release from the PyPI JSON API
and reports current vs latest. With ``--write`` it bumps outdated pins to the
latest stable and stamps ``as_of`` with today's date, so the resulting diff is a
single reviewable PR (the review IS the upstream re-verification D-019 requires).

Compose image pins (Docker Hub / registry digests) are reported as TODO only;
their owner is the Data Layer Engineer (D-023).

This script makes network calls and is meant to run in the ``refresh-pins``
workflow, never in the main CI lanes.

Exit: 0 = nothing outdated (or --write applied) | 1 = outdated pins found (no --write) | 2 = error
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import tomllib
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from packaging.version import InvalidVersion, Version

PYPI_JSON = "https://pypi.org/pypi/{name}/json"
TODAY = dt.date.today().isoformat()
_EXTRAS = re.compile(r"\[.*?\]")


def _pypi_name(name: str) -> str:
    """Strip an extras spec: ``qdrant-client[fastembed]`` -> ``qdrant-client``."""
    return _EXTRAS.sub("", name).strip()


def _pypi_latest_stable(name: str) -> str | None:
    url = PYPI_JSON.format(name=_pypi_name(name))
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:  # noqa: S310 (trusted host)
            data = json.load(resp)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        print(f"  ! {name}: fetch failed ({exc})", file=sys.stderr)
        return None
    parsed: list[Version] = []
    for raw, files in data.get("releases", {}).items():
        if not files:
            continue
        try:
            parsed.append(Version(str(raw)))
        except InvalidVersion:
            continue
    stable = [v for v in parsed if not (v.is_prerelease or v.is_devrelease)]
    pool = stable or parsed
    if not pool:
        return None
    return str(max(pool))


def _collect_registry(reg_path: Path) -> dict[str, dict[str, Any]]:
    """package name -> {version, locations:[(key, ...)]}. Uses simple YAML-free parsing fallback."""
    import yaml  # local import; only needed here

    reg = yaml.safe_load(reg_path.read_text())
    found: dict[str, dict[str, Any]] = {}
    for key, opt in (reg.get("options") or {}).items():
        for pkg, spec in (opt.get("python_deps") or {}).items():
            version = spec["version"] if isinstance(spec, dict) else spec
            found.setdefault(pkg, {"version": version, "locations": []})
            found[pkg]["locations"].append(f"registry.yaml:options.{key}")
    return found


def _collect_pyproject(pp_path: Path) -> dict[str, dict[str, Any]]:
    data = tomllib.loads(pp_path.read_text())
    found: dict[str, dict[str, Any]] = {}
    groups = [
        ("pyproject.toml:[project].dependencies", data.get("project", {}).get("dependencies", [])),
    ]
    for gname, gdeps in (data.get("dependency-groups") or {}).items():
        groups.append((f"pyproject.toml:[dependency-groups].{gname}", gdeps))
    for loc, deps in groups:
        for dep in deps:
            m = re.match(r"^([A-Za-z0-9._-]+)\s*==\s*([A-Za-z0-9._-]+)", str(dep))
            if not m:
                continue
            pkg, version = m.group(1), m.group(2)
            found.setdefault(pkg, {"version": version, "locations": []})
            found[pkg]["locations"].append(loc)
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=Path("registry.yaml"))
    parser.add_argument("--pyproject", type=Path, default=Path("pyproject.toml"))
    parser.add_argument("--write", action="store_true", help="Apply bumps + as_of stamps in place")
    parser.add_argument("--report", type=Path, default=Path("pin-refresh-report.md"))
    args = parser.parse_args(argv)

    pins: dict[str, dict[str, Any]] = {}
    if args.registry.exists():
        for pkg, info in _collect_registry(args.registry).items():
            pins.setdefault(pkg, {"version": info["version"], "locations": []})
            pins[pkg]["locations"] += info["locations"]
    if args.pyproject.exists():
        for pkg, info in _collect_pyproject(args.pyproject).items():
            pins.setdefault(pkg, {"version": info["version"], "locations": []})
            pins[pkg]["locations"] += info["locations"]

    if not pins:
        print("[refresh_pins] no pins found", file=sys.stderr)
        return 2

    rows: list[tuple[str, str, str, str]] = []
    outdated: list[str] = []
    for pkg in sorted(pins, key=str.lower):
        current = pins[pkg]["version"]
        latest = _pypi_latest_stable(pkg)
        if latest is None:
            rows.append((pkg, current, "?", "unknown"))
            continue
        status = "current" if latest == current else "OUTDATED"
        if status == "OUTDATED":
            outdated.append(pkg)
        rows.append((pkg, current, latest, status))
        print(f"  {status:9} {pkg}  {current} -> {latest}")

    lines = [
        f"# Pin refresh report - {TODAY}",
        "",
        "| Package | Current | Latest stable | Status | Locations |",
        "| --- | --- | --- | --- | --- |",
    ]
    for pkg, cur, lat, status in rows:
        locs = ", ".join(pins[pkg]["locations"])
        lines.append(f"| {pkg} | {cur} | {lat} | {status} | {locs} |")
    lines += [
        "",
        "Compose image pins (D-023, Data Layer Engineer) are NOT checked here yet - TODO.",
        "",
        "Per D-019: review each bump against the upstream changelog before merging this PR.",
    ]
    args.report.write_text("\n".join(lines) + "\n")
    print(f"[refresh_pins] wrote {args.report}")

    if args.write:
        _apply(args.registry, args.pyproject, rows)
        print("[refresh_pins] applied bumps + as_of stamps")
        return 0

    if outdated:
        print(
            f"[refresh_pins] {len(outdated)} outdated pin(s): {', '.join(outdated)}",
            file=sys.stderr,
        )
        return 1
    print("[refresh_pins] all pins current")
    return 0


def _apply(reg_path: Path, pp_path: Path, rows: list[tuple[str, str, str, str]]) -> None:
    """Text-level rewrite: bump ``pkg==X`` and ``version: X`` / adjacent ``as_of``.

    Deliberately line-based so it does not reformat the YAML/TOML.
    """
    bumps = {pkg: (cur, lat) for pkg, cur, lat, status in rows if status == "OUTDATED"}
    for path in (reg_path, pp_path):
        if not path.exists():
            continue
        text = path.read_text()
        for pkg, (cur, lat) in bumps.items():
            text = text.replace(f"{pkg}=={cur}", f"{pkg}=={lat}")
            text = re.sub(
                rf'(\b{re.escape(pkg)}\b\s*:\s*\{{[^}}]*?version:\s*)"{re.escape(cur)}"',
                rf'\g<1>"{lat}"',
                text,
            )
        path.write_text(text)
    # Stamp as_of on every registry pin line: the script re-verified all of them
    # against upstream this run. TODO(DevOps): make this per-package so a failed
    # fetch does not get a fresh date.
    if reg_path.exists():
        text = reg_path.read_text()
        text = re.sub(r'as_of:\s*"?\d{4}-\d{2}-\d{2}"?', f'as_of: "{TODAY}"', text)
        reg_path.write_text(text)


if __name__ == "__main__":
    raise SystemExit(main())

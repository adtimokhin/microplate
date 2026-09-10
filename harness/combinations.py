# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml==6.0.2"]
# ///
"""Combination generator for the combinatorial verification harness.

Reads `registry.yaml`, computes the set of valid answers files to test, and
writes them to an output directory with a manifest.

Three modes:

  full       Every valid, distinct combination. The count is computed exactly by
             enumerating the *coupled* axes (those any constraint references) with
             backtracking and multiplying by the product of the *independent*
             axis domains. Answers files are only materialized when the count is
             <= --max-materialize (default 200); otherwise the count is reported
             and you are told to narrow the axis set with --include / --pin or use
             pairwise.

  pairwise   A deterministic greedy 2-wise covering set over every axis, built
             over the constraint components. No RNG. Always materialized.

  singletons The base-only combination plus, for each overlay, the minimal valid
             combination that enables its gate (validity forces its `requires`
             overlays on). The per-overlay Definition of Done from
             docs/boots-test-contract.md. `run.py --mode pairwise` folds this in.

Determinism: axes are processed in a fixed order (registry group order, then key
name); every domain is iterated in registry order; output paths are a sha256 of
the answers content; no `set` iteration reaches an output path or the manifest.

Usage:
    uv run harness/combinations.py full --out .harness-out/full
    uv run harness/combinations.py pairwise --out .harness-out/pairwise
    uv run harness/combinations.py full --include db_postgres,db_redis --out .out/data

See harness/README.md for the algorithm write-up.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import sys
import time
from pathlib import Path
from typing import Any

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from registry_model import (  # noqa: E402
    Axis,
    Registry,
    answers_for,
    axis_components,
    load_registry,
)

GENERATOR_VERSION = "0.1.0"
DEFAULT_REGISTRY = Path(__file__).resolve().parent.parent / "registry.yaml"


# ---------------------------------------------------------------------------
# axis selection


def select_axes(
    reg: Registry, include: list[str] | None, pins: dict[str, Any]
) -> tuple[list[Axis], list[Axis], dict[str, Any]]:
    """Split axes into (coupled, independent) after applying --include / --pin.

    Pinned axes are removed from enumeration and their fixed value is returned
    in `pin_values`. --include keeps only the named axes as variable; everything
    else collapses to its registry default (still recorded in the answers file).
    """
    pin_values: dict[str, Any] = {}
    coupled: list[Axis] = []
    independent: list[Axis] = []

    for axis in reg.axes:
        if axis.key in pins:
            value = pins[axis.key]
            if value not in axis.domain:
                raise SystemExit(
                    f"--pin {axis.key}={value!r} is not in the registry domain {list(axis.domain)}"
                )
            pin_values[axis.key] = value
            continue
        if include is not None and axis.key not in include:
            pin_values[axis.key] = axis.default
            continue
        if len(axis.domain) < 2:
            pin_values[axis.key] = axis.default
            continue
        (coupled if axis.coupled else independent).append(axis)

    return coupled, independent, pin_values


# ---------------------------------------------------------------------------
# full enumeration


class NodeBudgetExceeded(Exception):
    def __init__(self, visited: int) -> None:
        super().__init__(f"node budget exceeded after {visited} nodes")
        self.visited = visited


def _order_by_when_deps(reg: Registry, axes: list[Axis]) -> list[Axis]:
    """Stable order where an axis follows every axis its `when` references.

    `when` expressions only reference axes in the same component, so this is a
    self-contained topological sort. It lets `enumerate_component` prune a
    conditional axis as soon as its parent is decided false.
    """
    import re

    ident = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
    by_key = {a.key: a for a in axes}
    deps: dict[str, set[str]] = {}
    for a in axes:
        refs = set(ident.findall(a.when)) & set(by_key) if a.when else set()
        deps[a.key] = refs - {a.key}

    ordered: list[Axis] = []
    placed: set[str] = set()
    remaining = list(axes)  # keeps the incoming deterministic order as tiebreak
    while remaining:
        progressed = False
        for a in list(remaining):
            if deps[a.key] <= placed:
                ordered.append(a)
                placed.add(a.key)
                remaining.remove(a)
                progressed = True
        if not progressed:  # cycle (should not happen); fall back to input order
            ordered.extend(remaining)
            break
    return ordered


def enumerate_component(
    reg: Registry,
    component: list[Axis],
    pin_values: dict[str, Any],
    max_nodes: int,
) -> tuple[list[dict[str, Any]], bool]:
    """Backtrack over ONE constraint component, returning its distinct valid,
    canonicalized sub-assignments (component keys only).

    Components share no constraints, so a rule / precondition on an option in
    this component depends only on this component's keys plus the constant base
    namespace. Validating against (base defaults + component partial) is exact.

    Returns (assignments, complete); `complete` is False if the node budget was
    hit, so the count is a lower bound.
    """
    import re as _re

    order = _order_by_when_deps(reg, component)
    order_keys = {a.key for a in order}
    dep_keys = {
        a.key: (set(_re.findall(r"[A-Za-z_][A-Za-z0-9_]*", a.when)) & order_keys)
        if a.when
        else set()
        for a in order
    }
    seen: set[tuple[tuple[str, Any], ...]] = set()
    out: list[dict[str, Any]] = []
    visited = 0

    def recurse(idx: int, current: dict[str, Any]) -> None:
        nonlocal visited
        visited += 1
        if visited > max_nodes:
            raise NodeBudgetExceeded(visited)

        if idx == len(order):
            canon = reg.canonicalize({**pin_values, **current})
            if reg.is_valid(canon):
                key = tuple((a.key, canon[a.key]) for a in order)
                if key not in seen:
                    seen.add(key)
                    out.append({a.key: canon[a.key] for a in order})
            return

        axis = order[idx]
        partial = {**pin_values, **current}
        # Prune a conditional axis only when every key its `when` needs is already
        # bound (thanks to `_order_by_when_deps`) and the `when` is false: only the
        # default branch can survive canonicalization.
        if (
            axis.when is not None
            and dep_keys[axis.key] <= set(current)
            and not reg.evaluate(axis.when, partial)
        ):
            recurse(idx + 1, {**current, axis.key: axis.default})
            return

        for value in axis.domain:
            nxt = {**current, axis.key: value}
            if _partial_conflict(reg, {**pin_values, **nxt}):
                continue
            recurse(idx + 1, nxt)

    try:
        recurse(0, {})
        complete = True
    except NodeBudgetExceeded:
        complete = False

    out.sort(key=lambda d: json.dumps(d, sort_keys=True))
    return out, complete


def _partial_conflict(reg: Registry, partial: dict[str, Any]) -> bool:
    """Cheap early prune: a validation rule is already violated when every key it
    needs is bound. Uses the base namespace for unbound keys, so only fires when
    the bound keys alone are enough to decide the rule.
    """
    bound = set(partial)
    for rule in reg.validation_rules:
        needed = _rule_keys(rule)
        if not needed <= bound:
            continue
        applies = rule.get("applies_when", "True")
        if reg.evaluate(applies, partial) and not reg.evaluate(rule["expr"], partial):
            return True
    return False


_RULE_KEY_CACHE: dict[str, set[str]] = {}


def _rule_keys(rule: dict[str, Any]) -> set[str]:
    cache_key = rule["id"]
    if cache_key not in _RULE_KEY_CACHE:
        import re

        ident = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
        kw = {"and", "or", "not", "in", "is", "True", "False", "None"}
        texts = [rule.get("applies_when", "True"), rule["expr"]]
        _RULE_KEY_CACHE[cache_key] = {m for t in texts for m in ident.findall(t) if m not in kw}
    return _RULE_KEY_CACHE[cache_key]


def run_full(
    reg: Registry,
    coupled: list[Axis],
    independent: list[Axis],
    pin_values: dict[str, Any],
    max_nodes: int,
    max_materialize: int,
) -> dict[str, Any]:
    t0 = time.monotonic()

    components = axis_components(reg, coupled)
    component_results: list[dict[str, Any]] = []
    complete = True
    for comp in components:
        assignments, comp_complete = enumerate_component(reg, comp, pin_values, max_nodes)
        complete = complete and comp_complete
        component_results.append(
            {
                "axes": [a.key for a in comp],
                "valid_count": len(assignments),
                "_assignments": assignments,
            }
        )

    indep_factor = 1
    for axis in independent:
        indep_factor *= len(axis.domain)

    coupled_count = 1
    for cr in component_results:
        coupled_count *= cr["valid_count"]

    full_count = coupled_count * indep_factor
    elapsed = time.monotonic() - t0

    result: dict[str, Any] = {
        "mode": "full",
        "algorithm": "per-component backtracking, product across components and independent axes",
        "components": [
            {"axes": cr["axes"], "valid_count": cr["valid_count"]} for cr in component_results
        ],
        "independent_axes": {a.key: list(a.domain) for a in independent},
        "coupled_valid_count": coupled_count,
        "independent_factor": indep_factor,
        "full_count": full_count,
        "full_count_is_lower_bound": not complete,
        "node_budget": max_nodes,
        "enumerate_seconds": round(elapsed, 3),
    }

    if complete and full_count <= max_materialize:
        result["materialized"] = True
        result["combinations"] = _expand(component_results, independent, pin_values)
    else:
        result["materialized"] = False
        result["combinations"] = []
    return result


def _expand(
    component_results: list[dict[str, Any]],
    independent: list[Axis],
    pin_values: dict[str, Any],
) -> list[dict[str, Any]]:
    per_component = [cr["_assignments"] for cr in component_results]
    indep_domains = [[(a.key, v) for v in a.domain] for a in independent]

    out: list[dict[str, Any]] = []
    comp_iter = itertools.product(*per_component) if per_component else [()]
    for comp_combo in comp_iter:
        indep_iter = itertools.product(*indep_domains) if indep_domains else [()]
        for indep_combo in indep_iter:
            assignment = dict(pin_values)
            for part in comp_combo:
                assignment.update(part)
            assignment.update(dict(indep_combo))
            out.append(assignment)
    return out


# ---------------------------------------------------------------------------
# singletons
#
# For each overlay: the "overlay alone on the base" combination, and implicitly
# "overlay plus its minimal `requires`" when validity forces other overlays on.
# This is the per-overlay Definition of Done from docs/boots-test-contract.md
# ("must pass with the overlay alone on the base, and with the overlay plus every
# overlay it names in `requires`"). Always included in a `run.py --mode pairwise`
# run so a newly `implemented` overlay actually executes even if the pairwise
# greedy never isolated it.


def run_singletons(
    reg: Registry,
    coupled: list[Axis],
    independent: list[Axis],
    pin_values: dict[str, Any],
    max_nodes: int,
) -> dict[str, Any]:
    components = axis_components(reg, coupled)
    comp_of_key: dict[str, int] = {}
    comp_menu: list[list[dict[str, Any]]] = []
    for ci, comp in enumerate(components):
        subs, complete = enumerate_component(reg, comp, pin_values, max_nodes)
        if not complete:  # pragma: no cover - defensive
            names = [a.key for a in comp]
            raise SystemExit(f"singletons: component {names} over --max-nodes; use --include")
        comp_menu.append(subs)
        for a in comp:
            comp_of_key[a.key] = ci

    def _minimal(subs: list[dict[str, Any]]) -> dict[str, Any]:
        return min(
            subs,
            key=lambda s: (sum(1 for v in s.values() if v is True), json.dumps(s, sort_keys=True)),
        )

    indep_by_key = {a.key: a for a in independent}
    indep_defaults = {a.key: a.default for a in independent}
    base_default_by_comp = [_minimal(subs) for subs in comp_menu]

    def base_assignment() -> dict[str, Any]:
        out = dict(pin_values)
        out.update(indep_defaults)
        for sub in base_default_by_comp:
            out.update(sub)
        return out

    combos: list[dict[str, Any]] = [base_assignment()]
    per_overlay: list[dict[str, Any]] = []

    gate_by_id: dict[str, str] = {}
    for spec in reg.options.values():
        oid = spec.get("overlay_id")
        gate = spec.get("gate")
        if oid and isinstance(gate, str):
            gate_by_id[oid] = gate

    for oid in reg.overlay_order:
        gate = gate_by_id.get(oid, oid)
        assignment: dict[str, Any] | None = None

        coupled_hit = next((k for k in comp_of_key if _expr_mentions(gate, k)), None)
        indep_hit = next((k for k in indep_by_key if _expr_mentions(gate, k)), None)

        if coupled_hit is not None:
            ci = comp_of_key[coupled_hit]
            cands = [s for s in comp_menu[ci] if reg.evaluate(gate, {**pin_values, **s})]
            if cands:
                best = _minimal(cands)
                assignment = dict(pin_values)
                assignment.update(indep_defaults)
                for cj, sub in enumerate(base_default_by_comp):
                    assignment.update(best if cj == ci else sub)
        elif indep_hit is not None:
            axis = indep_by_key[indep_hit]
            on = next(
                (v for v in axis.domain if reg.evaluate(gate, {indep_hit: v})),
                None,
            )
            if on is not None:
                assignment = base_assignment()
                assignment[indep_hit] = on

        if assignment is None:
            per_overlay.append({"overlay": oid, "status": "not isolable", "assignment": None})
            continue

        canon = reg.canonicalize(assignment)
        status = "ok" if reg.is_valid(canon) else "invalid after canonicalize"
        combos.append({k: canon[k] for k in assignment})
        per_overlay.append(
            {
                "overlay": oid,
                "status": status,
                "assignment": {k: canon[k] for k in sorted(assignment)},
            }
        )

    # de-duplicate structurally, keep first occurrence order
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for c in combos:
        key = json.dumps(c, sort_keys=True, default=str)
        if key not in seen:
            seen.add(key)
            unique.append(c)

    return {
        "mode": "singletons",
        "algorithm": "base-only plus, per overlay, the minimal valid assignment enabling its gate",
        "overlay_count": len(reg.overlay_order),
        "per_overlay": per_overlay,
        "singleton_count": len(unique),
        "materialized": True,
        "combinations": unique,
    }


def _expr_mentions(expr: str, key: str) -> bool:
    import re

    return re.search(rf"\b{re.escape(key)}\b", expr) is not None


# ---------------------------------------------------------------------------
# pairwise
#
# Deterministic greedy 2-wise covering array, built over constraint COMPONENTS
# rather than single axes. No RNG.
#
#   1. Partition the variable axes into constraint components (axes that share no
#      constraint are independent) and enumerate each component's full set of
#      valid, canonicalized sub-assignments (reuses `enumerate_component`).
#      Independent axes are 1-axis components with one sub-assignment per value.
#   2. A target pair (ka=va, kb=vb) is FEASIBLE iff:
#        - ka, kb in the same component C: some sub-assignment of C has both, or
#        - ka, kb in different components: va is reachable for ka AND vb for kb
#          (cross-component choices never interact, so the product is valid).
#      Feasibility is therefore exact, not a heuristic.
#   3. Greedy build: while feasible pairs are uncovered, seed a case from the
#      first uncovered pair (sorted order), then for each component in order pick
#      the valid sub-assignment (its enumerated order breaks ties) that covers
#      the most still-uncovered pairs and is consistent with the seed. Every case
#      is valid by construction. Mark its pairs covered, repeat.
#
# Terminates: each case covers at least its seed pair.


def _all_pairs(axes: list[Axis]) -> list[tuple[str, Any, str, Any]]:
    out: list[tuple[str, Any, str, Any]] = []
    for i in range(len(axes)):
        for j in range(i + 1, len(axes)):
            for va in axes[i].domain:
                for vb in axes[j].domain:
                    out.append((axes[i].key, va, axes[j].key, vb))
    return out


def _case_pairs(case: dict[str, Any], keys: list[str]) -> set[tuple[str, Any, str, Any]]:
    out: set[tuple[str, Any, str, Any]] = set()
    for i in range(len(keys)):
        for j in range(i + 1, len(keys)):
            out.add((keys[i], case[keys[i]], keys[j], case[keys[j]]))
    return out


def run_pairwise(
    reg: Registry,
    variable_axes: list[Axis],
    pin_values: dict[str, Any],
    max_nodes: int,
) -> dict[str, Any]:
    t0 = time.monotonic()
    axes = variable_axes
    keys = [a.key for a in axes]

    # ---- 1. components and their valid sub-assignments -------------------
    components = axis_components(reg, axes)
    comp_menus: list[list[dict[str, Any]]] = []
    for comp in components:
        subs, comp_complete = enumerate_component(reg, comp, pin_values, max_nodes)
        if not comp_complete:  # pragma: no cover - defensive
            names = [a.key for a in comp]
            raise SystemExit(
                f"pairwise: component {names} exceeded --max-nodes; narrow with --include"
            )
        comp_menus.append(subs)

    comp_of_key: dict[str, int] = {}
    for ci, comp in enumerate(components):
        for a in comp:
            comp_of_key[a.key] = ci

    def reachable(k: str, v: Any) -> bool:
        return any(sub.get(k) == v for sub in comp_menus[comp_of_key[k]])

    # ---- 2. feasible / infeasible target pairs -------------------------
    all_pairs = _all_pairs(axes)
    feasible: list[tuple[str, Any, str, Any]] = []
    infeasible: list[tuple[str, Any, str, Any]] = []
    for pair in all_pairs:
        ka, va, kb, vb = pair
        ca, cb = comp_of_key[ka], comp_of_key[kb]
        if ca == cb:
            ok = any(sub.get(ka) == va and sub.get(kb) == vb for sub in comp_menus[ca])
        else:
            ok = reachable(ka, va) and reachable(kb, vb)
        (feasible if ok else infeasible).append(pair)

    # ---- 3. greedy cover ---------------------------------------------
    uncovered: set[tuple[str, Any, str, Any]] = set(feasible)
    feasible_sorted = sorted(feasible, key=lambda p: (p[0], str(p[1]), p[2], str(p[3])))
    cases: list[dict[str, Any]] = []

    while uncovered:
        seed = next(p for p in feasible_sorted if p in uncovered)
        ska, sva, skb, svb = seed
        seed_vals = {ska: sva, skb: svb}

        case: dict[str, Any] = {}
        for ci, comp in enumerate(components):
            comp_keys = {a.key for a in comp}
            menu = comp_menus[ci]
            if comp_keys & set(seed_vals):
                consistent = [
                    sub
                    for sub in menu
                    if all(sub.get(k) == v for k, v in seed_vals.items() if k in comp_keys)
                ]
                if consistent:
                    menu = consistent

            best_sub = None
            best_score = -1
            for sub in menu:
                trial = {**case, **sub}
                trial_keys = [k for k in keys if k in trial]
                score = sum(1 for p in _case_pairs(trial, trial_keys) if p in uncovered)
                if score > best_score:
                    best_score = score
                    best_sub = sub
            case.update(best_sub)

        cases.append(case)
        for p in _case_pairs(case, keys):
            uncovered.discard(p)

    combos = [dict(pin_values, **c) for c in cases]
    elapsed = time.monotonic() - t0

    return {
        "mode": "pairwise",
        "algorithm": "deterministic greedy 2-wise covering array over components, no RNG",
        "variable_axes": keys,
        "components": [[a.key for a in comp] for comp in components],
        "target_pairs": len(all_pairs),
        "feasible_pairs": len(feasible),
        "infeasible_pair_count": len(infeasible),
        "infeasible_pairs": [
            {"a": f"{ka}={va}", "b": f"{kb}={vb}"}
            for (ka, va, kb, vb) in sorted(
                infeasible, key=lambda p: (p[0], str(p[1]), p[2], str(p[3]))
            )
        ],
        "pairwise_case_count": len(combos),
        "materialized": True,
        "combinations": combos,
        "enumerate_seconds": round(elapsed, 3),
    }


# ---------------------------------------------------------------------------
# output


def _answers_yaml(reg: Registry, assignment: dict[str, Any]) -> str:
    answers = answers_for(reg, assignment)
    return yaml.safe_dump(answers, sort_keys=True, default_flow_style=False)


def write_output(
    reg: Registry,
    out_dir: Path,
    result: dict[str, Any],
    args: argparse.Namespace,
) -> dict[str, Any]:
    out_dir.mkdir(parents=True, exist_ok=True)
    files: list[dict[str, Any]] = []

    for assignment in result.get("combinations", []):
        text = _answers_yaml(reg, assignment)
        digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
        fname = f"{digest}.yml"
        (out_dir / fname).write_text(text)
        files.append(
            {
                "hash": digest,
                "file": fname,
                "selected_overlays": reg.selected_overlays(reg.canonicalize(assignment)),
                "answers": answers_for(reg, assignment),
            }
        )

    files.sort(key=lambda f: f["hash"])

    manifest = {
        "generator_version": GENERATOR_VERSION,
        "registry_path": str(reg.path),
        "registry_sha256": reg.sha256,
        "registry_version": reg.meta.get("registry_version"),
        "params": {
            "mode": args.mode,
            "include": sorted(args.include) if args.include else None,
            "pin": {k: v for k, v in sorted(args.pin.items())} if args.pin else {},
            "max_nodes": getattr(args, "max_nodes", None),
            "max_materialize": getattr(args, "max_materialize", None),
        },
        "summary": {k: v for k, v in result.items() if k != "combinations"},
        "file_count": len(files),
        "files": files,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


# ---------------------------------------------------------------------------
# cli


def _parse_pins(items: list[str]) -> dict[str, Any]:
    pins: dict[str, Any] = {}
    for item in items:
        if "=" not in item:
            raise SystemExit(f"--pin expects key=value, got {item!r}")
        key, _, raw = item.partition("=")
        pins[key.strip()] = _coerce(raw.strip())
    return pins


def _coerce(raw: str) -> Any:
    low = raw.lower()
    if low in ("true", "false"):
        return low == "true"
    if raw.isdigit():
        return int(raw)
    return raw


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("mode", choices=["full", "pairwise", "singletons"])
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument(
        "--out", type=Path, default=None, help="output directory (default: print summary only)"
    )
    parser.add_argument(
        "--include",
        type=lambda s: [x.strip() for x in s.split(",") if x.strip()],
        default=None,
        help="comma-separated axis keys to keep variable; all others pinned to default",
    )
    parser.add_argument("--pin", action="append", default=[], help="key=value, repeatable")
    parser.add_argument(
        "--max-nodes", type=int, default=5_000_000, help="full mode backtracking budget"
    )
    parser.add_argument(
        "--max-materialize",
        type=int,
        default=200,
        help="full mode: write files only at or below this count",
    )
    args = parser.parse_args(argv)
    args.pin = _parse_pins(args.pin)

    reg = load_registry(args.registry)
    coupled, independent, pin_values = select_axes(reg, args.include, args.pin)

    if args.mode == "full":
        result = run_full(
            reg, coupled, independent, pin_values, args.max_nodes, args.max_materialize
        )
    elif args.mode == "singletons":
        result = run_singletons(reg, coupled, independent, pin_values, args.max_nodes)
    else:
        variable = coupled + independent
        variable.sort(key=lambda a: (a.group_order, a.key))
        result = run_pairwise(reg, variable, pin_values, args.max_nodes)

    summary = {k: v for k, v in result.items() if k != "combinations"}
    print(json.dumps(summary, indent=2, sort_keys=True))

    if args.out is not None:
        manifest = write_output(reg, args.out, result, args)
        print(f"\nwrote {manifest['file_count']} answers file(s) to {args.out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

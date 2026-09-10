"""Shared registry model for the combinatorial verification harness.

This module is the single place that reads `registry.yaml` and turns it into:

  * a deterministic list of combination *axes* (the answer keys the harness varies),
  * a boolean-expression evaluator for `when` / `requires` / `conflicts` /
    `validation_rules` strings, exactly as the registry writes them,
  * `canonicalize()` which forces conditional keys to their default when their
    `when` is false (mirrors what Copier stores in `.copier-answers.yml`),
  * `validate()` which returns the list of rule ids an assignment violates.

Nothing here talks to Copier or the network. It is a pure function of
`registry.yaml`. See `harness/README.md` for the algorithm notes and
`docs/registry-schema.md` for the field definitions this parser relies on.

The expression strings in the registry (for example ``"llm_openai or llm_anthropic"``
or ``"topology != 'single' and transport_grpc"``) are a syntactic subset of Python
boolean expressions, so they are evaluated with ``eval`` in a namespace that binds
every option key to its current value and nothing else (``__builtins__`` stripped).
The registry file is a trusted, version-controlled input.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Keys that are computed (`when: false`) and are never a combination axis, never
# written to an answers file, and never read back from one.
#
# Copier 9.18.2 does NOT persist `when: false` values to `.copier-answers.yml` at
# all (verified by BaseTemplateEngineer / RegistryArchitect), so the harness must
# not expect `selected_overlays` / `registry_version` to appear there. The set of
# active overlays is always reconstructed from the recorded gate booleans by
# `Registry.selected_overlays()`, never read from a key.
#
# `selected_overlays` and `registry_version` lost their leading underscore in the
# registry (an `_`-prefixed answer key is stripped by Copier from `_copier_answers`).
COMPUTED_KEYS = {
    "service_slug",
    "python_package",
    "api_rest",
    "healthchecks",
    "selected_overlays",
    "registry_version",
}

# Free-form keys we pin to a fixed canonical value for every generated answers
# file. They do not enumerate.
PINNED_FREEFORM = {
    "service_name": "harness-svc",
    "service_names": ["api"],
    "services_config": {},
}

# `int` axes have no `choices` in the registry, so their candidate domain is
# spelled out here. embedding_vector_size is the only one in v0 (D-014).
INT_AXIS_DOMAINS = {
    "embedding_vector_size": [384, 1536, 3072],
}

# Values bound into every expression namespace regardless of the assignment.
# api_rest and healthchecks are computed `true` in v1 (D-018, scope 4.6).
BASE_NAMESPACE = {
    "api_rest": True,
    "healthchecks": True,
}


@dataclass(frozen=True)
class Axis:
    """One combination dimension derived from an `options` entry."""

    key: str
    group: str
    group_order: int
    type: str
    domain: tuple[Any, ...]
    default: Any
    when: str | None
    coupled: bool  # True if any constraint text references this key

    @property
    def is_independent(self) -> bool:
        return not self.coupled


@dataclass
class Registry:
    path: Path
    raw: dict[str, Any]
    sha256: str

    meta: dict[str, Any]
    overlay_order: list[str]
    groups: dict[str, dict[str, Any]]
    options: dict[str, dict[str, Any]]
    validation_rules: list[dict[str, Any]]
    image_resolution: list[dict[str, Any]]

    axes: list[Axis] = field(default_factory=list)
    _compiled: dict[str, Any] = field(default_factory=dict)
    _base_ns: dict[str, Any] | None = None

    # ---- expression handling ------------------------------------------------

    def base_namespace(self) -> dict[str, Any]:
        """Every option key at its resolved default, plus the computed keys.

        Cached: the defaults never change for a loaded registry.
        """
        if self._base_ns is None:
            ns: dict[str, Any] = dict(BASE_NAMESPACE)
            for key, spec in self.options.items():
                if key in ns or key in COMPUTED_KEYS:
                    # api_rest / healthchecks come from BASE_NAMESPACE; the other
                    # computed keys are Jinja-template defaults, not evaluable
                    # values, and no constraint expression references them.
                    continue
                ns[key] = _resolve_default(key, spec)
            for key, value in PINNED_FREEFORM.items():
                ns[key] = value
            self._base_ns = ns
        return self._base_ns

    def _eval(self, expr: str, assignment: dict[str, Any]) -> bool:
        code = self._compiled.get(expr)
        if code is None:
            code = compile(expr, f"<registry expr: {expr!r}>", "eval")
            self._compiled[expr] = code
        ns = dict(self.base_namespace())
        ns.update(assignment)
        try:
            return bool(eval(code, {"__builtins__": {}}, ns))  # noqa: S307 - trusted input
        except NameError as exc:  # pragma: no cover - registry authoring bug
            raise ValueError(f"expression {expr!r} references an unknown key: {exc}") from exc

    def evaluate(self, expr: str, assignment: dict[str, Any]) -> bool:
        return self._eval(expr, assignment)

    # ---- canonicalization + validation -----------------------------------

    def canonicalize(self, assignment: dict[str, Any]) -> dict[str, Any]:
        """Force every key whose `when` is currently false back to its default.

        Runs to a fixpoint because one conditional key's `when` can depend on
        another conditional key.
        """
        result = dict(assignment)
        for _ in range(10):
            changed = False
            for key, spec in self.options.items():
                when = spec.get("when")
                if not isinstance(when, str):
                    continue
                default = _resolve_default(key, spec)
                if not self._eval(when, result) and result.get(key) != default:
                    result[key] = default
                    changed = True
            if not changed:
                break
        return result

    def _option_active(self, key: str, spec: dict[str, Any], assignment: dict[str, Any]) -> bool:
        """Whether `requires` / `conflicts` on this option should be enforced."""
        gate = spec.get("gate")
        if isinstance(gate, str):
            return self._eval(gate, assignment)
        if spec.get("type") == "bool":
            return bool(assignment.get(key, _resolve_default(key, spec)))
        when = spec.get("when")
        if isinstance(when, str):
            return self._eval(when, assignment)
        return True

    def validate(self, assignment: dict[str, Any]) -> list[str]:
        """Return the ids of every rule / precondition the assignment breaks."""
        violations: list[str] = []

        for rule in self.validation_rules:
            if not _is_copier_rule(rule):
                # services_config-scoped rules (V-15..) carry a prose `expr`
                # that is not a Python boolean; they are checked by
                # validate_registry.py, not the harness. Mirror gen_copier_yml.py.
                continue
            applies = rule.get("applies_when", "True")
            if self._eval(applies, assignment) and not self._eval(rule["expr"], assignment):
                violations.append(rule["id"])

        for key, spec in self.options.items():
            if not self._option_active(key, spec, assignment):
                continue
            for req in spec.get("requires", []) or []:
                if not self._eval(req["expr"], assignment):
                    violations.append(f"requires:{key}:{req['expr']}")
            for conf in spec.get("conflicts", []) or []:
                if self._eval(conf["expr"], assignment):
                    violations.append(f"conflicts:{key}:{conf['expr']}")

        return violations

    def is_valid(self, assignment: dict[str, Any]) -> bool:
        return not self.validate(assignment)

    # ---- overlay helpers -------------------------------------------------

    def selected_overlays(self, assignment: dict[str, Any]) -> list[str]:
        """Overlay ids whose gate is true, in `overlay_order` sequence."""
        gate_by_id: dict[str, str] = {}
        for spec in self.options.values():
            oid = spec.get("overlay_id")
            gate = spec.get("gate")
            if oid and isinstance(gate, str):
                gate_by_id[oid] = gate
        out: list[str] = []
        for oid in self.overlay_order:
            gate = gate_by_id.get(oid, oid)
            if self._eval(gate, assignment):
                out.append(oid)
        return out


def _is_copier_rule(rule: dict[str, Any]) -> bool:
    """A validation rule whose `expr` is a Python-evaluable boolean.

    Rules with a non-`copier` scope (services_config's V-15.. carry a prose
    `expr`) are validated by validate_registry.py, not compiled here.
    """
    return rule.get("scope", "copier") == "copier"


def _resolve_default(key: str, spec: dict[str, Any]) -> Any:
    if key in PINNED_FREEFORM:
        return PINNED_FREEFORM[key]
    default = spec.get("default")
    # Templated Jinja defaults are not evaluable here. For a bool key (the
    # conditional `transport_rabbitmq` default) the base value is False and
    # axis enumeration covers True; other templated defaults (service_slug)
    # are never used as booleans, so return them verbatim.
    if isinstance(default, str) and "{{" in default:
        return False if spec.get("type") == "bool" else default
    return default


def _choice_values(choices: Any) -> list[Any]:
    if isinstance(choices, dict):
        return list(choices.values())
    if isinstance(choices, list):
        return list(choices)
    raise TypeError(f"unsupported choices shape: {choices!r}")


def _constraint_texts(raw: dict[str, Any]) -> list[str]:
    """Every expression string anywhere in the registry."""
    texts: list[str] = []
    for spec in raw.get("options", {}).values():
        when = spec.get("when")
        if isinstance(when, str):
            texts.append(when)
        for block_name in ("requires", "conflicts"):
            for item in spec.get(block_name, []) or []:
                texts.append(item["expr"])
    for rule in raw.get("validation_rules", []) or []:
        if not _is_copier_rule(rule):
            continue
        if isinstance(rule.get("applies_when"), str):
            texts.append(rule["applies_when"])
        texts.append(rule["expr"])
    for ir in raw.get("image_resolution", []) or []:
        if isinstance(ir.get("when"), str):
            texts.append(ir["when"])
    return texts


def _referenced_keys(texts: Iterable[str]) -> set[str]:
    ident = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
    keywords = {"and", "or", "not", "in", "is", "True", "False", "None"}
    out: set[str] = set()
    for text in texts:
        for match in ident.findall(text):
            if match not in keywords:
                out.add(match)
    return out


def _build_axes(raw: dict[str, Any]) -> list[Axis]:
    groups = raw.get("groups", {})
    constraint_texts = _constraint_texts(raw)
    referenced = _referenced_keys(constraint_texts)

    axes: list[Axis] = []
    for key, spec in raw.get("options", {}).items():
        if key in COMPUTED_KEYS or spec.get("when") is False:
            continue
        if key in PINNED_FREEFORM:
            continue
        axis_type = spec.get("type", "str")
        if axis_type in ("json", "yaml"):
            continue

        if axis_type == "bool":
            domain: list[Any] = [False, True]
        elif "choices" in spec:
            domain = _choice_values(spec["choices"])
        elif axis_type == "int" and key in INT_AXIS_DOMAINS:
            domain = list(INT_AXIS_DOMAINS[key])
        else:
            # No enumerable domain (free-form str/int without choices): pin it.
            continue

        if len(domain) < 2:
            # A single-value axis (python_version) adds no branching; keep it as
            # an independent axis so it still lands in the answers file.
            pass

        group = spec.get("group", "base")
        group_order = groups.get(group, {}).get("order", 999)
        has_own_constraint = (
            bool(spec.get("requires"))
            or bool(spec.get("conflicts"))
            or isinstance(spec.get("when"), str)
        )
        coupled = has_own_constraint or key in referenced

        axes.append(
            Axis(
                key=key,
                group=group,
                group_order=group_order,
                type=axis_type,
                domain=tuple(domain),
                default=_resolve_default(key, spec),
                when=spec.get("when") if isinstance(spec.get("when"), str) else None,
                coupled=coupled,
            )
        )

    axes.sort(key=lambda a: (a.group_order, a.key))
    return axes


def constraint_link_groups(raw: dict[str, Any]) -> list[set[str]]:
    """Groups of option keys that co-occur in the same constraint expression.

    Two keys named together in any `when` / `requires` / `conflicts` /
    `validation_rules` / `image_resolution` string are in the same group. Used to
    partition the coupled axes into independent components for enumeration.
    """
    groups: list[set[str]] = []
    for spec in raw.get("options", {}).values():
        own_key = spec.get("key")
        when = spec.get("when")
        if isinstance(when, str):
            grp = _referenced_keys([when]) | ({own_key} if own_key else set())
            groups.append(grp)
        for block_name in ("requires", "conflicts"):
            for item in spec.get(block_name, []) or []:
                grp = _referenced_keys([item["expr"]]) | ({own_key} if own_key else set())
                groups.append(grp)
    for rule in raw.get("validation_rules", []) or []:
        if not _is_copier_rule(rule):
            continue
        texts = [rule["expr"]]
        if isinstance(rule.get("applies_when"), str):
            texts.append(rule["applies_when"])
        groups.append(_referenced_keys(texts))
    for ir in raw.get("image_resolution", []) or []:
        if isinstance(ir.get("when"), str):
            groups.append(_referenced_keys([ir["when"]]))
    return groups


def axis_components(reg: Registry, axes: list[Axis]) -> list[list[Axis]]:
    """Partition `axes` into connected components under `constraint_link_groups`.

    Components are returned in a deterministic order (by the group_order/key of
    their first axis), and each component keeps the input axis order.
    """
    axis_keys = {a.key for a in axes}
    parent: dict[str, str] = {a.key: a.key for a in axes}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for grp in constraint_link_groups(reg.raw):
        members = sorted(k for k in grp if k in axis_keys)
        for other in members[1:]:
            union(members[0], other)

    buckets: dict[str, list[Axis]] = {}
    for axis in axes:
        buckets.setdefault(find(axis.key), []).append(axis)

    components = list(buckets.values())
    components.sort(key=lambda comp: (comp[0].group_order, comp[0].key))
    return components


def load_registry(path: str | Path) -> Registry:
    import hashlib

    path = Path(path)
    data = path.read_bytes()
    raw = yaml.safe_load(data)
    reg = Registry(
        path=path,
        raw=raw,
        sha256=hashlib.sha256(data).hexdigest(),
        meta=raw.get("meta", {}),
        overlay_order=list(raw.get("overlay_order", [])),
        groups=raw.get("groups", {}),
        options=raw.get("options", {}),
        validation_rules=list(raw.get("validation_rules", [])),
        image_resolution=list(raw.get("image_resolution", [])),
    )
    reg.axes = _build_axes(raw)
    return reg


def answers_for(reg: Registry, assignment: dict[str, Any]) -> dict[str, Any]:
    """Build a complete, canonical answers mapping for one combination.

    Includes every non-computed key. Conditional keys whose `when` is false are
    dropped, matching what Copier writes to `.copier-answers.yml`.
    """
    canon = reg.canonicalize(assignment)
    out: dict[str, Any] = {}

    for key, value in PINNED_FREEFORM.items():
        out[key] = value

    for key, spec in reg.options.items():
        if key in COMPUTED_KEYS or spec.get("when") is False:
            continue
        if key in PINNED_FREEFORM:
            continue
        when = spec.get("when")
        if isinstance(when, str) and not reg.evaluate(when, canon):
            continue
        out[key] = canon.get(key, _resolve_default(key, spec))

    return out

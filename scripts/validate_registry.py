#!/usr/bin/env python3
"""Lint ``registry.yaml`` against the schema in ``docs/registry-schema.md`` §6.2.

Pure, offline, deterministic. Exit 0 when clean, 1 with a list of problems, 2 on
a usage error. Run in CI and as a pre-commit hook.

Checks:
  * file parses; required top-level sections present
  * every ``overlay_order`` id maps 1:1 to an option whose ``overlay_id`` matches;
    no duplicates in ``overlay_order``
  * every option's map key equals its ``key`` field
  * every option ``group`` refers to a defined group
  * every identifier used in a ``when`` / ``requires`` / ``conflicts`` /
    ``validation_rules`` / ``image_resolution`` expression is a defined option key
    or a known computed key
  * ``validation_rules``: unique ids, ``expr`` + ``message`` present, every
    ``attach_to`` target is a defined option
  * ``image_resolution``: ``image_ref`` / ``else_image_ref`` resolve into
    ``compose_image_pins``
  * ``python_deps`` versions are exact pins and carry an ``as_of``
  * ``compose_image_pins`` entries carry an ``owner``; ``image`` present unless
    the pin is explicitly pending (``as_of: null`` is allowed, it means "owner
    has not pinned yet")
  * ``default`` values type-match the option ``type`` and, for ``choices``, are a
    valid choice value
  * ``registry_version`` option default equals ``meta.registry_version``
  * optional: no enum value renamed vs a previous registry (pass
    ``--prev PATH`` or set ``REGISTRY_PREV``); skipped when unavailable

Also exposes ``validate_services_config(answers)`` (and ``--answers PATH``) which
validates a multi-service answers file's ``services_config`` map: V-15..V-20 plus
a per-service replay of V-2..V-14 over each service's effective submap. The
``msvc-gen`` CLI runs it before an orchestrated ``monorepo`` / ``multi_repo``
generation (D-036). See ``docs/services-config-schema.md``.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover
    print("PyYAML is required: `uv sync` or `pip install pyyaml`", file=sys.stderr)
    raise SystemExit(2) from None

REQUIRED_SECTIONS = ("meta", "overlay_order", "groups", "options")
RANGE_TOKENS = ("^", "~", ">=", "<=", ">", "<", "*", ",", "!=", " ")
EXPR_KEYWORDS = {"and", "or", "not", "in", "is", "True", "False", "None", "true", "false"}
# Computed / injected keys that expressions may reference but that are not
# prompted options. Mirrors harness/registry_model.py and gen_copier_yml.py.
EXPR_EXTRA_KEYS = {"api_rest", "healthchecks", "_copier_operation"}


def _load(path: Path) -> dict[str, Any]:
    with path.open() as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError("registry.yaml top level must be a mapping")
    return data


def _identifiers(expr: str) -> set[str]:
    """Bare identifiers in an expression, ignoring quoted string literals."""
    out: set[str] = set()
    token = ""
    quote: str | None = None
    for ch in expr + " ":
        if quote is not None:
            if ch == quote:
                quote = None
            continue
        if ch in ("'", '"'):
            quote = ch
            continue
        if ch.isalnum() or ch == "_":
            token += ch
        else:
            if token and not token[0].isdigit():
                out.add(token)
            token = ""
    return out - EXPR_KEYWORDS


def _choice_values(choices: Any) -> list[Any]:
    if isinstance(choices, dict):
        return list(choices.values())
    if isinstance(choices, list):
        return list(choices)
    return []


def _all_exprs(reg: dict[str, Any]) -> list[tuple[str, str]]:
    """(context label, expression) for every expression string in the registry."""
    out: list[tuple[str, str]] = []
    for key, opt in reg.get("options", {}).items():
        if isinstance(opt.get("when"), str):
            out.append((f"options.{key}.when", opt["when"]))
        for block in ("requires", "conflicts"):
            for i, item in enumerate(opt.get(block, []) or []):
                out.append((f"options.{key}.{block}[{i}]", item["expr"]))
        if isinstance(opt.get("gate"), str):
            out.append((f"options.{key}.gate", opt["gate"]))
    for rule in reg.get("validation_rules", []) or []:
        rid = rule.get("id", "?")
        if isinstance(rule.get("applies_when"), str):
            out.append((f"validation_rules.{rid}.applies_when", rule["applies_when"]))
        # `scope: services_config` rules state their predicate in prose (they are
        # evaluated structurally by validate_services_config, not as Jinja), so
        # their `expr` is not an identifier-checkable expression.
        if rule.get("scope", "copier") == "copier":
            out.append((f"validation_rules.{rid}.expr", rule["expr"]))
    for ir in reg.get("image_resolution", []) or []:
        if isinstance(ir.get("when"), str):
            out.append((f"image_resolution.{ir.get('id', '?')}.when", ir["when"]))
    return out


def validate(path: Path, prev_path: Path | None) -> list[str]:  # noqa: C901 - linear checklist
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

    meta = reg.get("meta") or {}
    groups = reg.get("groups") or {}
    options = reg.get("options") or {}
    overlay_order = reg.get("overlay_order") or []
    known_keys = set(options) | EXPR_EXTRA_KEYS

    # ---- overlay_order --------------------------------------------------------
    if len(overlay_order) != len(set(overlay_order)):
        problems.append("overlay_order contains duplicate ids")
    overlay_ids = {
        opt.get("overlay_id")
        for opt in options.values()
        if isinstance(opt, dict) and opt.get("overlay_id")
    }
    for oid in overlay_order:
        if oid not in overlay_ids:
            problems.append(f"overlay_order id has no option with overlay_id == {oid!r}")
    for opt_key, opt in options.items():
        oid = opt.get("overlay_id") if isinstance(opt, dict) else None
        if oid and oid not in overlay_order:
            problems.append(f"option {opt_key!r} declares overlay_id {oid!r} not in overlay_order")

    # ---- per-option shape ---------------------------------------------------
    for key, opt in options.items():
        if not isinstance(opt, dict):
            problems.append(f"option {key!r} is not a mapping")
            continue
        if opt.get("key") != key:
            problems.append(f"option {key!r} has mismatched 'key' field: {opt.get('key')!r}")
        grp = opt.get("group")
        if grp is not None and grp not in groups:
            problems.append(f"option {key!r} references undefined group {grp!r}")

        # python_deps: exact pins + as_of. `group` is "runtime" (default) or "dev".
        # TODO(later, Lead-approved): cross-check that a group:dev dep appears in the
        # overlay's dev-deps.toml.jinja fragment and a group:runtime one in deps.toml.jinja.
        for pkg, spec in (opt.get("python_deps") or {}).items():
            version = spec.get("version") if isinstance(spec, dict) else spec
            if not isinstance(version, str) or any(t in version for t in RANGE_TOKENS):
                problems.append(f"option {key!r} dep {pkg!r} is not an exact pin: {version!r}")
            if isinstance(spec, dict):
                if not spec.get("as_of"):
                    problems.append(f"option {key!r} dep {pkg!r} missing as_of date")
                grp = spec.get("group", "runtime")
                if grp not in ("runtime", "dev"):
                    problems.append(f"option {key!r} dep {pkg!r} has invalid group {grp!r}")

        # default type-match
        _check_default(key, opt, problems)

    # ---- expression identifiers -------------------------------------------
    for label, expr in _all_exprs(reg):
        for ident in _identifiers(expr):
            if ident not in known_keys:
                problems.append(f"{label}: expression references unknown key {ident!r}")

    # ---- validation_rules ------------------------------------------------
    seen_rule_ids: set[str] = set()
    for rule in reg.get("validation_rules", []) or []:
        rid = rule.get("id")
        if not rid:
            problems.append("validation_rules entry missing 'id'")
            continue
        if rid in seen_rule_ids:
            problems.append(f"validation_rules duplicate id: {rid}")
        seen_rule_ids.add(rid)
        if not rule.get("expr"):
            problems.append(f"validation_rules {rid}: missing 'expr'")
        if not rule.get("message"):
            problems.append(f"validation_rules {rid}: missing 'message'")
        for target in rule.get("attach_to", []) or []:
            if target not in options:
                problems.append(
                    f"validation_rules {rid}: attach_to {target!r} is not a defined option"
                )

    # ---- image_resolution + compose_image_pins --------------------------
    pins = reg.get("compose_image_pins") or {}
    for ref, spec in pins.items():
        if not isinstance(spec, dict):
            problems.append(f"compose_image_pins {ref!r} is not a mapping")
            continue
        if not spec.get("owner"):
            problems.append(f"compose_image_pins {ref!r} missing 'owner'")
        if "image" not in spec:
            problems.append(f"compose_image_pins {ref!r} missing 'image'")
    for ir in reg.get("image_resolution", []) or []:
        irid = ir.get("id", "?")
        for field in ("image_ref", "else_image_ref"):
            ref = ir.get(field)
            if ref is not None and ref not in pins:
                problems.append(
                    f"image_resolution {irid}: {field} {ref!r} not in compose_image_pins"
                )

    # ---- meta cross-checks --------------------------------------------
    rv_opt = options.get("registry_version", {})
    if "default" in rv_opt and rv_opt["default"] != meta.get("registry_version"):
        problems.append(
            f"registry_version option default {rv_opt['default']!r} != "
            f"meta.registry_version {meta.get('registry_version')!r}"
        )

    # ---- optional: renamed enum values vs previous registry ------------
    if prev_path and prev_path.exists():
        problems.extend(_check_no_renamed_values(reg, _load(prev_path)))
    else:
        print(
            "[validate_registry] note: no previous registry to diff enum values against",
            file=sys.stderr,
        )

    return problems


def _check_default(key: str, opt: dict[str, Any], problems: list[str]) -> None:
    if "default" not in opt:
        return
    default = opt["default"]
    if default is None:
        return
    otype = opt.get("type", "str")
    choices = opt.get("choices")

    if opt.get("multiselect"):
        if not isinstance(default, list):
            problems.append(f"option {key!r} multiselect default must be a list, got {default!r}")
        return

    # A Jinja-templated string default (contains `{{`) is computed at render time,
    # not a literal of the option's declared type. `transport_rabbitmq` uses
    # `"{{ true if topology != 'single' else false }}"` (deterministic function of
    # `topology`, scope section 4.3). Accept it for any scalar type.
    jinja_default = isinstance(default, str) and "{{" in default

    if otype == "bool" and not isinstance(default, bool) and not jinja_default:
        problems.append(f"option {key!r} type bool but default is {default!r}")
    elif otype == "int" and not isinstance(default, int) and not jinja_default:
        problems.append(f"option {key!r} type int but default is {default!r}")
    elif otype in ("json", "yaml") and not isinstance(default, (dict, list, str)):
        problems.append(f"option {key!r} type {otype} but default is {default!r}")

    if choices is not None and isinstance(default, (str, int)):
        valid = _choice_values(choices)
        # Jinja-templated defaults are computed, not literal choices.
        if not (isinstance(default, str) and "{{" in default) and default not in valid:
            problems.append(f"option {key!r} default {default!r} is not one of choices {valid}")


def _enum_values(reg: dict[str, Any]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for key, opt in reg.get("options", {}).items():
        choices = opt.get("choices")
        if choices is not None:
            out[key] = {str(v) for v in _choice_values(choices)}
    return out


def _check_no_renamed_values(reg: dict[str, Any], prev: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    now, was = _enum_values(reg), _enum_values(prev)
    for key, old_values in was.items():
        if key not in now:
            continue
        removed = old_values - now[key]
        if removed:
            problems.append(
                f"option {key!r}: choice value(s) {sorted(removed)} removed/renamed vs previous "
                "registry - needs a migrations entry (registry-schema.md §8.2)"
            )
    return problems


# --------------------------------------------------------------------------- #
# services_config validation (D-005 / D-017 / D-036; docs/services-config-schema.md)
# --------------------------------------------------------------------------- #

SERVICE_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,48}$")

# Keys allowed inside a per-service `services_config` submap
# (docs/services-config-schema.md §2.2): the 20 overlay_order ids minus the two
# shared transport ids, plus the sub-option keys, plus tests_unit /
# tests_integration / llm_response_mode / docker.
PER_SERVICE_KEYS = frozenset(
    {
        "api_grpc", "streaming_sse", "streaming_grpc", "tool_scaffold", "mcp_server",
        "db_postgres", "db_mongodb", "db_redis", "redis_pubsub", "db_qdrant",
        "messaging_rabbitmq",
        "llm_openai", "llm_anthropic", "prompt_management", "langchain",
        "langchain_retrieval", "embedding_pipeline", "embedding_backend",
        "embedding_vector_size", "langgraph", "langgraph_checkpoint", "langsmith",
        "otel_tracing",
        "crud_scaffold", "crud_entity", "crud_backend",
        "tests_unit", "tests_integration", "llm_response_mode", "docker",
    }
)  # fmt: skip


def _per_service_defaults(registry: dict[str, Any]) -> dict[str, Any]:
    """Registry `default:` for each per-service key, for the effective-submap base."""
    options = registry.get("options", {}) or {}
    out: dict[str, Any] = {}
    for key in PER_SERVICE_KEYS:
        opt = options.get(key, {})
        out[key] = opt.get("default")
    return out


def _effective_submap(svc: str, submap: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    """docs/services-config-schema.md §3 merge: registry defaults <- submap <-
    derived identity <- the shared keys a single render also needs."""
    eff = dict(defaults)
    for k, v in submap.items():
        eff[k] = v
    eff["service_name"] = svc
    eff["service_slug"] = svc
    eff["python_package"] = svc.replace("-", "_")
    # Shared computed keys a single-style render always has (D-018 / D-026).
    eff["api_rest"] = True
    eff["healthchecks"] = True
    return eff


def _replay_single_rules(svc: str, e: dict[str, Any]) -> list[str]:
    """V-2..V-14 minus the topology-level rules (V-1, V-11), as Python predicates
    over one service's effective submap ``e``. Each row is
    ``(applies?, must-hold?, "id - message")``; ids/messages mirror
    docs/registry-schema.md §4."""
    g = e.get
    llm = bool(g("llm_openai") or g("llm_anthropic"))
    backend = g("embedding_backend", "fastembed")
    cp = g("langgraph_checkpoint", "postgres")
    rows: list[tuple[Any, Any, str]] = [
        (
            g("tool_scaffold"),
            g("api_rest") or g("api_grpc"),
            "V-2 - tool_scaffold needs api_rest or api_grpc",
        ),
        (
            g("mcp_server"),
            g("tool_scaffold") or g("api_grpc"),
            "V-3 - mcp_server needs tool_scaffold or api_grpc",
        ),
        (g("embedding_pipeline"), g("db_qdrant"), "V-4 - embedding_pipeline needs db_qdrant"),
        (
            g("langgraph"),
            g("db_postgres") or g("db_redis"),
            "V-5 - langgraph needs db_postgres or db_redis",
        ),
        (
            g("langchain_retrieval"),
            g("langchain") and g("db_qdrant"),
            "V-6 - langchain_retrieval needs langchain and db_qdrant",
        ),
        (g("langchain"), llm, "V-7 - langchain needs an LLM provider"),
        (
            g("embedding_pipeline"),
            backend == "fastembed" or (backend == "openai" and g("llm_openai")),
            "V-8 - openai embedding backend needs llm_openai",
        ),
        (
            g("langgraph"),
            (cp == "postgres" and g("db_postgres")) or (cp == "redis" and g("db_redis")),
            "V-9 - langgraph_checkpoint store must be enabled",
        ),
        (g("langsmith"), llm, "V-10 - langsmith needs an LLM provider"),
        (g("redis_pubsub"), g("db_redis"), "V-12 - redis_pubsub needs db_redis"),
        (g("streaming_grpc"), g("api_grpc"), "V-13 - streaming_grpc needs api_grpc"),
        (g("streaming_sse"), g("api_rest"), "V-14 - streaming_sse needs api_rest"),
    ]
    return [f"service {svc!r}: {label}" for applies, holds, label in rows if applies and not holds]


def validate_services_config(
    answers: dict[str, Any], registry_path: Path | None = None
) -> list[str]:
    """Validate a multi-service answers file's `services_config` (V-15..V-20 plus
    a per-service replay of V-2..V-14). Returns [] for a `single` topology or a
    clean map. The msvc-gen CLI calls this before an orchestrated monorepo /
    multi_repo generation (D-036); it never guesses, it rejects (scope §6)."""
    problems: list[str] = []
    if (answers.get("topology") or "single") == "single":
        return problems

    reg_path = registry_path or Path(__file__).resolve().parent.parent / "registry.yaml"
    try:
        registry = _load(reg_path)
    except (yaml.YAMLError, ValueError, OSError) as exc:  # pragma: no cover
        return [f"could not load registry for services_config validation: {exc}"]
    defaults = _per_service_defaults(registry)

    names = answers.get("service_names") or []
    if not isinstance(names, list):
        return ["service_names must be a list for a multi-service topology"]
    sc = answers.get("services_config") or {}
    if not isinstance(sc, dict):
        return ["services_config must be a mapping"]

    # V-19: at least one service
    if len(names) < 1:
        problems.append("V-19: service_names is empty for a multi-service topology")
    # V-20: name regex
    for n in names:
        if not (isinstance(n, str) and SERVICE_NAME_RE.match(n)):
            problems.append(f"V-20: service name {n!r} is not kebab-case")
    # V-16: distinct after '-' -> '_'
    normalized = [n.replace("-", "_") for n in names if isinstance(n, str)]
    if len(set(normalized)) != len(normalized):
        problems.append("V-16: two service names normalize to the same Python package")
    # V-15: every services_config key is a declared service
    for k in sc:
        if k not in names:
            problems.append(f"V-15: services_config entry {k!r} is not in service_names")
    # V-17: submaps carry only known per-service keys
    for k, submap in sc.items():
        if not isinstance(submap, dict):
            problems.append(f"V-17: services_config[{k!r}] must be a mapping")
            continue
        for sk in submap:
            if sk not in PER_SERVICE_KEYS:
                problems.append(f"V-17: services_config[{k!r}] key {sk!r} not allowed in a submap")

    # Per-service replay of V-2..V-14, and collect api_grpc for V-18.
    any_api_grpc = False
    for svc in names:
        if not isinstance(svc, str):
            continue
        raw = sc.get(svc, {})
        submap = (
            {k: v for k, v in raw.items() if k in PER_SERVICE_KEYS} if isinstance(raw, dict) else {}
        )
        eff = _effective_submap(svc, submap, defaults)
        any_api_grpc = any_api_grpc or bool(eff.get("api_grpc"))
        problems.extend(_replay_single_rules(svc, eff))

    # V-18: gRPC transport needs at least one gRPC server
    if answers.get("transport_grpc") and not any_api_grpc:
        problems.append("V-18: transport_grpc is on but no service enables api_grpc")

    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("registry", nargs="?", default="registry.yaml", type=Path)
    parser.add_argument(
        "--prev",
        type=Path,
        default=os.environ.get("REGISTRY_PREV"),
        help="Previous registry.yaml to diff enum values against (optional).",
    )
    parser.add_argument(
        "--answers",
        type=Path,
        default=None,
        help="An answers YAML to run validate_services_config against (multi-service topology).",
    )
    args = parser.parse_args(argv)

    if not args.registry.exists():
        print(f"[validate_registry] not found: {args.registry}", file=sys.stderr)
        return 2

    if args.answers is not None:
        if not args.answers.exists():
            print(f"[validate_registry] answers not found: {args.answers}", file=sys.stderr)
            return 2
        with args.answers.open() as fh:
            answers = yaml.safe_load(fh) or {}
        sc_problems = validate_services_config(answers, args.registry)
        if sc_problems:
            n = len(sc_problems)
            print(f"[validate_registry] {n} services_config problem(s):", file=sys.stderr)
            for p in sc_problems:
                print(f"  - {p}", file=sys.stderr)
            return 1
        print("[validate_registry] services_config ok")
        return 0

    problems = validate(args.registry, args.prev)
    if problems:
        print(f"[validate_registry] {len(problems)} problem(s):", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    print("[validate_registry] ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

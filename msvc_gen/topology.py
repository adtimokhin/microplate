"""Multi-service topology orchestration (D-036).

`cli.py` calls into here ONLY when ``topology != 'single'``. The single-service
path in `cli.py` is untouched.

Mechanism (D-036, supersedes the ``{% yield %}`` mechanism sketched in D-017;
D-017's one-root-manifest intent stands):

* One ordinary single-service Copier render per name in ``service_names`` (the
  frozen list order), each driven by that service's *effective* answer set
  (shared top-level keys + ``services_config[<svc>]`` submap + a forced
  ``service_name``). No ``{% yield %}``, no change to ``template/`` or any
  overlay.
* ``monorepo``  -> every service renders into ``<output>/services/<svc>/``.
  ``multi_repo`` -> every service renders into ``<output>/<svc>/`` as an
  independent repo.
* Each service directory keeps its OWN ``.copier-answers.yml`` (native Copier),
  so ``copier update`` works per service.
* A thin root layer is rendered on top: a root ``docker-compose.yml`` wiring the
  service app containers, a root ``README.md``, a root CI workflow, and a root
  ``.copier-answers.yml`` MANIFEST carrying ``topology`` + ``service_names`` +
  ``services_config`` + the shared keys. ``copier update`` re-renders the root
  layer wholesale.

Determinism: N single renders in frozen ``service_names`` order + one root
render, every step a pure function of the answers.
"""

from __future__ import annotations

import importlib.util
import json
import re
from functools import lru_cache
from pathlib import Path
from types import ModuleType
from typing import Any, Literal

import copier
import yaml

_ROOT_TEMPLATES = Path(__file__).resolve().parent / "root_templates"
_REPO_ROOT = Path(__file__).resolve().parent.parent
_REGISTRY_PATH = _REPO_ROOT / "registry.yaml"


@lru_cache(maxsize=1)
def _validate_registry_mod() -> ModuleType | None:
    """Load ``scripts/validate_registry.py`` as a module (it is not a package).

    Returns ``None`` if the file is absent (e.g. a packaged install without the
    dev scripts); deep ``services_config`` validation is then skipped and the
    per-service Copier renders still enforce every ``copier.yml`` validator.
    """

    path = _REPO_ROOT / "scripts" / "validate_registry.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("_msvc_validate_registry", path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

# A service name uses the same rule as the top-level `service_name`
# (registry-schema.md base group).
_SERVICE_NAME_RE = re.compile(r"^[a-z][a-z0-9-]{1,48}$")

_VALID_TOPOLOGIES = ("monorepo", "multi_repo")

# Keys answered once at the top level; passed through into every per-service
# render unchanged. Mirrors docs/services-config-schema.md 2.1.
SHARED_PASSTHROUGH_KEYS = (
    "license",
    "ci",
    "iac",
    "docker",
    "topology",
    "service_names",
    "transport_grpc",
    "transport_rabbitmq",
    # claude_hooks + its hook_* sub-options are answered once; each service dir
    # gets its own .claude/ rendered from the shared answer (D-041).
    "claude_hooks",
    "hook_guard_pack",
    "hook_format_code",
    "hook_protect_tests",
    "hook_auto_stage",
    "hook_session_logger",
    "hook_instructions_audit",
)

# Keys a per-service submap MAY carry. Mirrors docs/services-config-schema.md 2.2:
# the 20 overlay_order ids minus the two transports, plus the sub-option keys,
# plus the per-service testing / packaging choices.
PER_SERVICE_ALLOWED_KEYS = frozenset(
    {
        "api_grpc",
        "streaming_sse",
        "streaming_grpc",
        "tool_scaffold",
        "mcp_server",
        "db_postgres",
        "db_mongodb",
        "db_redis",
        "redis_pubsub",
        "db_qdrant",
        "messaging_rabbitmq",
        "llm_openai",
        "llm_anthropic",
        "prompt_management",
        "langchain",
        "langchain_retrieval",
        "embedding_pipeline",
        "embedding_backend",
        "embedding_vector_size",
        "langgraph",
        "langgraph_checkpoint",
        "langsmith",
        "otel_tracing",
        "crud_scaffold",
        "crud_entity",
        "crud_backend",
        "crud_soft_delete",
        "tests_unit",
        "tests_integration",
        "llm_response_mode",
        "docker",
    }
)


class TopologyError(SystemExit):
    """User-facing multi-service generation error."""


# ---------------------------------------------------------------------------
# pure helpers (unit-tested offline in tests/test_topology.py)


def _slug(name: str) -> str:
    """Match includes/slugify.jinja for an already-clean service name."""

    return re.sub(r"-+$", "", re.sub(r"[^a-z0-9]+", "-", name.lower())).strip("-")


def _python_package(name: str) -> str:
    return _slug(name).replace("-", "_")


def normalize_service_names(raw: Any) -> list[str]:
    """Return the service roster as an ordered list of validated names.

    Accepts a YAML list (from an answers file) or a comma / space string
    (defensive; ``--data`` already yields a list via ``yaml.safe_load``).
    Order is preserved exactly - it is the frozen iteration order.
    """

    if raw is None:
        raise TopologyError("topology != 'single' requires a non-empty service_names list")
    if isinstance(raw, str):
        items = [p for p in re.split(r"[,\s]+", raw.strip()) if p]
    elif isinstance(raw, (list, tuple)):
        items = [str(p) for p in raw]
    else:
        raise TopologyError(f"service_names must be a list, got {type(raw).__name__}")

    if not items:
        raise TopologyError("service_names is empty (V-T5)")
    seen: set[str] = set()
    packages: set[str] = set()
    for name in items:
        if not _SERVICE_NAME_RE.match(name):
            raise TopologyError(
                f"service name {name!r} does not match ^[a-z][a-z0-9-]{{1,48}}$ (V-T6)"
            )
        if name in seen:
            raise TopologyError(f"duplicate service name {name!r}")
        pkg = _python_package(name)
        if pkg in packages:
            raise TopologyError(
                f"service name {name!r} collides with another after '-' -> '_' normalization (V-T2)"
            )
        seen.add(name)
        packages.add(pkg)
    return items


def _coerce_services_config(raw: Any) -> dict[str, dict[str, Any]]:
    if raw in (None, "", {}):
        return {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise TopologyError(f"services_config is not valid JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise TopologyError("services_config must be a JSON object of service -> submap")
    out: dict[str, dict[str, Any]] = {}
    for svc, submap in raw.items():
        if not isinstance(submap, dict):
            raise TopologyError(f"services_config[{svc!r}] must be an object")
        out[str(svc)] = dict(submap)
    return out


def validate_services_config(
    service_names: list[str], services_config: dict[str, dict[str, Any]]
) -> None:
    """Fast structural checks for clear local errors. The authoritative replay of
    V-15..V-20 + per-service V-2..V-14 is RegistryArchitect's
    ``validate_registry.validate_services_config``, run by ``_deep_validate``."""

    roster = set(service_names)
    for svc, submap in services_config.items():
        if svc not in roster:
            raise TopologyError(
                f"services_config names {svc!r} which is not in service_names (V-T1)"
            )
        unknown = set(submap) - PER_SERVICE_ALLOWED_KEYS
        if unknown:
            raise TopologyError(
                f"services_config[{svc!r}] has keys not valid per-service: "
                f"{sorted(unknown)} (V-T3). Shared keys stay at the top level."
            )


def effective_answers(
    data: dict[str, Any],
    svc: str,
    services_config: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Build one service's complete single-service answer set.

    Order (docs/services-config-schema.md 3): shared passthrough keys, then the
    service's submap, then the forced identity / root-only keys. Registry
    defaults for everything else are applied by Copier itself.
    """

    eff: dict[str, Any] = {}
    for key in SHARED_PASSTHROUGH_KEYS:
        if key in data:
            eff[key] = data[key]
    eff.update(services_config.get(svc, {}))
    # Forced: identity from the roster entry, and the root-only keys.
    eff["service_name"] = svc
    eff["services_config"] = {}   # not recursive; keep the per-service answers file lean
    eff["tests_contract"] = False  # contract tests are a root-layer job, never per-service
    return eff


def service_dest(output: Path, topology: str, svc: str) -> Path:
    if topology == "monorepo":
        return output / "services" / svc
    return output / svc  # multi_repo: one independent repo dir per service


# ---------------------------------------------------------------------------
# root layer


def _render_tree(src: Path, dst: Path, ctx: dict[str, Any]) -> list[Path]:
    """Render every file under ``src`` (``.jinja`` stripped) into ``dst`` with a
    plain Jinja environment. Used for the root wiring layer only - it carries no
    user business logic and is re-rendered wholesale on update."""

    from jinja2 import Environment, FileSystemLoader, StrictUndefined

    env = Environment(
        loader=FileSystemLoader(str(src)),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        autoescape=False,
    )
    written: list[Path] = []
    for path in sorted(src.rglob("*")):
        if path.is_dir() or path.name == "__init__.py":
            continue
        rel = path.relative_to(src)
        rel_out = rel.with_suffix("") if rel.suffix == ".jinja" else rel
        template = env.get_template(str(rel).replace("\\", "/"))
        rendered = template.render(**ctx)
        # A root template that gates its whole body on a flag renders to nothing
        # when the flag is off (e.g. buf.yaml without tests_contract). Skip it so
        # the output tree only carries files the topology actually needs.
        if not rendered.strip():
            continue
        target = dst / rel_out
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered)
        # Preserve the source file's mode so a rendered script keeps its +x bit
        # (Copier does this for its own renders; the root layer must match).
        target.chmod(path.stat().st_mode & 0o777)
        written.append(target)
    return written


@lru_cache(maxsize=1)
def _registry() -> dict[str, Any]:
    if not _REGISTRY_PATH.is_file():  # pragma: no cover - defensive
        return {}
    loaded = yaml.safe_load(_REGISTRY_PATH.read_text())
    return loaded if isinstance(loaded, dict) else {}


# Overlay keys that add a compose backing service, in the order the root compose
# should emit them. Each maps to that option's `compose_services` block in
# registry.yaml (single-sourced pins, D-019 / D-023).
_BACKING_OVERLAY_KEYS = (
    "db_postgres",
    "db_mongodb",
    "db_redis",
    "db_qdrant",
    "messaging_rabbitmq",
)


def _effective_submap(svc: str, services_config: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Registry per-service defaults <- this service's submap. Used for the root
    wiring layer's view of a service (which datastores it needs, whether it
    exposes a gRPC server). Mirrors validate_registry._effective_submap."""

    mod = _validate_registry_mod()
    reg = _registry()
    defaults = mod._per_service_defaults(reg) if (mod is not None and reg) else {}
    eff = dict(defaults)
    eff.update(services_config.get(svc, {}))
    return eff


def _compose_service_def(overlay_key: str, *, redis_stack: bool = False) -> dict[str, Any] | None:
    """The `{name,image,ports,healthcheck,environment}` for one backing overlay,
    read from registry.yaml `compose_services`."""

    opt = (_registry().get("options", {}) or {}).get(overlay_key, {}) or {}
    entries = opt.get("compose_services") or []
    if not entries:
        return None
    entry = entries[0]
    name = str(entry.get("name", overlay_key))
    image = str(entry.get("image", ""))
    ports = [str(p) for p in entry.get("ports", [])]
    if overlay_key == "db_redis" and redis_stack:
        pins = _registry().get("compose_image_pins", {}) or {}
        image = str((pins.get("redis_stack") or {}).get("image", image))
        ports = ["6379:6379", "8001:8001"]
    env: dict[str, str] = {}
    if overlay_key == "db_postgres":
        env = {"POSTGRES_USER": "app", "POSTGRES_PASSWORD": "app", "POSTGRES_DB": "app"}
    return {
        "name": name,
        "image": image,
        "ports": ports,
        "healthcheck": str(entry.get("healthcheck", "")),
        "environment": env,
    }


def _root_context(
    data: dict[str, Any], topology: str, service_names: list[str],
    services_config: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    repo_name = str(data.get("service_name") or (service_names[0] if service_names else "services"))
    transport_grpc = bool(data.get("transport_grpc", False))
    transport_rabbitmq = bool(data.get("transport_rabbitmq", False))

    effmaps = {s: _effective_submap(s, services_config) for s in service_names}
    redis_stack = any(
        e.get("langgraph") and (e.get("langgraph_checkpoint") or "postgres") == "redis"
        for e in effmaps.values()
    )

    # Union of backing services across every submap, deterministic order:
    # service_names order, then _BACKING_OVERLAY_KEYS order.
    backing: dict[str, dict[str, Any]] = {}
    for s in service_names:
        eff = effmaps[s]
        for key in _BACKING_OVERLAY_KEYS:
            if not eff.get(key):
                continue
            definition = _compose_service_def(key, redis_stack=redis_stack)
            if definition and definition["name"] not in backing:
                backing[definition["name"]] = definition
    # transport_rabbitmq adds the shared bus broker if no submap already did.
    if transport_rabbitmq and "rabbitmq" not in backing:
        definition = _compose_service_def("messaging_rabbitmq")
        if definition:
            backing[definition["name"]] = definition

    def _depends_on(eff: dict[str, Any]) -> list[str]:
        needed = [
            _compose_service_def(key, redis_stack=redis_stack)["name"]  # type: ignore[index]
            for key in _BACKING_OVERLAY_KEYS
            if eff.get(key) and _compose_service_def(key, redis_stack=redis_stack)
        ]
        if transport_rabbitmq and "rabbitmq" not in needed:
            needed.append("rabbitmq")
        return [n for n in needed if n in backing]

    services = []
    for i, s in enumerate(service_names):
        eff = effmaps[s]
        services.append(
            {
                "name": s,
                "slug": _slug(s),
                "package": _python_package(s),
                "index": i,
                "http_port": 8000 + i,
                "has_api_grpc": bool(eff.get("api_grpc")),
                "depends_on": _depends_on(eff),
                "peers": [
                    {"name": p, "slug": _slug(p)} for p in service_names if p != s
                ],
            }
        )

    return {
        "topology": topology,
        "repo_name": repo_name,
        "repo_slug": _slug(repo_name),
        "services": services,
        "service_names": service_names,
        "backing_services": list(backing.values()),
        "services_config": services_config,
        "services_config_json": json.dumps(services_config, indent=2, sort_keys=True),
        "transport_grpc": transport_grpc,
        "transport_rabbitmq": transport_rabbitmq,
        "tests_contract": bool(data.get("tests_contract", False)),
        "ci": str(data.get("ci", "github_actions")),
        "license": str(data.get("license", "proprietary")),
    }


def render_root_layer(
    output: Path, data: dict[str, Any], topology: str, service_names: list[str],
    services_config: dict[str, dict[str, Any]], *, dry_run: bool,
) -> list[Path]:
    ctx = _root_context(data, topology, service_names, services_config)
    src = _ROOT_TEMPLATES / topology
    if not src.is_dir():
        raise TopologyError(f"missing root templates for topology {topology!r} at {src}")
    if dry_run:
        return []
    output.mkdir(parents=True, exist_ok=True)
    return _render_tree(src, output, ctx)


# ---------------------------------------------------------------------------
# orchestration entrypoints (called by cli.py)


def _deep_validate(data: dict[str, Any], service_names: list[str],
                   services_config: dict[str, dict[str, Any]]) -> None:
    """Run RegistryArchitect's authoritative ``services_config`` rules
    (V-15..V-20 + the per-service replay of V-2..V-14). The generator never
    guesses, it rejects (scope §6). Skipped only if the dev scripts are absent."""

    mod = _validate_registry_mod()
    if mod is None:
        return
    answers = {
        "topology": data.get("topology"),
        "service_names": service_names,
        "transport_grpc": bool(data.get("transport_grpc", False)),
        "transport_rabbitmq": bool(data.get("transport_rabbitmq", False)),
        "services_config": services_config,
    }
    problems: list[str] = mod.validate_services_config(answers, _REGISTRY_PATH)
    if problems:
        raise TopologyError(
            "services_config validation failed:\n  - " + "\n  - ".join(problems)
        )


def _prepare(data: dict[str, Any]) -> tuple[str, list[str], dict[str, dict[str, Any]]]:
    topology = str(data.get("topology", "single"))
    if topology not in _VALID_TOPOLOGIES:
        raise TopologyError(f"topology must be one of {_VALID_TOPOLOGIES}, got {topology!r}")
    service_names = normalize_service_names(data.get("service_names"))
    services_config = _coerce_services_config(data.get("services_config"))
    validate_services_config(service_names, services_config)
    _deep_validate(data, service_names, services_config)
    return topology, service_names, services_config


def run_multi_service_new(
    *,
    template_src: str,
    output: Path,
    data: dict[str, Any],
    vcs_ref: str,
    skip_tasks: bool,
    force: bool,
    dry_run: bool,
    quiet: bool,
) -> int:
    output = Path(output).resolve()  # symlinked parents (macOS /var) break copier.run_update
    topology, service_names, services_config = _prepare(data)
    if not quiet:
        print(f"topology={topology}: {len(service_names)} services {service_names} -> {output}")

    for svc in service_names:  # frozen order
        dest = service_dest(output, topology, svc)
        eff = effective_answers(data, svc, services_config)
        if not quiet:
            print(f"  render {svc} -> {dest}")
        copier.run_copy(
            template_src,
            str(dest),
            data=eff,
            vcs_ref=vcs_ref,
            defaults=True,
            unsafe=True,
            skip_tasks=skip_tasks,
            overwrite=force,
            pretend=dry_run,
            quiet=quiet,
        )

    render_root_layer(
        output, data, topology, service_names, services_config, dry_run=dry_run
    )
    if not quiet:
        print(f"  root layer -> {output}")
    return 0


def run_multi_service_update(
    *,
    output: Path,
    data: dict[str, Any],
    vcs_ref: str,
    skip_tasks: bool,
    dry_run: bool,
    quiet: bool,
    conflict: Literal["inline", "rej"],
) -> int:
    """Re-run ``copier update`` per service directory, then re-render the root
    layer. The roster and per-service config come from the passed ``data`` (the
    root manifest answers file), not re-discovered from disk."""

    output = Path(output).resolve()  # symlinked parents (macOS /var) break copier.run_update
    topology, service_names, services_config = _prepare(data)
    for svc in service_names:  # frozen order
        dest = service_dest(output, topology, svc)
        if not dest.is_dir():
            raise TopologyError(
                f"cannot update: {dest} does not exist. Roster changed? Regenerate with `new`."
            )
        copier.run_update(
            str(dest),
            data=effective_answers(data, svc, services_config),
            vcs_ref=vcs_ref,
            defaults=True,
            unsafe=True,
            skip_tasks=skip_tasks,
            overwrite=True,
            pretend=dry_run,
            quiet=quiet,
            conflict=conflict,
        )
    render_root_layer(
        output, data, topology, service_names, services_config, dry_run=dry_run
    )
    return 0

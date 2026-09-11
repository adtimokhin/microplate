# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml==6.0.2", "copier==9.18.2"]
# ///
"""Runner for the combinatorial verification harness.

For each answers file in a combination set it:

  1. renders the generator template TWICE into separate temp dirs and asserts the
     two trees are byte-identical (determinism gate),
  2. `uv lock` + `uv sync` in the generated project,
  3. `uv run pytest` in the generated project,
  4. if `docker` was selected: `docker compose config` validates the compose file,
  5. if the combination selects a datastore / broker overlay (one with
     `compose_services`) and Docker is reachable: `boot_under_compose()` brings
     the backing services up for real with `docker compose up --wait`, asserts
     they become healthy, and tears down. Skip-safe when Docker is not present.
  6. writes `report.json` and `report.md`.

A combination that selects an overlay whose `build_status` in `registry.yaml` is
not yet `implemented` is reported as SKIPPED with the milestone that will
implement it. As overlays land and flip to `implemented`, the runner picks them
up with no change here.

Skip-safe: if `copier` is unavailable or the generator template has no
`copier.yml` yet, the runner prints a notice and exits 0 unless `--strict`.

Usage:
    uv run harness/run.py --mode pairwise
    uv run harness/run.py --mode full --include db_postgres,db_redis
    uv run harness/run.py --manifest .harness-out/pairwise
    uv run harness/run.py --answers ci/answers/zero-overlay.yml
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import yaml

HARNESS_DIR = Path(__file__).resolve().parent
REPO_ROOT = HARNESS_DIR.parent
sys.path.insert(0, str(HARNESS_DIR))
sys.path.insert(0, str(REPO_ROOT))

import combinations as combos_mod  # noqa: E402
from registry_model import answers_for, load_registry  # noqa: E402

# Phase 7 task 1: real orchestrated multi-service rendering (D-036), imported
# lazily by `_topology_mod()` so a checkout without `msvc_gen/` still runs the
# `single`-only parts of the harness.

IGNORE_TREE_PARTS = {".git"}
# `.copier-answers.yml` records `_commit` and `_src_path`. In pinned `--vcs-ref`
# mode both are stable, but rendering a dirty local worktree makes Copier mint a
# throwaway snapshot commit per render, so `_commit` (and an absolute `_src_path`)
# vary run to run without the rendered content changing. These lines are
# normalized out before the determinism comparison; every other byte still counts.
ANSWERS_FILE_BASENAMES = {".copier-answers.yml"}
ANSWERS_VOLATILE_PREFIXES = ("_commit:", "_src_path:")


# ---------------------------------------------------------------------------
# generator invocation interface


@dataclasses.dataclass
class StepResult:
    name: str
    status: str  # "pass" | "fail" | "skip"
    seconds: float = 0.0
    detail: str = ""


def _topology_mod() -> Any:
    """Import `msvc_gen.topology` on first use. Raises ImportError with a clear
    message if the generator package is not importable (e.g. a stripped-down
    checkout) - callers treat that as a `fail`, not a silent `skip`, because a
    `topology != single` combo genuinely cannot render without it."""
    import msvc_gen.topology as t  # noqa: PLC0415

    return t


class CopierGenerator:
    """Renders via the `copier` CLI, matching scripts/check_determinism.py.

    With no `vcs_ref` and a local template path, Copier renders the working tree
    as-is (template-development mode). Pass `vcs_ref` for a pinned CI run (D-012).
    Tasks are skipped here; the runner drives `uv lock` itself so it is captured
    and controllable.
    """

    def __init__(self, template_src: str, vcs_ref: str | None) -> None:
        self.template_src = template_src
        self.vcs_ref = vcs_ref

    def available(self) -> tuple[bool, str]:
        if shutil.which("copier") is None:
            return False, "copier not on PATH"
        cy = Path(self.template_src) / "copier.yml"
        if not cy.is_file() and "://" not in self.template_src:
            return False, f"no copier.yml under {self.template_src}"
        return True, ""

    def render(self, answers_file: Path, dest: Path) -> StepResult:
        cmd = [
            "copier",
            "copy",
            "--force",
            "--trust",
            "--skip-tasks",
            "--data-file",
            str(answers_file),
        ]
        if self.vcs_ref:
            cmd += ["--vcs-ref", self.vcs_ref]
        cmd += [self.template_src, str(dest)]
        t0 = time.monotonic()
        proc = subprocess.run(cmd, capture_output=True, text=True)
        dt = time.monotonic() - t0
        if proc.returncode != 0:
            return StepResult("render", "fail", dt, _tail(proc.stderr or proc.stdout))
        return StepResult("render", "pass", dt)


# ---------------------------------------------------------------------------
# helpers


def _tail(text: str, n: int = 40) -> str:
    lines = (text or "").strip().splitlines()
    return "\n".join(lines[-n:])


def _file_bytes_for_digest(path: Path) -> bytes:
    if path.name in ANSWERS_FILE_BASENAMES:
        kept = [
            ln
            for ln in path.read_text().splitlines()
            if not ln.startswith(ANSWERS_VOLATILE_PREFIXES)
        ]
        return ("\n".join(kept) + "\n").encode("utf-8")
    return path.read_bytes()


def _tree_digest(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if any(part in IGNORE_TREE_PARTS for part in rel.parts):
            continue
        if path.is_file():
            out[rel.as_posix()] = hashlib.sha256(_file_bytes_for_digest(path)).hexdigest()
    return out


def _tree_diff(a: Path, b: Path) -> list[str]:
    da, db = _tree_digest(a), _tree_digest(b)
    problems: list[str] = []
    for rel in sorted(set(da) | set(db)):
        if rel not in da:
            problems.append(f"only in render 2: {rel}")
        elif rel not in db:
            problems.append(f"only in render 1: {rel}")
        elif da[rel] != db[rel]:
            problems.append(f"differs: {rel}")
    return problems


def _run(
    cmd: list[str],
    cwd: Path,
    name: str,
    timeout: int = 900,
    env: dict[str, str] | None = None,
) -> StepResult:
    t0 = time.monotonic()
    run_env = {**os.environ, **env} if env else None
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=run_env
        )
    except subprocess.TimeoutExpired:
        return StepResult(name, "fail", time.monotonic() - t0, f"timeout after {timeout}s")
    dt = time.monotonic() - t0
    if proc.returncode != 0:
        return StepResult(name, "fail", dt, _tail(proc.stderr or proc.stdout))
    return StepResult(name, "pass", dt)


# `tests_integration=true` combos use real testcontainers fixtures (D-031, Phase
# 7 task 2). On this Docker Desktop setup testcontainers' `ryuk` reaper sidecar
# fails to start (`error while creating mount source path
# '/host_mnt/.../docker.sock': operation not supported` - a known
# testcontainers-python / Docker Desktop-for-Mac bind-mount quirk, reproduced
# directly: a `db_postgres` + `tests_integration` combo ERRORs in
# `PostgresContainer.start()` with this exact message). Ryuk is only the
# orphan-container reaper for abnormal termination; each fixture already stops
# its own container via its `with ...Container(...)` context manager on normal
# exit, so disabling ryuk does not weaken cleanup for a harness run that always
# lets pytest finish. Verified: the same combo goes 10/10 green with this set.
TESTS_INTEGRATION_ENV = {"TESTCONTAINERS_RYUK_DISABLED": "true"}


def _docker_available() -> bool:
    """True only when the `docker` CLI, the Compose plugin, AND a reachable daemon
    are all present. `docker compose ls` needs the daemon, so a stopped Docker
    Desktop makes the compose boot skip rather than fail.
    """
    if shutil.which("docker") is None:
        return False
    try:
        proc = subprocess.run(
            ["docker", "compose", "ls"], capture_output=True, text=True, timeout=30
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    return proc.returncode == 0


def _resolved_compose(project_dir: Path) -> dict[str, Any] | None:
    try:
        proc = subprocess.run(
            ["docker", "compose", "config", "--format", "json"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError:
        return None


def _backing_services(project_dir: Path) -> list[str] | None:
    """Compose service names that are pulled images (no `build:` section), i.e. the
    datastore / broker containers the overlays add. Returns None if compose config
    cannot be read.
    """
    cfg = _resolved_compose(project_dir)
    if cfg is None:
        return None
    services = cfg.get("services", {})
    return sorted(name for name, s in services.items() if "build" not in s)


_HARNESS_COMPOSE = "compose.harness-boot.yml"


def _write_harness_compose(project_dir: Path, services: list[str]) -> Path | None:
    """Write a self-contained compose file for `boot_under_compose`: only the
    backing services, with host port publishing removed.

    Built from `docker compose config` (fully resolved), so it sidesteps Compose
    override-merge semantics (list fields like `ports` MERGE across `-f` files,
    they do not replace, so a `ports: []` override does not clear them). Removing
    the host binds is what keeps back-to-back combos from colliding on the fixed
    host ports (5432 / 6333 / ...) while Docker's port release lags the `down`.
    `--wait` still works: each container's healthcheck runs inside the container.
    """
    cfg = _resolved_compose(project_dir)
    if cfg is None:
        return None
    keep = {
        "services": {
            name: {k: v for k, v in s.items() if k != "ports"}
            for name, s in cfg.get("services", {}).items()
            if name in services
        }
    }
    for opt in ("volumes", "networks"):
        if opt in cfg:
            keep[opt] = cfg[opt]
    path = project_dir / _HARNESS_COMPOSE
    path.write_text(yaml.safe_dump(keep, sort_keys=True))
    return path


def boot_under_compose(project_dir: Path, timeout: int = 300) -> StepResult:
    """Bring the generated project's compose backing services up for real,
    wait for them to become healthy, then tear down.

    This is the Phase 2 gate for datastore / broker overlays: `docker compose
    config` only parses the file, this proves the assembled compose file is
    runnable (image tags pull, healthchecks pass, env wiring resolves). The app
    service (the one with a `build:` section) is excluded: building the service
    image is not what this step checks and adds failure surface. Host port
    publishing is dropped (see `_write_harness_compose`).

    Skip-safe: returns `skip` when Docker is unavailable or the compose file has
    no backing services. Always tears down with `docker compose down -v`.
    """
    name = "compose_boot"
    if not _docker_available():
        return StepResult(name, "skip", 0.0, "docker / docker compose not available")

    if not (project_dir / "docker-compose.yml").is_file():
        return StepResult(name, "skip", 0.0, "no docker-compose.yml")

    env_example = project_dir / ".env.example"
    if env_example.is_file() and not (project_dir / ".env").exists():
        (project_dir / ".env").write_text(env_example.read_text())

    services = _backing_services(project_dir)
    if services is None:
        return StepResult(name, "fail", 0.0, "`docker compose config` did not return valid JSON")
    if not services:
        return StepResult(name, "skip", 0.0, "no backing services in compose (app-only)")

    boot_file = _write_harness_compose(project_dir, services)
    if boot_file is None:
        return StepResult(name, "fail", 0.0, "could not build the harness compose file")
    files = ["-f", boot_file.name]
    t0 = time.monotonic()
    up_cmd = [
        "docker",
        "compose",
        *files,
        "up",
        "-d",
        "--wait",
        "--wait-timeout",
        str(timeout),
        *services,
    ]
    try:
        up = subprocess.run(
            up_cmd, cwd=project_dir, capture_output=True, text=True, timeout=timeout + 60
        )
        dt = time.monotonic() - t0
        if up.returncode != 0:
            logs = subprocess.run(
                ["docker", "compose", *files, "logs", "--no-color", "--tail", "60", *services],
                cwd=project_dir,
                capture_output=True,
                text=True,
                timeout=60,
            )
            detail = _tail(up.stderr or up.stdout) + "\n--- logs ---\n" + _tail(logs.stdout, 60)
            return StepResult(name, "fail", dt, detail.strip())
        return StepResult(name, "pass", dt, f"services healthy: {', '.join(services)}")
    except subprocess.TimeoutExpired:
        msg = f"`docker compose up --wait` timed out ({timeout}s)"
        return StepResult(name, "fail", time.monotonic() - t0, msg)
    finally:
        subprocess.run(
            ["docker", "compose", *files, "down", "-v", "--remove-orphans", "--timeout", "20"],
            cwd=project_dir,
            capture_output=True,
            text=True,
            timeout=120,
        )


# ---------------------------------------------------------------------------
# per-combination execution


def implemented_overlays(reg: Any) -> set[str]:
    out: set[str] = set()
    for spec in reg.options.values():
        oid = spec.get("overlay_id")
        if oid and spec.get("build_status") == "implemented":
            out.add(oid)
    return out


def milestone_for_overlays(reg: Any, overlay_ids: list[str]) -> dict[str, int]:
    by_id: dict[str, int] = {}
    for spec in reg.options.values():
        oid = spec.get("overlay_id")
        if oid:
            by_id[oid] = spec.get("milestone", 0)
    return {oid: by_id.get(oid, 0) for oid in overlay_ids}


def _selected_have_compose_service(reg: Any, selected: list[str]) -> bool:
    sel = set(selected)
    for spec in reg.options.values():
        if spec.get("overlay_id") in sel and spec.get("compose_services"):
            return True
    return False


def _boots_test_paths(reg: Any, selected: list[str]) -> dict[str, str]:
    """overlay_id -> its `boots_test` path, for the selected overlays."""
    sel = set(selected)
    out: dict[str, str] = {}
    for spec in reg.options.values():
        oid = spec.get("overlay_id")
        if oid in sel and spec.get("boots_test"):
            out[oid] = spec["boots_test"]
    return out


def boots_tests_guard(project_dir: Path, reg: Any, selected: list[str]) -> StepResult:
    """Every selected overlay's `boots_test` must exist in the rendered tree AND
    be collected by pytest with at least one test.

    This catches the class of bug where a bad `_exclude` (or a mis-gated template
    path) silently drops `tests/overlays/`, so the overlay's proves-it-boots test
    never runs and the combination goes green on the base tests alone.
    """
    name = "boots_tests"
    want = _boots_test_paths(reg, selected)
    if not want:
        return StepResult(name, "skip", 0.0, "no selected overlay declares a boots_test")

    missing_file = sorted(oid for oid, p in want.items() if not (project_dir / p).is_file())

    proc = subprocess.run(
        ["uv", "run", "pytest", "--co", "-q", "-p", "no:cacheprovider"],
        cwd=project_dir,
        capture_output=True,
        text=True,
        timeout=300,
    )
    collected: dict[str, int] = {}
    for line in proc.stdout.splitlines():
        m = re.match(r"^(.+\.py): (\d+)$", line.strip())
        if m:
            collected[m.group(1)] = int(m.group(2))

    def is_collected(rel: str) -> bool:
        target = Path(rel)
        return any(
            Path(p) == target or p.endswith("/" + rel) or p == rel
            for p, n in collected.items()
            if n >= 1
        )

    not_collected = sorted(
        oid for oid, p in want.items() if oid not in missing_file and not is_collected(p)
    )

    if missing_file or not_collected:
        detail_parts = []
        if missing_file:
            detail_parts.append(
                "boots_test file missing from rendered tree: "
                + ", ".join(f"{oid} ({want[oid]})" for oid in missing_file)
            )
        if not_collected:
            detail_parts.append(
                "boots_test present but not collected by pytest: "
                + ", ".join(f"{oid} ({want[oid]})" for oid in not_collected)
            )
        if proc.returncode not in (0, 5):
            detail_parts.append("pytest --co stderr:\n" + _tail(proc.stderr, 20))
        return StepResult(name, "fail", 0.0, "\n".join(detail_parts))

    total = sum(collected.get(p, 0) for p in want.values())
    return StepResult(
        name, "pass", 0.0, f"{len(want)} overlay boots test(s) collected, {total} test(s)"
    )


# ---------------------------------------------------------------------------
# topology (`monorepo` / `multi_repo`) orchestration - Phase 7 task 1


def _service_canon(reg: Any, answers: dict[str, Any], svc: str) -> dict[str, Any]:
    """The canonical single-service assignment for one entry in `service_names`:
    registry defaults <- shared top-level keys a `single` render also needs <-
    `services_config[svc]` - mirrors `msvc_gen.topology.effective_answers` /
    docs/services-config-schema.md §3, so `reg.selected_overlays` on the result
    matches what actually rendered into that service's directory."""
    shared_keys = ("license", "ci", "iac", "docker")
    submap = (answers.get("services_config") or {}).get(svc) or {}
    assignment = {
        **reg.base_namespace(),
        **{k: answers[k] for k in shared_keys if k in answers},
        **submap,
        "service_name": svc,
    }
    return reg.canonicalize(assignment)


def _fixup_services_config_for_v18(
    answers: dict[str, Any], service_names: list[str]
) -> dict[str, dict[str, Any]]:
    """`services_config` is a free-form `json` key that `combinations.py` pins to
    `{}` for every generated combo (registry_model.py `PINNED_FREEFORM`) - it is
    not modeled as an axis, so the harness can produce a structurally-valid-looking
    combination that is nonetheless rejected at render time by V-18 (`transport_grpc`
    needs at least one service with `api_grpc`; docs/services-config-schema.md §5).

    Mirrors what a real user is required to do: when `transport_grpc` is on and no
    submap already sets `api_grpc`, turn it on for the first service. This is a
    harness-side normalization only (never mutates `combinations.py`'s axis
    model); the record's `per_service_overlays` reflects the actual post-fixup
    selection so the report stays honest about what rendered.
    """
    services_config = {k: dict(v) for k, v in (answers.get("services_config") or {}).items()}
    if not answers.get("transport_grpc") or not service_names:
        return services_config
    if any(services_config.get(s, {}).get("api_grpc") for s in service_names):
        return services_config
    first = service_names[0]
    services_config[first] = {**services_config.get(first, {}), "api_grpc": True}
    return services_config


def render_topology(dest: Path, answers: dict[str, Any], vcs_ref: str | None) -> StepResult:
    """Render a `topology != 'single'` answers file the same way `msvc-gen new`
    does: `msvc_gen.topology.run_multi_service_new` in-process (N per-service
    Copier renders in `service_names` order + the root wiring layer), not a
    single degenerate Copier tree."""
    name = "render"
    t0 = time.monotonic()
    try:
        topo = _topology_mod()
        topo.run_multi_service_new(
            template_src=str(REPO_ROOT),
            output=dest,
            data=answers,
            vcs_ref=vcs_ref,
            skip_tasks=True,
            force=True,
            dry_run=False,
            quiet=True,
        )
    except SystemExit as exc:  # TopologyError is a SystemExit subclass
        return StepResult(name, "fail", time.monotonic() - t0, str(exc) or repr(exc))
    except Exception as exc:  # noqa: BLE001 - report, don't crash the whole gate
        return StepResult(name, "fail", time.monotonic() - t0, f"{type(exc).__name__}: {exc}")
    return StepResult(name, "pass", time.monotonic() - t0)


def _run_project_checks(
    project_dir: Path,
    reg: Any,
    selected: list[str],
    do_lock: bool,
    tests_integration: bool,
    label: str = "",
) -> list[StepResult]:
    """`uv lock` + `uv sync` + `uv run pytest` + the boots-tests guard for ONE
    project directory (a `single` render, or one `services/<svc>/` of a topology
    render). `label` namespaces the step names so a multi-service record's steps
    stay attributable to their service."""
    suffix = f"[{label}]" if label else ""
    steps: list[StepResult] = []
    if do_lock:
        steps.append(_run(["uv", "lock"], project_dir, f"uv_lock{suffix}", timeout=600))
    if not steps or steps[-1].status == "pass":
        steps.append(_run(["uv", "sync"], project_dir, f"uv_sync{suffix}", timeout=600))
    if steps[-1].status == "pass":
        # Phase 7 task 2: real containers for `tests_integration` (see
        # TESTS_INTEGRATION_ENV above the `boot_under_compose` skip-safety note).
        pytest_env = TESTS_INTEGRATION_ENV if tests_integration else None
        steps.append(
            _run(
                ["uv", "run", "pytest", "-q"],
                project_dir,
                f"pytest{suffix}",
                timeout=900,
                env=pytest_env,
            )
        )
    if steps[-1].status == "pass" and selected:
        guard = boots_tests_guard(project_dir, reg, selected)
        steps.append(dataclasses.replace(guard, name=f"boots_tests{suffix}"))
    return steps


def contract_check(
    root_dir: Path, topo: Any, topology: str, service_names: list[str], grpc_services: list[str]
) -> StepResult:
    """Real wiring for `tests_contract` (Phase 7 task 3;
    docs/grpc-contract-tests.md), run against the rendered root `proto/` tree:

    - `buf lint`, for real, when the `buf` binary is on PATH (skip-safe
      otherwise - not installed in every environment).
    - the no-toolchain descriptor-set fallback (`proto/gen_descriptor_set.py`),
      always run for real: executed with `uv run` from a service directory that
      carries `grpcio-tools` (the `api_grpc` overlay's dev-dep - the root layer
      itself has no Python project of its own), asserting a non-empty
      `descriptor.pb` and that regenerating it twice is byte-identical (the
      determinism half of D-009's "regenerate, then `git diff --exit-code`"
      contract - there is no prior git history to diff against in a fresh
      render, so this checks the generator is a pure function of the same
      `proto/` tree, which is the property the CI guard actually depends on).
    """
    name = "contract"
    proto_dir = root_dir / "proto"
    if not proto_dir.is_dir() or not any(proto_dir.rglob("*.proto")):
        return StepResult(name, "skip", 0.0, "no proto/ tree rendered")

    t0 = time.monotonic()
    detail: list[str] = []

    if shutil.which("buf"):
        proc = subprocess.run(
            ["buf", "lint"], cwd=root_dir, capture_output=True, text=True, timeout=60
        )
        if proc.returncode != 0:
            msg = "buf lint:\n" + _tail(proc.stderr or proc.stdout)
            return StepResult(name, "fail", time.monotonic() - t0, msg)
        detail.append("buf lint: pass")
    else:
        detail.append("buf lint: skip (buf not on PATH)")

    gen_script = proto_dir / "gen_descriptor_set.py"
    if not gen_script.is_file():
        detail.append("descriptor-set fallback: skip (proto/gen_descriptor_set.py not rendered)")
        return StepResult(name, "pass", time.monotonic() - t0, "; ".join(detail))

    svc_dir = next(
        (
            topo.service_dest(root_dir, topology, s)
            for s in grpc_services
            if s in service_names
        ),
        None,
    )
    if svc_dir is None or not (svc_dir / "pyproject.toml").is_file():
        detail.append("descriptor-set fallback: skip (no service ships grpcio-tools)")
        return StepResult(name, "pass", time.monotonic() - t0, "; ".join(detail))

    descriptor = proto_dir / "descriptor.pb"
    run1 = subprocess.run(
        ["uv", "run", "python", str(gen_script)],
        cwd=svc_dir,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if run1.returncode != 0:
        return StepResult(
            name,
            "fail",
            time.monotonic() - t0,
            "gen_descriptor_set.py:\n" + _tail(run1.stderr or run1.stdout),
        )
    if not descriptor.is_file() or descriptor.stat().st_size == 0:
        return StepResult(name, "fail", time.monotonic() - t0, "descriptor.pb missing/empty")
    before = descriptor.read_bytes()

    run2 = subprocess.run(
        ["uv", "run", "python", str(gen_script)],
        cwd=svc_dir,
        capture_output=True,
        text=True,
        timeout=120,
    )
    after = descriptor.read_bytes() if descriptor.is_file() else b""
    if run2.returncode != 0 or before != after:
        return StepResult(
            name,
            "fail",
            time.monotonic() - t0,
            "descriptor-set snapshot not byte-stable across regeneration",
        )
    detail.append(f"descriptor-set fallback: pass ({len(before)} bytes, regen byte-stable)")
    return StepResult(name, "pass", time.monotonic() - t0, "; ".join(detail))


def run_combination(
    reg: Any,
    answers_path: Path,
    generator: CopierGenerator,
    do_lock: bool,
    do_docker: bool,
    do_compose_boot: bool = False,
    compose_timeout: int = 300,
    treat_implemented: set[str] | None = None,
) -> dict[str, Any]:
    answers = yaml.safe_load(answers_path.read_text()) or {}
    canon = reg.canonicalize({**reg.base_namespace(), **answers})
    selected = reg.selected_overlays(canon)
    digest = hashlib.sha256(answers_path.read_bytes()).hexdigest()[:12]
    is_topology = str(canon.get("topology", "single")) != "single"

    record: dict[str, Any] = {
        "hash": digest,
        "answers_file": str(answers_path),
        "selected_overlays": selected,
        "steps": [],
        "status": "pass",
    }

    # Phase 7 task 1: topology != single actually orchestrates N per-service
    # renders + a root layer (msvc_gen.topology, D-036), not one degenerate
    # Copier tree. Compute each service's own selected-overlay set (needed for
    # the unmet-overlay gate and the per-service boots-tests guard) and apply
    # the V-18 harness-side fixup (see `_fixup_services_config_for_v18`).
    service_names: list[str] = []
    services_config: dict[str, dict[str, Any]] = {}
    per_service_selected: dict[str, list[str]] = {}
    all_selected = set(selected)
    if is_topology:
        topo = _topology_mod()
        try:
            service_names = topo.normalize_service_names(answers.get("service_names"))
        except SystemExit as exc:
            record["status"] = "fail"
            record["steps"] = [dataclasses.asdict(StepResult("render", "fail", 0.0, str(exc)))]
            return record
        services_config = _fixup_services_config_for_v18(answers, service_names)
        answers = {**answers, "services_config": services_config}
        for svc in service_names:
            svc_canon = _service_canon(reg, answers, svc)
            per_service_selected[svc] = reg.selected_overlays(svc_canon)
            all_selected.update(per_service_selected[svc])
        record["per_service_overlays"] = per_service_selected

    # `--treat-implemented` forces named overlays through the full pipeline before
    # their registry `build_status` is flipped, so an overlay can be gated on a
    # green harness run.
    impl = implemented_overlays(reg) | (treat_implemented or set())
    unmet = [o for o in all_selected if o not in impl]
    if unmet:
        record["status"] = "skip"
        by_milestone = sorted(milestone_for_overlays(reg, sorted(unmet)).items())
        record["skip_reason"] = "overlay(s) not yet implemented: " + ", ".join(
            f"{o} (milestone {m})" for o, m in by_milestone
        )
        return record

    ok, why = generator.available()
    if not ok:
        record["status"] = "skip"
        record["skip_reason"] = f"generator unavailable: {why}"
        return record

    steps: list[StepResult] = []
    with tempfile.TemporaryDirectory(prefix=f"harness-{digest}-") as tmp:
        d1, d2 = Path(tmp) / "r1", Path(tmp) / "r2"

        if is_topology:
            r1 = render_topology(d1, answers, generator.vcs_ref)
        else:
            r1 = generator.render(answers_path, d1)
        steps.append(r1)
        if r1.status == "pass":
            if is_topology:
                r2 = render_topology(d2, answers, generator.vcs_ref)
            else:
                r2 = generator.render(answers_path, d2)
            steps.append(dataclasses.replace(r2, name="render_2"))
            if r2.status == "pass":
                problems = _tree_diff(d1, d2)
                steps.append(
                    StepResult(
                        "determinism",
                        "pass" if not problems else "fail",
                        0.0,
                        "" if not problems else "\n".join(problems[:20]),
                    )
                )

        if all(s.status == "pass" for s in steps):
            if is_topology:
                topo = _topology_mod()
                topology = str(canon.get("topology"))
                for svc in service_names:
                    dest = topo.service_dest(d1, topology, svc)
                    steps.extend(
                        _run_project_checks(
                            dest,
                            reg,
                            per_service_selected.get(svc, []),
                            do_lock,
                            bool(_service_canon(reg, answers, svc).get("tests_integration")),
                            label=svc,
                        )
                    )

                if do_docker and all(s.status == "pass" for s in steps):
                    if shutil.which("docker"):
                        steps.append(
                            _run(
                                ["docker", "compose", "config", "-q"],
                                d1,
                                "root_compose_config",
                                timeout=120,
                            )
                        )
                    else:
                        steps.append(
                            StepResult("root_compose_config", "skip", 0.0, "docker not on PATH")
                        )
                    if do_compose_boot and steps[-1].status == "pass":
                        steps.append(boot_under_compose(d1, timeout=compose_timeout))

                if all(s.status == "pass" for s in steps) and canon.get("tests_contract"):
                    grpc_services = [
                        s for s in service_names if "api_grpc" in per_service_selected.get(s, [])
                    ]
                    steps.append(contract_check(d1, topo, topology, service_names, grpc_services))
            else:
                steps.extend(
                    _run_project_checks(
                        d1, reg, selected, do_lock, bool(canon.get("tests_integration"))
                    )
                )

                if (
                    do_docker
                    and bool(canon.get("docker"))
                    and all(s.status == "pass" for s in steps)
                ):
                    env_example = d1 / ".env.example"
                    if env_example.is_file() and not (d1 / ".env").exists():
                        (d1 / ".env").write_text(env_example.read_text())
                    if shutil.which("docker"):
                        steps.append(
                            _run(
                                ["docker", "compose", "config", "-q"],
                                d1,
                                "compose_config",
                                timeout=120,
                            )
                        )
                    else:
                        steps.append(
                            StepResult("compose_config", "skip", 0.0, "docker not on PATH")
                        )

                    # Phase 2 gate: datastore / broker overlays must actually boot
                    # under `docker compose up`, not just validate.
                    if (
                        do_compose_boot
                        and steps[-1].status == "pass"
                        and _selected_have_compose_service(reg, selected)
                    ):
                        steps.append(boot_under_compose(d1, timeout=compose_timeout))

    record["steps"] = [dataclasses.asdict(s) for s in steps]
    if any(s.status == "fail" for s in steps):
        record["status"] = "fail"
    return record


# ---------------------------------------------------------------------------
# orchestration


def _gather_answers(args: argparse.Namespace) -> tuple[list[Path], Path | None, dict[str, Any]]:
    """Return (answers_files, out_dir, generation_summary)."""
    if args.answers:
        return [Path(args.answers)], None, {"source": "single answers file"}

    if args.manifest:
        mdir = Path(args.manifest)
        manifest = json.loads((mdir / "manifest.json").read_text())
        files = [mdir / f["file"] for f in manifest["files"]]
        return files, mdir, {"source": f"manifest {mdir}", "summary": manifest.get("summary", {})}

    # Generate a fresh set with combinations.py, into a temp dir we keep.
    out_dir = Path(args.out) if args.out else Path(tempfile.mkdtemp(prefix="harness-combos-"))
    reg = load_registry(args.registry)
    coupled, independent, pin_values = combos_mod.select_axes(reg, args.include, {})
    if args.mode == "full":
        result = combos_mod.run_full(
            reg, coupled, independent, pin_values, args.max_nodes, args.max_materialize
        )
    elif args.mode == "singletons":
        result = combos_mod.run_singletons(reg, coupled, independent, pin_values, args.max_nodes)
    else:
        variable = coupled + independent
        variable.sort(key=lambda a: (a.group_order, a.key))
        result = combos_mod.run_pairwise(reg, variable, pin_values, args.max_nodes)
        # Always fold in the per-overlay singletons so a newly `implemented`
        # overlay executes even if the pairwise greedy never isolated it
        # (the boots-test DoD: overlay alone on the base + overlay plus requires).
        if not args.no_singletons:
            singles = combos_mod.run_singletons(
                reg, coupled, independent, pin_values, args.max_nodes
            )

            def _answers_key(c: dict[str, Any]) -> str:
                return json.dumps(answers_for(reg, c), sort_keys=True, default=str)

            have = {_answers_key(c) for c in result["combinations"]}
            added = [c for c in singles["combinations"] if _answers_key(c) not in have]
            result["combinations"].extend(added)
            result["singletons_added"] = len(added)

    ns = argparse.Namespace(
        mode=args.mode,
        include=args.include,
        pin={},
        max_nodes=args.max_nodes,
        max_materialize=args.max_materialize,
    )
    manifest = combos_mod.write_output(reg, out_dir, result, ns)
    files = [out_dir / f["file"] for f in manifest["files"]]
    if args.mode == "full" and not result.get("materialized"):
        print(
            f"[harness] full set not materialized: {result['full_count']} combinations "
            f"(> --max-materialize {args.max_materialize}). Narrow with --include / --pin, "
            f"raise --max-materialize, or use --mode pairwise.",
            file=sys.stderr,
        )
    return (
        files,
        out_dir,
        {"source": f"{args.mode} (generated)", "summary": manifest.get("summary", {})},
    )


def write_reports(out: Path, report: dict[str, Any]) -> None:
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    lines = ["# Harness run report", ""]
    s = report["summary"]
    lines.append(f"- generated from: {report['generation']['source']}")
    lines.append(
        f"- combinations: {s['total']}  pass: {s['pass']}  fail: {s['fail']}  skip: {s['skip']}"
    )
    lines.append(f"- overall: **{report['status'].upper()}**")
    lines.append("")
    lines.append("| combination | overlays | status | notes |")
    lines.append("| --- | --- | --- | --- |")
    for r in report["combinations"]:
        overlays = ", ".join(r["selected_overlays"]) or "(base only)"
        note = r.get("skip_reason", "")
        if not note and r["status"] == "fail":
            note = "; ".join(
                f"{st['name']}:{st['status']}"
                for st in r.get("steps", [])
                if st["status"] == "fail"
            )
        lines.append(f"| `{r['hash']}` | {overlays} | {r['status']} | {note} |")
    lines.append("")
    (out / "report.md").write_text("\n".join(lines))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--mode", choices=["pairwise", "full", "singletons"], default="pairwise")
    p.add_argument(
        "--no-singletons",
        action="store_true",
        help="pairwise mode: do not fold in the per-overlay singleton combinations",
    )
    p.add_argument(
        "--treat-implemented",
        type=lambda s: {x.strip() for x in s.split(",") if x.strip()},
        default=set(),
        help="comma-separated overlay ids to run through the full pipeline even though "
        "their registry build_status is not yet `implemented` (pre-flip verification)",
    )
    p.add_argument("--manifest", help="run an existing combinations manifest directory")
    p.add_argument("--answers", help="run a single answers file")
    p.add_argument("--registry", type=Path, default=REPO_ROOT / "registry.yaml")
    p.add_argument("--template-src", default=str(REPO_ROOT), help="Copier template path or URL")
    p.add_argument(
        "--vcs-ref",
        default=None,
        help="pin the template ref (D-012); omit for local dirty worktree",
    )
    p.add_argument(
        "--include", type=lambda s: [x.strip() for x in s.split(",") if x.strip()], default=None
    )
    p.add_argument("--out", default=None, help="directory for generated combos + reports")
    p.add_argument("--max-nodes", type=int, default=5_000_000)
    p.add_argument("--max-materialize", type=int, default=200)
    p.add_argument(
        "--no-lock", action="store_true", help="skip `uv lock` (offline; assumes a lock exists)"
    )
    p.add_argument(
        "--no-docker",
        action="store_true",
        help="skip `docker compose config` and the compose boot",
    )
    p.add_argument(
        "--no-compose-boot",
        action="store_true",
        help="skip `docker compose up` boot; keep `docker compose config`",
    )
    p.add_argument(
        "--compose-timeout",
        type=int,
        default=300,
        help="seconds to wait for compose services to become healthy",
    )
    p.add_argument(
        "--strict", action="store_true", help="exit non-zero when the generator is unavailable"
    )
    p.add_argument("--report-dir", default=None, help="where to write report.json / report.md")
    args = p.parse_args(argv)

    reg = load_registry(args.registry)
    generator = CopierGenerator(args.template_src, args.vcs_ref)

    ok, why = generator.available()
    if not ok and not args.answers:
        msg = f"[harness] generator unavailable: {why}"
        if args.strict:
            print(msg, file=sys.stderr)
            return 1
        print(msg + " -> skip (Phase 1 slot)")
        return 0

    answers_files, out_dir, gen_summary = _gather_answers(args)
    report_dir = (
        Path(args.report_dir) if args.report_dir else (out_dir or Path.cwd() / ".harness-report")
    )

    do_compose_boot = not args.no_docker and not args.no_compose_boot and _docker_available()

    combinations: list[dict[str, Any]] = []
    for af in answers_files:
        rec = run_combination(
            reg,
            af,
            generator,
            do_lock=not args.no_lock,
            do_docker=not args.no_docker,
            do_compose_boot=do_compose_boot,
            compose_timeout=args.compose_timeout,
            treat_implemented=args.treat_implemented,
        )
        combinations.append(rec)
        line = f"[harness] {rec['hash']} {rec['status']}"
        if rec.get("skip_reason"):
            line += f"  ({rec['skip_reason']})"
        print(line)

    combinations.sort(key=lambda r: r["hash"])
    tally = {"total": len(combinations), "pass": 0, "fail": 0, "skip": 0}
    for r in combinations:
        tally[r["status"]] += 1

    overall = "fail" if tally["fail"] else "pass"
    report = {
        "status": overall,
        "summary": tally,
        "generation": gen_summary,
        "combinations": combinations,
    }
    write_reports(report_dir, report)
    print(f"\n[harness] {tally}  overall={overall.upper()}  report={report_dir}")

    return 1 if overall == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Smoke tests for the DevOps scripts. Fast, offline, no copier/network."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _run(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )


def test_validate_registry_passes_on_real_registry() -> None:
    res = _run("scripts/validate_registry.py", "registry.yaml")
    assert res.returncode == 0, res.stderr


def test_validate_registry_flags_broken_registry(tmp_path: Path) -> None:
    bad = tmp_path / "registry.yaml"
    bad.write_text("meta: {}\noverlay_order: [x]\ngroups: {}\noptions: {}\n")
    res = _run("scripts/validate_registry.py", str(bad))
    assert res.returncode == 1
    assert "overlay_order id has no option" in res.stderr


def test_gen_copier_yml_check_passes_when_in_sync() -> None:
    """copier.yml is committed in sync with registry.yaml; --check must pass."""
    res = _run("scripts/gen_copier_yml.py", "--check", "registry.yaml")
    assert res.returncode == 0, res.stderr


def test_gen_copier_yml_detects_drift(tmp_path: Path) -> None:
    """A registry change not reflected in the committed copier.yml is drift (exit 1)."""
    reg = (REPO / "registry.yaml").read_text()
    assert 'prompt: "Infrastructure-as-code output"' in reg
    drifted = tmp_path / "registry.yaml"
    drifted.write_text(
        reg.replace('prompt: "Infrastructure-as-code output"', 'prompt: "IaC output changed"', 1)
    )
    res = _run("scripts/gen_copier_yml.py", "--check", str(drifted))
    assert res.returncode == 1
    assert "out of sync" in res.stderr


def test_gen_copier_yml_is_deterministic() -> None:
    """Rendering twice from the same registry yields byte-identical output."""
    a = _run("scripts/gen_copier_yml.py", "--stdout", "registry.yaml")
    b = _run("scripts/gen_copier_yml.py", "--stdout", "registry.yaml")
    assert a.returncode == 0 and b.returncode == 0, a.stderr + b.stderr
    assert a.stdout == b.stdout
    assert a.stdout.startswith("# ===")


def test_check_determinism_skips_when_no_copier_yml(tmp_path: Path) -> None:
    """With no copier.yml under --template and no --strict, the check skips clean."""
    (tmp_path / "answers").mkdir()
    (tmp_path / "answers" / "a.yml").write_text("x: 1\n")
    res = _run(
        "scripts/check_determinism.py",
        "--template",
        str(tmp_path),
        "--answers-dir",
        str(tmp_path / "answers"),
    )
    assert res.returncode == 0, res.stderr
    assert "skip" in res.stdout


def test_check_determinism_strict_fails_when_no_copier_yml(tmp_path: Path) -> None:
    res = _run(
        "scripts/check_determinism.py",
        "--template",
        str(tmp_path),
        "--answers-dir",
        str(tmp_path),
        "--strict",
    )
    assert res.returncode == 1


def test_check_determinism_runs_on_bundled_fixture() -> None:
    """The fixture template has a copier.yml, so the check runs (not skips) and
    two renders are byte-identical."""
    res = _run(
        "scripts/check_determinism.py",
        "--template",
        "tests/fixtures/determinism_fixture",
        "--answers-dir",
        "tests/fixtures/determinism_fixture/answers",
        "--strict",
    )
    assert res.returncode == 0, res.stderr
    assert "skip" not in res.stdout
    assert "ok" in res.stdout

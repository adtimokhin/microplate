"""Regression guard for the GENERATED copier.yml.

The zero-overlay answers file cannot catch `_exclude` bugs that only bite when an
overlay is selected (it produces no `tests/overlays/`, no gated subtree). This
renders an overlay-selecting fixture (`otel_tracing=true`) and asserts:

  * the proves-it-boots subtree `tests/overlays/` survives (a bare `overlays`
    entry in `_exclude` silently ate it once, 2026-09-08),
  * the `_fragments/` partial dir does NOT leak into the output,
  * the gated overlay subtree renders.

Offline: `copier copy --skip-tasks`, no `uv`/network. Skips if `copier` is absent.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
ANSWERS = REPO / "ci" / "answers" / "otel-only.yml"

pytestmark = pytest.mark.skipif(shutil.which("copier") is None, reason="copier not on PATH")


@pytest.fixture(scope="module")
def rendered(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("otel-render")
    # regenerate copier.yml from registry.yaml first, so the test reflects HEAD
    subprocess.run(
        [sys.executable, "scripts/gen_copier_yml.py"], cwd=REPO, check=True, capture_output=True
    )
    subprocess.run(
        [
            "copier",
            "copy",
            "--force",
            "--trust",
            "--skip-tasks",
            "--defaults",
            "--data-file",
            str(ANSWERS),
            str(REPO),
            str(out),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return out


def test_boots_test_subtree_survives(rendered: Path) -> None:
    boots = rendered / "tests" / "overlays" / "test_otel_tracing_boots.py"
    assert boots.is_file(), "tests/overlays/ boots-test subtree was excluded from the render"


def test_fragments_dir_not_leaked(rendered: Path) -> None:
    leaked = [p for p in rendered.rglob("_fragments") if ".git" not in p.parts]
    assert not leaked, f"_fragments/ leaked into the generated project: {leaked}"


def test_gated_overlay_subtree_rendered(rendered: Path) -> None:
    assert (rendered / "otel_svc" / "observability" / "otel" / "tracing.py").is_file()

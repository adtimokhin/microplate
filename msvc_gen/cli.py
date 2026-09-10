"""msvc-gen command line entrypoint.

A thin wrapper over Copier. All component selection is Copier + ``registry.yaml``;
this module only resolves the template source, pins an explicit ``vcs_ref``
(D-012), and forwards a complete, non-interactive answer set. It never prompts,
never guesses, and never infers an answer.

Commands:
    msvc-gen new     --output DIR [--answers-file F] [--data k=v ...]
    msvc-gen update  --output DIR [--answers-file F] [--data k=v ...]
"""

from __future__ import annotations

import argparse
import os
from collections.abc import Sequence
from pathlib import Path

import copier
import yaml

from . import __version__

# Pre-v1 the template repo iterates on `main` (scope section 7). Releases use
# semver tags. The CLI ALWAYS passes an explicit ref (D-012); it never relies on
# Copier's "highest PEP 440 tag" default.
DEFAULT_VCS_REF = "main"

# The canonical private template repo URL is owned by DevOps & Distribution.
# Until packaging wires it in, a source checkout is detected automatically and a
# local path / URL can be passed with --template-src or MSVC_GEN_TEMPLATE_SRC.
DEFAULT_TEMPLATE_SRC = "git+ssh://git@github.com/ORG/microservice-boilerplate.git"

_ENV_TEMPLATE_SRC = "MSVC_GEN_TEMPLATE_SRC"
_ENV_VCS_REF = "MSVC_GEN_VCS_REF"


class CliError(SystemExit):
    """User-facing error; argparse-style exit with a message."""


def _bundled_template_root() -> Path | None:
    """Return the repo root when running from a source checkout, else None."""

    root = Path(__file__).resolve().parent.parent
    return root if (root / "copier.yml").is_file() else None


def _resolve_template_src(explicit: str | None) -> str:
    if explicit:
        return explicit
    env = os.environ.get(_ENV_TEMPLATE_SRC)
    if env:
        return env
    bundled = _bundled_template_root()
    if bundled is not None:
        return str(bundled)
    return DEFAULT_TEMPLATE_SRC


def _resolve_vcs_ref(explicit: str | None) -> str:
    return explicit or os.environ.get(_ENV_VCS_REF) or DEFAULT_VCS_REF


def _parse_data_pairs(pairs: Sequence[str]) -> dict[str, object]:
    data: dict[str, object] = {}
    for pair in pairs:
        if "=" not in pair:
            raise CliError(f"--data expects key=value, got: {pair!r}")
        key, _, raw = pair.partition("=")
        data[key.strip()] = yaml.safe_load(raw)
    return data


def _load_answers_file(path: str | None) -> dict[str, object]:
    if not path:
        return {}
    p = Path(path).expanduser()
    if not p.is_file():
        raise CliError(f"answers file not found: {p}")
    loaded = yaml.safe_load(p.read_text())
    if loaded is None:
        return {}
    if not isinstance(loaded, dict):
        raise CliError(f"answers file must be a YAML mapping: {p}")
    # A .copier-answers.yml carries _src_path / _commit; drop Copier internals.
    return {k: v for k, v in loaded.items() if not str(k).startswith("_")}


def _merge_data(answers_file: str | None, data_pairs: Sequence[str]) -> dict[str, object]:
    merged: dict[str, object] = {}
    merged.update(_load_answers_file(answers_file))
    merged.update(_parse_data_pairs(data_pairs))  # explicit --data wins
    return merged


def _is_multi_service(data: dict[str, object]) -> bool:
    return str(data.get("topology", "single")) != "single"


def _manifest_data(output: Path) -> dict[str, object]:
    """Read a root multi-service manifest (`.copier-answers.yml` at `output`),
    or an empty dict if there is none. The manifest is plain YAML written by
    `msvc_gen.topology`; `_load_answers_file` strips Copier internals."""

    manifest = output / ".copier-answers.yml"
    return _load_answers_file(str(manifest)) if manifest.is_file() else {}


def cmd_new(args: argparse.Namespace) -> int:
    dst = Path(args.output).expanduser()
    data = _merge_data(args.answers_file, args.data)
    if _is_multi_service(data):
        # Multi-service topology (D-036): one single-service render per service
        # plus a thin root layer. cli.py's single-service path below is untouched.
        from .topology import run_multi_service_new

        return run_multi_service_new(
            template_src=_resolve_template_src(args.template_src),
            output=dst,
            data=data,
            vcs_ref=_resolve_vcs_ref(args.vcs_ref),
            skip_tasks=args.skip_tasks,
            force=args.force,
            dry_run=args.dry_run,
            quiet=args.quiet,
        )
    copier.run_copy(
        _resolve_template_src(args.template_src),
        str(dst),
        data=data,
        vcs_ref=_resolve_vcs_ref(args.vcs_ref),
        defaults=True,  # non-interactive; a question with no default is a hard error
        unsafe=True,  # the template ships list-form _tasks (uv lock)
        skip_tasks=args.skip_tasks,
        overwrite=args.force,
        pretend=args.dry_run,
        quiet=args.quiet,
    )
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    dst = Path(args.output).expanduser()
    data = _merge_data(args.answers_file, args.data)
    # Multi-service if the passed answers say so, or the target carries a
    # multi-service root manifest. Explicit --data / --answers-file wins.
    manifest = _manifest_data(dst)
    effective = {**manifest, **data}
    if _is_multi_service(effective):
        from .topology import run_multi_service_update

        return run_multi_service_update(
            output=dst,
            data=effective,
            vcs_ref=_resolve_vcs_ref(args.vcs_ref),
            skip_tasks=args.skip_tasks,
            dry_run=args.dry_run,
            quiet=args.quiet,
            conflict=args.conflict,
        )
    copier.run_update(
        str(dst),
        data=data,
        vcs_ref=_resolve_vcs_ref(args.vcs_ref),
        defaults=True,
        unsafe=True,
        skip_tasks=args.skip_tasks,
        # `copier update` always rewrites template-managed files; the three-way
        # merge preserves the user's own edits and marks real conflicts.
        overwrite=True,
        pretend=args.dry_run,
        quiet=args.quiet,
        conflict=args.conflict,
    )
    return 0


def _add_common(sub: argparse.ArgumentParser) -> None:
    sub.add_argument(
        "-o",
        "--output",
        required=True,
        metavar="DIR",
        help="target directory for the service (e.g. ./my-service or ~/Desktop/my-service)",
    )
    sub.add_argument(
        "--answers-file",
        metavar="FILE",
        help="YAML file of answers for non-interactive generation",
    )
    sub.add_argument(
        "--data",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="single answer, repeatable; overrides the answers file",
    )
    sub.add_argument(
        "--vcs-ref",
        metavar="REF",
        help=f"template git ref (tag/branch/commit); default {DEFAULT_VCS_REF!r} "
        f"or ${_ENV_VCS_REF}",
    )
    sub.add_argument(
        "--template-src",
        metavar="SRC",
        help=f"template path or git URL; default: source checkout, else ${_ENV_TEMPLATE_SRC}",
    )
    sub.add_argument("--skip-tasks", action="store_true", help="do not run post-generation tasks")
    sub.add_argument("--force", action="store_true", help="overwrite existing files without asking")
    sub.add_argument("--dry-run", action="store_true", help="render nothing to disk")
    sub.add_argument("--quiet", action="store_true", help="suppress Copier output")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="msvc-gen", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    new = subparsers.add_parser("new", help="generate a new service")
    _add_common(new)
    new.set_defaults(func=cmd_new)

    update = subparsers.add_parser("update", help="update a generated service to a newer template")
    _add_common(update)
    update.add_argument(
        "--conflict",
        choices=["inline", "rej"],
        default="inline",
        help="how to mark unresolved update hunks",
    )
    update.set_defaults(func=cmd_update)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

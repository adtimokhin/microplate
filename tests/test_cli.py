"""Unit tests for the msvc-gen CLI plumbing. Offline, no copier invocation."""

from __future__ import annotations

import pytest

from msvc_gen import cli


def test_parse_data_pairs_yaml_typed() -> None:
    out = cli._parse_data_pairs(["service_name=billing-api", "otel_tracing=true", "n=3"])
    assert out == {"service_name": "billing-api", "otel_tracing": True, "n": 3}


def test_parse_data_pairs_rejects_missing_equals() -> None:
    with pytest.raises(SystemExit):
        cli._parse_data_pairs(["nope"])


def test_load_answers_file_strips_copier_internals(tmp_path) -> None:
    f = tmp_path / "answers.yml"
    f.write_text("_commit: v1\n_src_path: x\nservice_name: svc\nlicense: mit\n")
    assert cli._load_answers_file(str(f)) == {"service_name": "svc", "license": "mit"}


def test_load_answers_file_missing_is_error() -> None:
    with pytest.raises(SystemExit):
        cli._load_answers_file("/no/such/answers.yml")


def test_merge_data_cli_overrides_file(tmp_path) -> None:
    f = tmp_path / "a.yml"
    f.write_text("service_name: from-file\nlicense: mit\n")
    merged = cli._merge_data(str(f), ["service_name=from-cli"])
    assert merged == {"service_name": "from-cli", "license": "mit"}


def test_resolve_vcs_ref_precedence(monkeypatch) -> None:
    monkeypatch.delenv("MSVC_GEN_VCS_REF", raising=False)
    assert cli._resolve_vcs_ref(None) == cli.DEFAULT_VCS_REF
    assert cli._resolve_vcs_ref("v1.2.3") == "v1.2.3"
    monkeypatch.setenv("MSVC_GEN_VCS_REF", "env-ref")
    assert cli._resolve_vcs_ref(None) == "env-ref"
    assert cli._resolve_vcs_ref("explicit") == "explicit"


def test_bundled_template_src_is_the_repo_checkout() -> None:
    # Running from a source checkout: copier.yml sits next to msvc_gen/.
    assert cli._resolve_template_src(None).endswith("microservice-boilerplate")


def test_parser_requires_output() -> None:
    parser = cli.build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["new"])


def test_parser_new_roundtrip() -> None:
    parser = cli.build_parser()
    args = parser.parse_args(["new", "-o", "/tmp/x", "--data", "service_name=svc"])
    assert args.command == "new"
    assert args.output == "/tmp/x"
    assert args.data == ["service_name=svc"]
    assert args.func is cli.cmd_new

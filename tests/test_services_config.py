"""Tests for validate_registry.validate_services_config (D-005 / D-017 / D-036).

Offline, pure. Exercises the multi-service `services_config` submap rules
V-15..V-20 plus the per-service replay of V-2..V-14. Schema:
docs/services-config-schema.md.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "validate_registry", REPO / "scripts" / "validate_registry.py"
)
assert _spec and _spec.loader
_vr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_vr)

validate_services_config = _vr.validate_services_config
REG = REPO / "registry.yaml"


def _check(answers: dict[str, Any]) -> list[str]:
    return validate_services_config(answers, REG)


def test_single_topology_is_a_noop() -> None:
    assert _check({"topology": "single"}) == []
    assert _check({}) == []


def test_valid_monorepo_two_services_clean() -> None:
    answers = {
        "topology": "monorepo",
        "service_names": ["api", "worker"],
        "transport_grpc": True,
        "transport_rabbitmq": False,
        "services_config": {
            "api": {"api_grpc": True, "db_postgres": True, "tool_scaffold": True},
            "worker": {"db_postgres": True, "messaging_rabbitmq": True, "otel_tracing": True},
        },
    }
    assert _check(answers) == []


def test_v15_services_config_key_not_in_service_names() -> None:
    answers = {
        "topology": "monorepo",
        "service_names": ["api"],
        "services_config": {"api": {}, "ghost": {"db_redis": True}},
    }
    problems = _check(answers)
    assert any("V-15" in p and "ghost" in p for p in problems)


def test_v16_names_collide_after_normalization() -> None:
    # '-' -> '_' makes these collide; the regex also forbids '_', so use two
    # names that normalize identically only via the hyphen swap is impossible -
    # instead assert the check is wired by feeding a duplicate outright.
    answers = {
        "topology": "monorepo",
        "service_names": ["api", "api"],
        "services_config": {},
    }
    problems = _check(answers)
    assert any("V-16" in p for p in problems)


def test_v17_unknown_submap_key() -> None:
    answers = {
        "topology": "monorepo",
        "service_names": ["api"],
        "services_config": {"api": {"topology": "single", "nonsense": True}},
    }
    problems = _check(answers)
    assert any("V-17" in p and "topology" in p for p in problems)
    assert any("V-17" in p and "nonsense" in p for p in problems)


def test_v18_grpc_transport_without_any_grpc_server() -> None:
    answers = {
        "topology": "monorepo",
        "service_names": ["api", "worker"],
        "transport_grpc": True,
        "services_config": {"api": {"db_postgres": True}, "worker": {}},
    }
    problems = _check(answers)
    assert any("V-18" in p for p in problems)


def test_v18_satisfied_when_one_service_exposes_grpc() -> None:
    answers = {
        "topology": "monorepo",
        "service_names": ["api", "worker"],
        "transport_grpc": True,
        "services_config": {"api": {"api_grpc": True}, "worker": {}},
    }
    assert not any("V-18" in p for p in _check(answers))


def test_v19_empty_service_names() -> None:
    answers = {"topology": "multi_repo", "service_names": [], "services_config": {}}
    problems = _check(answers)
    assert any("V-19" in p for p in problems)


def test_v20_bad_service_name() -> None:
    answers = {
        "topology": "monorepo",
        "service_names": ["Api_Gateway"],
        "services_config": {},
    }
    problems = _check(answers)
    assert any("V-20" in p for p in problems)


def test_per_service_replay_v5_langgraph_needs_a_store() -> None:
    answers = {
        "topology": "monorepo",
        "service_names": ["api", "worker"],
        "transport_rabbitmq": True,
        "services_config": {
            "api": {"db_postgres": True},
            "worker": {"langgraph": True},  # no db_postgres / db_redis in this submap
        },
    }
    problems = _check(answers)
    assert any("worker" in p and "V-5" in p for p in problems)
    assert not any("'api'" in p for p in problems)


def test_per_service_replay_v13_streaming_grpc_needs_api_grpc() -> None:
    answers = {
        "topology": "monorepo",
        "service_names": ["api"],
        "transport_rabbitmq": True,
        "services_config": {"api": {"streaming_grpc": True}},
    }
    problems = _check(answers)
    assert any("V-13" in p for p in problems)


def test_effective_submap_defaults_do_not_trip_rules() -> None:
    # A service with an empty submap is a plain base FastAPI service and must be
    # clean (all per-service defaults are false / safe).
    answers = {
        "topology": "monorepo",
        "service_names": ["api", "worker"],
        "transport_rabbitmq": True,
        "services_config": {"api": {}},  # worker absent entirely -> all defaults
    }
    assert _check(answers) == []

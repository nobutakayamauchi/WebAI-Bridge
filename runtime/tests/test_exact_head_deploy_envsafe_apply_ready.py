from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "deploy/exact_head_deploy_envsafe_apply_ready.py"
spec = importlib.util.spec_from_file_location("exact_head_deploy_envsafe_apply_ready", PATH)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


class GateError(RuntimeError):
    pass


def _generation(*, pid: int = 10, invocation: str = "a" * 32, revision: str = "9" * 40):
    return {
        "pid": pid,
        "invocation_id": invocation,
        "cwd": "/old/runtime",
        "revision": revision,
        "service_sha256": "b" * 64,
        "stable_samples": 2,
    }


def _fixture_inner(sequence: list[dict]):
    class Base:
        GateError = GateError
        TARGET_SHA = "5" * 40
        mutation_calls = 0
        evidence_payloads: list[dict] = []

        @staticmethod
        def systemd_composition():
            return None

    class Inner:
        BOOTSTRAP_ALLOWED_ENV_KEYS = m.BOOTSTRAP_ALLOWED_ENV_KEYS
        index = 0

        @staticmethod
        def _stable_previous_snapshot(base, ready):
            item = sequence[min(Inner.index, len(sequence) - 1)]
            Inner.index += 1
            return dict(item)

        @staticmethod
        def _install_apply_overlay(base, envsafe, host, ready, controller_revision):
            def prepare():
                return {"production_mutation": False, "production_apply_enabled": True}

            def evidence(payload: dict):
                Base.evidence_payloads.append(payload)
                return Path("/tmp/evidence.json")

            def apply(approval: str):
                Inner._stable_previous_snapshot(base, ready)
                Base.mutation_calls += 1
                return base.evidence({"status": "DEPLOYED_AND_EXTERNAL_ACCEPTANCE_PASS"})

            base.prepare = prepare
            base.evidence = evidence
            base.apply = apply

    return Inner, Base


def test_same_previous_generation_requires_all_identity_fields():
    a = _generation()
    assert m._same_previous_generation(a, dict(a))
    for field, replacement in (
        ("pid", 11),
        ("invocation_id", "b" * 32),
        ("cwd", "/different"),
        ("revision", "8" * 40),
        ("service_sha256", "c" * 64),
    ):
        changed = dict(a)
        changed[field] = replacement
        assert not m._same_previous_generation(a, changed)


def test_prepare_reports_stable_previous_generation_without_mutation():
    inner, Base = _fixture_inner([_generation()])
    m._install_human_gate_overlay(inner)
    inner._install_apply_overlay(Base, object(), object(), object(), "c" * 40)

    prepared = Base.prepare()

    assert prepared["previous_production_snapshot"]["invocation_id"] == "a" * 32
    assert prepared["target_already_active"] is False
    assert prepared["human_gate_authority"] == m.HUMAN_GATE_AUTHORITY
    assert Base.mutation_calls == 0


def test_apply_rejects_generation_change_before_inner_mutation():
    before = _generation()
    changed = _generation(pid=11, invocation="b" * 32)
    inner, Base = _fixture_inner([before, changed])
    m._install_human_gate_overlay(inner)
    inner._install_apply_overlay(Base, object(), object(), object(), "c" * 40)

    with pytest.raises(GateError, match="changed after Human Gate"):
        Base.apply(Base.TARGET_SHA)

    assert Base.mutation_calls == 0
    assert Base.evidence_payloads == []


def test_apply_rejects_redundant_target_before_inner_apply():
    target = _generation(revision="5" * 40)
    inner, Base = _fixture_inner([target])
    m._install_human_gate_overlay(inner)
    inner._install_apply_overlay(Base, object(), object(), object(), "c" * 40)

    with pytest.raises(GateError, match="already active"):
        Base.apply(Base.TARGET_SHA)

    assert Base.mutation_calls == 0


def test_success_evidence_records_human_gate_revalidation():
    before = _generation()
    inner, Base = _fixture_inner([before, dict(before)])
    m._install_human_gate_overlay(inner)
    inner._install_apply_overlay(Base, object(), object(), object(), "c" * 40)

    result = Base.apply(Base.TARGET_SHA)

    assert result == Path("/tmp/evidence.json")
    assert Base.mutation_calls == 1
    payload = Base.evidence_payloads[-1]
    assert payload["human_gate_previous_production_snapshot"]["pid"] == 10
    assert payload["human_gate_generation_revalidated"] is True
    assert payload["human_gate_authority"] == m.HUMAN_GATE_AUTHORITY

"""T04b — the package never pretends to apply native configuration.

The observation seam for native effects is the *consumer-side* UNBOUND
Protocols (`ConfigurationTarget`/`EffectProbe` in `probe.py`) whose documented
shape will be satisfied by the released `harness-api` when C0 publishes it
(`specs/011-q5-safety/api-requests.md` G3 — the branch commit b5dcf84703 is
NOT a checkpoint and its vocabulary is NOT copied here). These tests pin that
promise: no apply path, no written config, no second intent vocabulary.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from _sandbox_backend_helpers import HARNESSES_TOML, claude_evidence, claude_intent, facts

import ordessa_sandbox_backend
from ordessa_sandbox_api import SandboxVerificationOutcome, ToolCategory
from ordessa_sandbox_backend import (
    ConfigurationTarget,
    EffectObservation,
    EffectProbe,
    SandboxOptionCatalogue,
    SandboxVerifier,
    VerdictKind,
)

HARNESS_C3_VOCABULARY = ("SetField", "ResetField", "InvokeAction", "MountContent",
                         "TargetHandle", "FieldClaim", "ConfigurationAdapter")


@pytest.fixture()
def verifier():
    catalogue = SandboxOptionCatalogue.from_repo(harnesses_toml=Path(HARNESSES_TOML))
    return SandboxVerifier(catalogue=catalogue)


class RecordingTarget:
    """A consumer-side stand-in that records every attribute touched."""

    def __init__(self, calls):
        self._calls = calls

    def is_available(self):
        self._calls.append("is_available")
        return True

    def __getattr__(self, name):  # any mutating call would land here
        self._calls.append(name)
        raise AssertionError(f"backend called a non-read method: {name}")


class FakeProbe:
    def __init__(self, calls, outcome=SandboxVerificationOutcome.VERIFIED,
                 covered=(ToolCategory.BASH,)):
        self._calls = calls
        self._outcome = outcome
        self._covered = frozenset(covered)

    def observe_effect(self, target_handle, intent):
        self._calls.append("observe_effect")
        return EffectObservation(outcome=self._outcome,
                                 covered_categories=self._covered,
                                 reason="fake controlled probe")


def test_probe_and_target_are_read_only_protocols():
    # the entire observation seam has no verb that could apply configuration
    for proto in (ConfigurationTarget, EffectProbe):
        methods = {n for n in dir(proto) if not n.startswith("_")}
        assert methods <= {"is_available", "observe_effect"}, proto
        assert not (methods & {"apply", "write", "commit", "configure", "reset"})


def test_the_package_copies_no_harness_c3_intent_vocabulary():
    # G3: the closed SetField/ResetField/InvokeAction intent types are
    # Harness's; a second vocabulary pretending to be them is forbidden
    exported = set(dir(ordessa_sandbox_backend))
    leaked = exported & set(HARNESS_C3_VOCABULARY)
    assert leaked == set()


def test_verifier_never_calls_anything_but_read_methods(verifier, tmp_path, monkeypatch):
    calls: list[str] = []
    target = RecordingTarget(calls)
    probe = FakeProbe(calls)
    verdict = verifier.verify(claude_intent(), facts(),
                              evidence=claude_evidence(),
                              target=target, probe=probe)
    assert verdict.kind is VerdictKind.VERIFIED
    assert calls and set(calls) <= {"is_available", "observe_effect"}
    assert verdict.effect_started is False
    # and no config file appeared anywhere under a pristine "harness root"
    monkeypatch.chdir(tmp_path)
    assert list(tmp_path.rglob("*")) == []


def test_probe_inconclusiveness_downgrades_verified(verifier):
    calls: list[str] = []
    probe = FakeProbe(calls, outcome=SandboxVerificationOutcome.UNKNOWN)
    verdict = verifier.verify(claude_intent(), facts(),
                              evidence=claude_evidence(), probe=probe)
    assert verdict.kind is VerdictKind.UNKNOWN
    assert verdict.code.value == "SANDBOX_EFFECT_UNKNOWN"


def test_a_refusal_path_touches_nothing_at_all(verifier):
    calls: list[str] = []
    target = RecordingTarget(calls)
    probe = FakeProbe(calls)
    verdict = verifier.verify(claude_intent(), facts(adapter_available=False),
                              evidence=claude_evidence(),
                              target=target, probe=probe)
    assert verdict.kind is not VerdictKind.VERIFIED
    assert verdict.refused_before_side_effect is True
    assert "observe_effect" not in calls  # refused before even probing effects
    assert set(calls) <= {"is_available"}

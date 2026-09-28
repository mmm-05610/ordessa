"""T08 — Pi conditional adapter (G14): explicit absence, never a bought green.

Positive column: a typed `unsupported` assessment whose reasons are the
three measured absences — now in the REAL `Assessment` DTO, the contract's
best available spelling of 「extension-backed: absent」 (status
`unsupported` + named `reason` + `evidence_ref`, plus an empty `FieldClaim`
tuple on the descriptor; there is no dedicated extension-backed status in
the published vocabulary — recorded as SR-1b(c)-adjacent observation) — and
a compile refusal *before* any intent. Negative column: a self-declared
registry (no owner / no review_ref / owner = this plugin) does NOT unlock;
even a granted record stops at NATIVE_ENTRY_UNAVAILABLE (A6); the triad
provably spawns no process and writes nothing.
"""
from __future__ import annotations

import os
import subprocess

import pytest
from ordessa_harness_api import (
    AdapterContext, Assessment, Installation, IntentSource, Mismatch,
    VerificationUnknown,
)

from ordessa_assets_subagents import dto, errors
from ordessa_assets_subagents.adapters import base, intents, pi

SHA = "sha256:" + "ab" * 32
#: Pi carries NO targets (no file-format entry at any pin) — the contract
#: shape of the old "TargetSlot had no Pi member" fact.
PI_CONTEXT = AdapterContext(
    (),
    Installation("pi", None, pi.PI_ADAPTER_SEMVER, "fixture:install"),
    "acp", "instance", "fixture:capability",
)
SOURCE = IntentSource(intents.FACET_ID, "def-pi", "v1")


def make_item(slug: str = "worker", *, definition_id: str = "d1") -> intents.ManagedItem:
    source = dto.SourceApproval("user-upload", "file:seed.md", SHA,
                                "principal-a", "2026-09-28T00:00:00Z")
    revision = dto.DefinitionRevision(definition_id, 1, SHA, "You do work.", source=source)
    definition = dto.AgentDefinition("server-a", definition_id, slug, "Worker",
                                     "does work", "public", "owner-a")
    return intents.ManagedItem(definition, revision)


class FakeRegistry:
    """A stand-in for C0's Harness-side registry (Protocol-shaped, injected)."""

    def __init__(self, record):
        self._record = record

    def lookup_extension(self, extension_id: str):
        assert extension_id == pi.PI_SUBAGENT_EXTENSION_ID
        return self._record


def granted_record(**overrides):
    record = {
        "registered": True,
        "owner": "harness-runtime",
        "pinned_commit": "0123456789abcdef0123456789abcdef01234567",
        "license": "MIT",
        "review_ref": "docs/harness/subagent-extension-audit.md#A1-A7",
    }
    record.update(overrides)
    return record


# -- assess ----------------------------------------------------------------------


def test_assess_is_unsupported_not_unknown():
    assessment = pi.PiAdapter().assess(PI_CONTEXT)
    assert type(assessment) is Assessment          # the published DTO
    assert assessment.status == "unsupported"
    assert "0.5.0" in (assessment.evidence_ref or "")
    joined = assessment.evidence_ref or ""
    assert "No packages installed" in joined            # measured host fact
    assert "A1" in joined or "A1–A7" in joined          # harness audit absent
    assert "subagent" in joined                          # adapter dist surface
    assert assessment.reason                             # contract-forced
    detail = pi.PiAdapter().assess_detail(PI_CONTEXT)
    assert len(detail.evidence) >= 3


def test_assess_keeps_unmeasured_governance_as_unknown_cell():
    detail = pi.PiAdapter().assess_detail(PI_CONTEXT)
    assert detail.verdict("example-extension-governance").state \
        is base.AssessmentState.UNKNOWN
    assert detail.verdict("extension-registered").state \
        is base.AssessmentState.UNSUPPORTED


def test_assess_refuses_foreign_installation():
    foreign = AdapterContext((), Installation("claude", None, (0, 5, 0), "f"),
                             "acp", "instance", "fixture:cap")
    with pytest.raises(errors.DomainError) as excinfo:
        pi.PiAdapter().assess(foreign)
    assert excinfo.value.code == errors.TARGET_CONFLICT


# -- compile: refusal before any intent -------------------------------------------


def test_compile_refuses_without_registry():
    with pytest.raises(errors.DomainError) as excinfo:
        pi.PiAdapter().compile(PI_CONTEXT, [make_item()], SOURCE)
    assert excinfo.value.code == errors.ADAPTER_MISSING
    assert "extension-backed" in excinfo.value.detail


@pytest.mark.parametrize("record,needle", [
    (None, "no Harness-registered"),
    ({"registered": False}, "registered=True"),
    (granted_record(owner=None), "owner"),
    (granted_record(review_ref="  "), "review"),
    (granted_record(owner="assets.native-subagents"), "self-declared"),
    (granted_record(owner="ordessa_assets_subagents"), "self-declared"),
    (granted_record(pinned_commit="main"), "commit"),
    (granted_record(license=""), "license"),
])
def test_registries_that_do_not_unlock(record, needle):
    adapter = pi.PiAdapter(FakeRegistry(record))
    with pytest.raises(errors.DomainError) as excinfo:
        adapter.compile(PI_CONTEXT, [make_item()], SOURCE)
    assert excinfo.value.code == errors.ADAPTER_MISSING
    assert needle in excinfo.value.detail


def test_self_declared_registry_does_not_unlock_even_when_complete():
    # §C3: the definitions plugin may not ship its own execution host, so a
    # record it granted to itself is NOT an unlock (no owner/review_ref or
    # self-owned owner must keep the refusal identical to absence).
    adapter = pi.PiAdapter(FakeRegistry(granted_record(owner="q3", review_ref="")))
    with pytest.raises(errors.DomainError) as excinfo:
        adapter.compile(PI_CONTEXT, [make_item()], SOURCE)
    assert excinfo.value.code == errors.ADAPTER_MISSING


def test_granted_record_advances_past_adapter_missing_but_still_refuses():
    adapter = pi.PiAdapter(FakeRegistry(granted_record()))
    with pytest.raises(errors.DomainError) as excinfo:
        adapter.compile(PI_CONTEXT, [make_item()], SOURCE)
    # A6 control port / definition surface absent at the pinned adapter:
    # compilation unlocks to a *different* typed refusal, never to intents.
    assert excinfo.value.code == errors.NATIVE_ENTRY_UNAVAILABLE


def test_precondition_refusal_wins_over_item_refusal():
    # even a collection that would fail item checks must first hit the
    # execution-host precondition — the refusal order proves no item-level
    # work happens while the extension is unregistered.
    retained = dto.DefinitionRevision("d9", 1, SHA, "body",
                                      retained_native_fields={"hooks": 1},
                                      source=dto.SourceApproval(
                                          "user-upload", "r", SHA, "p",
                                          "2026-09-28T00:00:00Z"))
    definition = dto.AgentDefinition("server-a", "d9", "worker", "W", "w", "public", "o")
    item = intents.ManagedItem(definition, retained)
    with pytest.raises(errors.DomainError) as excinfo:
        pi.PiAdapter().compile(PI_CONTEXT, [item], SOURCE)
    assert excinfo.value.code == errors.ADAPTER_MISSING  # precondition first


# -- verify: nothing observable ------------------------------------------------------

EMPTY_SET = intents.IntentSet(())


@pytest.mark.parametrize("observation", [
    base.NativeLoaderObservation("worker", "extension-loader"),
    base.ControlEntryObservation("worker", "entry"),
    base.InvocationEventObservation("worker", "evt"),
])
def test_verify_refuses_event_class_claims(observation):
    with pytest.raises(errors.DomainError) as excinfo:
        pi.PiAdapter().verify_observations(observation, EMPTY_SET)
    assert excinfo.value.code == errors.NATIVE_ENTRY_UNAVAILABLE


def test_verify_file_sighting_is_unknown_never_loaded():
    result = pi.PiAdapter().verify_observations(
        base.FileExistenceObservation("worker"), EMPTY_SET)
    assert result.state_of("worker") is base.VerifyState.UNKNOWN


def test_contract_verify_maps_the_same_facts():
    adapter = pi.PiAdapter()
    loader = adapter.verify(PI_CONTEXT, {"kind": "loader", "native_name": "worker",
                                         "ref": "extension-loader"})
    assert isinstance(loader, Mismatch)   # a Match would fake a loader (G14)
    file_only = adapter.verify(PI_CONTEXT, {"kind": "file-existence",
                                            "native_name": "worker", "ref": "sighting"})
    assert isinstance(file_only, VerificationUnknown)
    # capability: with valid input the SAME base path does produce non-error
    # Verification objects (the guard is live, not a broken code path) —
    # proven by the Claude Match in t06 using this exact inherited method.


# -- purity: no process, no writes, no filesystem --------------------------------------


def test_triad_never_spawns_a_process(monkeypatch, tmp_path):
    def tripwire(*args, **kwargs):
        raise AssertionError("Q3 adapters must never spawn a process")

    monkeypatch.setattr(subprocess, "Popen", tripwire)
    monkeypatch.setattr(subprocess, "run", tripwire)
    monkeypatch.setattr(subprocess, "call", tripwire)
    monkeypatch.setattr(subprocess, "check_output", tripwire)
    adapter = pi.PiAdapter()
    adapter.assess(PI_CONTEXT)
    with pytest.raises(errors.DomainError):
        adapter.compile(PI_CONTEXT, [make_item()], SOURCE)
    adapter.verify_observations(base.FileExistenceObservation("worker"), EMPTY_SET)
    # the claude/codex triads are under the same rule:
    from ordessa_assets_subagents.adapters import claude, codex
    claude_context = AdapterContext(
        (base.RealTargetDescriptor(
            base.TargetHandle(claude.CLAUDE_GENERATION_HANDLE, 1),
            "directory", "content", "instance", (("agents",),)),),
        Installation("claude", None, claude.CLAUDE_ADAPTER_SEMVER, "f"),
        "acp", "instance", "fixture:cap")
    claude.ClaudeAdapter().assess(claude_context)
    with pytest.raises(errors.DomainError):
        codex.CodexAdapter().compile(
            AdapterContext((), Installation("codex", None, codex.CODEX_ADAPTER_SEMVER, "f"),
                           "acp", "instance", "fixture:cap"), [], SOURCE)


def test_triad_writes_nothing_anywhere(monkeypatch):
    def no_write_open(*args, **kwargs):
        mode = args[1] if len(args) > 1 else kwargs.get("mode", "r")
        if isinstance(mode, str) and any(c in mode for c in "wxa+"):
            raise AssertionError("Q3 adapters must not write files")
        return real_open(*args, **kwargs)

    real_open = open
    monkeypatch.setattr("builtins.open", no_write_open)
    for name in ("mkdir", "makedirs", "rmdir", "removedirs", "rename", "replace",
                 "unlink", "remove", "symlink", "link"):
        def landmine(*args, **kwargs):
            raise AssertionError("no filesystem mutation from adapters")
        monkeypatch.setattr(os, name, landmine)
    adapter = pi.PiAdapter()
    adapter.assess(PI_CONTEXT)
    with pytest.raises(errors.DomainError):
        adapter.compile(PI_CONTEXT, [make_item()], SOURCE)
    result = adapter.verify_observations(base.FileExistenceObservation("worker"), EMPTY_SET)
    assert result.max_state is base.VerifyState.UNKNOWN


def test_adapter_sources_contain_no_process_network_or_filesystem_handles():
    """Static half of the purity bar: the adapters package imports nothing
    that could spawn, connect or write (the triad is content-in / intents-out).
    `hashlib` is a pure function, not a filesystem handle; the contract API
    package itself is stdlib-only by its own README."""
    from pathlib import Path
    import re as _re
    adapters_dir = Path(pi.__file__).parent
    banned = _re.compile(
        r"\b(subprocess|socket|asyncio|pty|shutil|urllib|ftplib|telnetlib)\b"
        r"|\bos\.(mkdir|remove|unlink|rename|replace|walk|system|spawn|fork|exec)"
        r"|\bopen\s*\(|\bPath\s*\(")
    for source in sorted(adapters_dir.glob("*.py")):
        text = source.read_text(encoding="utf-8")
        # scan import lines and every non-docstring statement line:
        code = _re.sub(r'""".*?"""', "", text, flags=_re.S)
        for line_no, line in enumerate(code.splitlines(), 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            assert banned.search(stripped) is None, \
                f"{source.name}:{line_no}: {stripped}"


def test_pi_descriptor_claims_no_target_and_carries_no_slot():
    # No file-format entry exists for Pi, so the descriptor claims nothing
    # (the contract shape of the old "no Pi TargetSlot member" fact) and no
    # IntentSet can ever be aimed at it:
    assert pi.PiAdapter().descriptor.claims == ()
    # even a host-injected content target is never reached: the precondition
    # refusal wins, so no Pi mount can exist:
    with_target = AdapterContext(
        (base.RealTargetDescriptor(
            base.TargetHandle("some-pi-generation", 1),
            "directory", "content", "instance", (("agents",),)),),
        Installation("pi", None, pi.PI_ADAPTER_SEMVER, "f"),
        "acp", "instance", "fixture:cap")
    with pytest.raises(errors.DomainError) as excinfo:
        pi.PiAdapter().compile(with_target, [make_item()], SOURCE)
    assert excinfo.value.code == errors.ADAPTER_MISSING
    assert intents.IntentSet(()) .intents == ()

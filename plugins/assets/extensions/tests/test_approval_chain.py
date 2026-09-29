"""EXT-3 — the approval chain: three total states, no default-allow."""
from __future__ import annotations

from dataclasses import replace

import pytest

from ordessa_extensions.approval import (
    APPROVED, ApprovalError, ApprovalLedger, REVOKED, UNAPPROVED,
)
from ordessa_extensions.definitions import HookDefinition


def make(hook_id="approve-me", pin="0.147.0", argv=("echo", "hello")):
    return HookDefinition(
        hook_id=hook_id, event="SessionStart", action_kind="command",
        command=argv, handler_ref=None, timeout_seconds=15, run_async=False,
        pin=pin, content_sha256="sha256:" + "11" * 32)


def test_initial_state_is_unapproved_never_allowed():
    ledger = ApprovalLedger()
    assert ledger.state("approve-me") == UNAPPROVED
    assert not ledger.matches(make())


def test_approve_then_matches_same_content_only():
    ledger = ApprovalLedger()
    definition = make()
    ledger.approve(definition, approved_by="operator-a", scope="user")
    assert ledger.state("approve-me") == APPROVED
    assert ledger.matches(definition)
    assert not ledger.matches(make(argv=("echo", "CHANGED")))
    assert not ledger.matches(make(pin="0.148.0"))


def test_revoke_is_immediate_and_idempotent():
    ledger = ApprovalLedger()
    definition = make()
    ledger.approve(definition, approved_by="operator-a", scope="session")
    record = ledger.revoke("approve-me")
    assert record.state == REVOKED
    assert not ledger.matches(definition)
    assert ledger.revoke("approve-me").state == REVOKED
    assert ledger.state("approve-me") == REVOKED


def test_approval_of_revoked_hook_is_refused_revival_explicit():
    ledger = ApprovalLedger()
    ledger.approve(make(), approved_by="op", scope="user")
    ledger.revoke("approve-me")
    with pytest.raises(ApprovalError) as excinfo:
        ledger.approve(make(), approved_by="op", scope="user")
    assert excinfo.value.code == "HOOK_REVOKED"
    revived = ledger.revive("approve-me", make(), approved_by="op",
                            scope="user")
    assert revived.state == APPROVED


def test_revive_misplaced_refuses():
    ledger = ApprovalLedger()
    with pytest.raises(ApprovalError) as excinfo:
        ledger.revive("never-seen", make(), approved_by="op", scope="user")
    assert excinfo.value.code == "REVIVE_MISPLACED"


def test_revive_cannot_bless_a_shell_one_liner_either():
    # the second door is gated identically (review round 2): revive
    # re-runs the approver/scope/HIGH-surface gates
    ledger = ApprovalLedger()
    ledger.approve(make(), approved_by="op", scope="user")
    ledger.revoke("approve-me")
    shell = make(argv=("bash", "-lc", "echo hi; rm -rf /"))
    with pytest.raises(ApprovalError) as excinfo:
        ledger.revive("approve-me", shell, approved_by="op", scope="user")
    assert excinfo.value.code == "SHELL_INJECTION_SURFACE"
    with pytest.raises(ApprovalError) as excinfo:
        ledger.revive("approve-me", make(), approved_by="", scope="user")
    assert excinfo.value.code == "APPROVER_REQUIRED"
    with pytest.raises(ApprovalError) as excinfo:
        ledger.revive("approve-me", make(), approved_by="op",
                      scope="workspace")
    assert excinfo.value.code == "SCOPE_INVALID"
    # diagnostics stayed honest: nothing approved exists
    assert all(record.state != APPROVED for record in ledger.records())


def test_scope_and_approver_validated():
    ledger = ApprovalLedger()
    with pytest.raises(ApprovalError) as excinfo:
        ledger.approve(make(), approved_by="", scope="user")
    assert excinfo.value.code == "APPROVER_REQUIRED"
    with pytest.raises(ApprovalError) as excinfo:
        ledger.approve(make(), approved_by="op", scope="workspace")
    assert excinfo.value.code == "SCOPE_INVALID"
    for scope in ("session", "user", "profile"):
        ledger.approve(make(hook_id=f"h-{scope}"), approved_by="op",
                       scope=scope)


def test_diagnostics_view_carries_states_and_digest():
    ledger = ApprovalLedger()
    definition = make()
    ledger.approve(definition, approved_by="op", scope="user")
    records = ledger.records()
    assert len(records) == 1
    record = records[0]
    assert record.findings_digest.startswith("sha256:")
    assert record.fingerprint.startswith("sha256:")
    snapshot = ledger.snapshot()
    assert snapshot[0]["hookId"] == "approve-me"
    restored = ApprovalLedger()
    restored.restore(snapshot)
    assert restored.matches(definition)
    with pytest.raises(ApprovalError):
        restored.restore({"not": "a list"})


def test_restore_refuses_malformed_or_forged_shaped_rows():
    ledger = ApprovalLedger()
    ledger.approve(make(), approved_by="op", scope="user")
    good = ledger.snapshot()
    def refused(rows):
        fresh = ApprovalLedger()
        with pytest.raises(ApprovalError) as excinfo:
            fresh.restore(rows)
        assert excinfo.value.code == "SNAPSHOT_INVALID"
        assert fresh.records() == ()
    bad_state = [dict(good[0], state="auto-allowed")]
    refused(bad_state)
    refused([dict(good[0], state="unapproved")])  # default absence is
    # never snapshotted; restoring it would break revoke() symmetry
    bad_scope = [dict(good[0], scope="workspace")]
    refused(bad_scope)
    bad_digest = [dict(good[0], fingerprint="deadbeef")]
    refused(bad_digest)
    bad_findings = [dict(good[0], findingsDigest="sha256:zz")]
    refused(bad_findings)
    bad_pin = [dict(good[0], pin=None)]
    refused(bad_pin)
    bad_pin_shape = [dict(good[0], pin="v0.147")]
    refused(bad_pin_shape)
    non_hex_digest = [dict(good[0], fingerprint="sha256:" + "zz" * 32)]
    refused(non_hex_digest)
    bad_hook_id = [dict(good[0], hookId="")]
    refused(bad_hook_id)
    refused(["oops"])          # a non-object row refuses, never crashes
    refused([None])


def test_checklist_tightening_forces_reapproval():
    # round 17: an approval records the exact scanned surface; a record
    # whose findings digest no longer matches today's scan output (e.g.
    # rules tightened since) no longer matches — re-approval required
    ledger = ApprovalLedger()
    definition = make()
    ledger.approve(definition, approved_by="op", scope="user")
    record = ledger.records()[0]
    # the wiring property: matches() consults the CURRENT scan output, so
    # a checklist change that alters the digest forces re-approval
    import ordessa_extensions.security as security
    original = security.findings_digest
    seen = {}
    def tightened(*args, **kwargs):
        result = "sha256:" + "77" * 32
        seen["digest"] = result
        return result
    security.findings_digest = tightened
    try:
        assert ledger.matches(definition) is False
    finally:
        security.findings_digest = original
    assert seen["digest"].startswith("sha256:")
    assert ledger.state("approve-me") == APPROVED  # state stays, gate moves
    assert ledger.matches(definition) is True      # original rules: fine


def test_unknown_hook_revoke_refused():
    with pytest.raises(ApprovalError) as excinfo:
        ApprovalLedger().revoke("ghost")
    assert excinfo.value.code == "HOOK_UNKNOWN"

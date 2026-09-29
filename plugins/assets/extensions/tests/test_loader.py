"""EXT-3 — the load pipeline: 未批准定义=不装载 (fail closed)."""
from __future__ import annotations

from ordessa_extensions.approval import ApprovalLedger
from ordessa_extensions.definitions import HookDefinition
from ordessa_extensions.loader import HookLoader


def make(hook_id="load-me", argv=("echo", "hi"), pin="0.147.0"):
    return HookDefinition(
        hook_id=hook_id, event="PreToolUse", action_kind="command",
        command=argv, handler_ref=None, timeout_seconds=9, run_async=False,
        pin=pin, content_sha256="sha256:" + "22" * 32)


def test_unapproved_definition_is_never_loaded():
    loader = HookLoader(ApprovalLedger())
    report = loader.load([make()])
    assert report.loaded == ()
    assert len(report.refusals) == 1
    assert report.refusals[0].code == "NOT_APPROVED"
    assert "未批准" in report.refusals[0].detail


def test_approved_exact_content_loads():
    ledger = ApprovalLedger()
    definition = make()
    ledger.approve(definition, approved_by="op", scope="user")
    report = HookLoader(ledger).load([definition])
    assert report.loaded == (definition,)
    assert report.refusals == ()


def test_stale_content_and_stale_pin_do_not_load():
    ledger = ApprovalLedger()
    ledger.approve(make(), approved_by="op", scope="user")
    drifted = make(argv=("echo", "drifted"))            # content changed
    repinned = make(pin="0.148.0")                      # pin changed only
    other = make(hook_id="second")                      # never approved
    report = HookLoader(ledger).load([drifted, repinned, other])
    assert report.loaded == ()
    assert {r.code for r in report.refusals} == {"NOT_APPROVED"}
    assert {r.hook_id for r in report.refusals} == {
        "load-me", "second"}  # drifted and repinned share hook_id


def test_revoked_definition_does_not_load():
    ledger = ApprovalLedger()
    definition = make()
    ledger.approve(definition, approved_by="op", scope="user")
    ledger.revoke("load-me")
    report = HookLoader(ledger).load([definition])
    assert report.loaded == ()


def test_high_security_finding_cannot_even_be_approved():
    # the red line lives in the LEDGER too (review fix): an approval of a
    # shell one-liner raises, so no "approved" record can ever exist for
    # content the loader would refuse — diagnostics cannot lie.
    import pytest
    from ordessa_extensions.approval import ApprovalError
    ledger = ApprovalLedger()
    shell = make(argv=("bash", "-lc", "echo hi; rm -rf /"))
    with pytest.raises(ApprovalError) as excinfo:
        ledger.approve(shell, approved_by="op", scope="user")
    assert excinfo.value.code == "SHELL_INJECTION_SURFACE"
    assert ledger.records() == ()
    report = HookLoader(ledger).load([shell])
    assert report.loaded == ()
    assert report.refusals[0].code == "SHELL_INJECTION_SURFACE"


def test_handler_actions_never_load_even_when_approved():
    # the handler registry does not exist tonight (round 16): the
    # modelled route is refused at the load gate, approval notwithstanding
    import pytest
    from ordessa_extensions.approval import ApprovalError
    ledger = ApprovalLedger()
    handler = HookDefinition(
        hook_id="handler-load", event="SessionStart", action_kind="handler",
        command=None, handler_ref="recorder", timeout_seconds=5,
        run_async=False, pin="0.147.0",
        content_sha256="sha256:" + "55" * 32)
    ledger.approve(handler, approved_by="op", scope="user")
    report = HookLoader(ledger).load([handler])
    assert report.loaded == ()
    assert report.refusals[0].code == "HANDLER_ROUTE_UNAVAILABLE"


def test_tampered_slots_refuse_typed_never_crash_the_batch():
    # round 18: a hand-tampered non-string slot crashes __post_init__
    # with TypeError — the gate types it, the rest of the batch loads on
    ledger = ApprovalLedger()
    good = make()
    ledger.approve(good, approved_by="op", scope="user")
    tampered = make()
    object.__setattr__(tampered, "pin", 123)  # bypass construction-time
    # validation — exactly the hand-tampered shape the re-touch exists for
    report = HookLoader(ledger).load([tampered, good])
    assert report.refusals[0].code == "DEFINITION_INVALID"
    assert report.loaded == (good,)


def test_mixed_report_accounts_for_every_input():
    ledger = ApprovalLedger()
    ledger.approve(make(), approved_by="op", scope="user")
    definitions = [make(), make(hook_id="unapproved"), make(hook_id="third")]
    report = HookLoader(ledger).load(definitions)
    assert len(report.loaded) + len(report.refusals) == 3
    assert len(report.loaded) == 1

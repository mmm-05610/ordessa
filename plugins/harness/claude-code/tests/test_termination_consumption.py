"""C: termination family consumption over the frozen unified stop/release face.

Real temporary SQLite ledger + real core lifecycle claims (one cleanup action
per operation, as the core reserves them) and REAL controlled test-owned sleep
processes. Proven here: begin -> effect -> owner evidence -> record; unknown
keeps the hold, the ticket and the process; borrowed or unknown units are
never killed nor released; forged evidence refuses; late/cold reconcile
concludes only owner-observed outcomes. The native Claude runtime P-layer is
absent (no binary in this tree): nothing here exercises the actual claude
CLI, model, or SDK.
"""
import pytest

import claude_production_fixture as fx
from ordessa_harness_claude_code.termination import (
    ClaudeTerminationCoordinator, ClaudeTerminationEffects, ClaudeTerminationRefused,
)
from ordessa_harness_claude_code.ownership import ClaudeChannelRefused

from ordessa_units.records.unit_records import TERMINATION_VERSION


def wired(parts, channels=None):
    channels = channels if channels is not None else parts["ports"].channels
    effects = ClaudeTerminationEffects(channels, parts["records"].termination_evidence,
                                       close_timeout=0.5)
    coordinator = ClaudeTerminationCoordinator(records=parts["records"],
                                               verifier=parts["records"].verifier,
                                               projection=parts["projection"], effects=effects)
    return coordinator, channels


def bootstrap(tmp_path):
    parts = fx.family_core_parts(tmp_path)
    coordinator, channels = wired(parts)
    return parts, coordinator, channels


def teardown_channel(channels):
    fx.reap_entries(channels)


class _DeadChannel:
    """Owned handle of an already-exited process (is_alive keeps False)."""

    def is_alive(self):
        return False

    def close(self, *, timeout=5.0):
        return 0


def _foreign_reference():
    return {"environmentNamespace": "env", "unitId": "unit-foreign",
            "ownerProviderRef": dict(fx.FAMILY_PROVIDER), "sourceRevision": "sha256:" + "a" * 64}


def test_stop_confirmed_reaps_owned_process_and_stores_owner_refs(tmp_path):
    parts, coordinator, channels = bootstrap(tmp_path)
    stop = fx.cleanup_operation(parts, "stop")
    channel = fx.sleeping_process()
    try:
        channels.register(parts["unit"].public_ref, channel)
        assert channel.is_alive() and channels.has_live_process(parts["unit"].public_ref)
        reply = coordinator.stop(parts["unit"].public_ref, stop["issued"]())
        assert reply["state"] == "confirmed" and fx.same_reference(reply["unitRef"], parts["unit"].public_ref)
        assert not channel.is_alive()  # the controlled process was actually reaped
        projection = parts["records"].owner_read_termination(parts["unit"].unit_ref, "stop")
        assert projection["version"] == TERMINATION_VERSION and projection["state"] == "confirmed"
        # The stored refs are the OWNER port's own provenance strings, never caller values.
        assert projection["outcome"]["action"] == "stop"
        assert projection["outcome"]["terminationEvidenceRef"].startswith("claude-termination/")
        assert reply["termination"]["state"] == "confirmed"
    finally:
        teardown_channel(channels)


def test_reply_projection_is_owner_read_projection_after_release(tmp_path):
    parts, coordinator, channels = bootstrap(tmp_path)
    release = fx.cleanup_operation(parts, "release")
    channels.register(parts["unit"].public_ref, _DeadChannel())
    reply = coordinator.release(parts["unit"].public_ref, release["issued"]())
    assert reply["state"] == "confirmed" and reply["action"] == "release"
    assert reply["sourceRevision"] == 2
    assert parts["records"].owner_read_termination(parts["unit"].unit_ref, "release")["state"] == "confirmed"
    with pytest.raises(ClaudeChannelRefused):
        channels.release(parts["unit"].public_ref)  # handle already released by the effect


def test_unknown_keeps_hold_ticket_and_the_process(tmp_path):
    parts, coordinator, channels = bootstrap(tmp_path)
    stop = fx.cleanup_operation(parts, "stop")
    channel = fx.sleeping_process()
    try:
        channel.break_close()
        channels.register(parts["unit"].public_ref, channel)
        context = stop["issued"]()
        reply = coordinator.stop(parts["unit"].public_ref, context)
        assert reply["state"] == "unknown"
        assert channel.is_alive()  # nothing was destroyed for an unobserved outcome
        projection = parts["records"].owner_read_termination(parts["unit"].unit_ref, "stop")
        assert projection["state"] == "unknown" and projection["outcome"] is None
        assert parts["issuer"].verified_consumption(context) is True  # one original cleanup consumed
        with pytest.raises(Exception):
            stop["issued"]()  # the store never re-issues the spent step
        from claude_production_fixture import safe_json
        with parts["journal"]._connect() as db:
            row = db.execute("SELECT state, outcome_json FROM harness_unit_terminations").fetchone()
        assert row["state"] == "unknown" and row["outcome_json"] is None
    finally:
        teardown_channel(channels)


def test_late_owner_observation_concludes_retained_unknown(tmp_path):
    parts, coordinator, channels = bootstrap(tmp_path)
    stop = fx.cleanup_operation(parts, "stop")
    channel = fx.sleeping_process()
    try:
        channel.break_close()
        channels.register(parts["unit"].public_ref, channel)
        assert coordinator.stop(parts["unit"].public_ref, stop["issued"]())["state"] == "unknown"
        channel.exit()
        reply = coordinator.reconcile(parts["unit"].public_ref, "stop", stop["query"]())
        assert reply["state"] == "confirmed"
        projection = parts["records"].owner_read_termination(parts["unit"].unit_ref, "stop")
        assert projection["state"] == "confirmed" and projection["sourceRevision"] == 3
    finally:
        teardown_channel(channels)


def test_unobserved_late_probe_keeps_unknown_without_new_record(tmp_path):
    parts, coordinator, channels = bootstrap(tmp_path)
    stop = fx.cleanup_operation(parts, "stop")
    channel = fx.sleeping_process()
    try:
        channel.break_close()
        channels.register(parts["unit"].public_ref, channel)
        assert coordinator.stop(parts["unit"].public_ref, stop["issued"]())["state"] == "unknown"
        revision_before = parts["records"].owner_read_termination(
            parts["unit"].unit_ref, "stop")["sourceRevision"]
        assert coordinator.reconcile(parts["unit"].public_ref, "stop", stop["query"]())["state"] == "unknown"
        assert parts["records"].owner_read_termination(
            parts["unit"].unit_ref, "stop")["sourceRevision"] == revision_before
        assert channel.is_alive()
    finally:
        teardown_channel(channels)


def test_foreign_step_query_is_rejected_and_keeps_attempt(tmp_path):
    parts, coordinator, channels = bootstrap(tmp_path)
    stop = fx.cleanup_operation(parts, "stop")
    channels.register(parts["unit"].public_ref, _DeadChannel())
    assert coordinator.stop(parts["unit"].public_ref, stop["issued"]())["state"] == "confirmed"
    other = fx.cleanup_operation(parts, "release")
    late_query = other["query"]()
    with pytest.raises(ClaudeTerminationRefused, match="query is not the original termination"):
        coordinator.reconcile(parts["unit"].public_ref, "stop", late_query)
    with pytest.raises(ClaudeTerminationRefused, match="never claimed"):
        coordinator.reconcile(parts["unit"].public_ref, "release", late_query)


def test_borrowed_or_unknown_units_are_never_killed(tmp_path):
    parts, coordinator, channels = bootstrap(tmp_path)
    stop = fx.cleanup_operation(parts, "stop")
    release = fx.cleanup_operation(parts, "release")
    foreign_process = fx.sleeping_process()  # owned by somebody else altogether
    try:
        channels.register(_foreign_reference(), foreign_process)  # not this unit
        context = stop["issued"]()
        with pytest.raises(ClaudeTerminationRefused, match="never killed"):
            coordinator.stop(parts["unit"].public_ref, context)
        assert foreign_process.is_alive()  # the foreign process was never touched
        assert parts["issuer"].verified_consumption(context) is False  # nothing consumed
        with parts["journal"]._connect() as db:
            assert db.execute("SELECT count(*) FROM harness_unit_terminations").fetchone()[0] == 0
        release_context = release["issued"]()
        with pytest.raises(ClaudeTerminationRefused, match="never killed"):
            coordinator.release(parts["unit"].public_ref, release_context)
        assert parts["issuer"].verified_consumption(release_context) is False
        assert foreign_process.is_alive()
    finally:
        teardown_channel(channels)


def test_release_confirmed_after_stop_releases_owned_handle(tmp_path):
    parts, coordinator, channels = bootstrap(tmp_path)
    stop = fx.cleanup_operation(parts, "stop")
    release = fx.cleanup_operation(parts, "release")
    channel = fx.sleeping_process()
    try:
        channels.register(parts["unit"].public_ref, channel)
        assert coordinator.stop(parts["unit"].public_ref, stop["issued"]())["state"] == "confirmed"
        assert not channel.is_alive()
        reply = coordinator.release(parts["unit"].public_ref, release["issued"]())
        assert reply["state"] == "confirmed" and reply["action"] == "release"
        assert not channels.is_owned(parts["unit"].public_ref)
    finally:
        teardown_channel(channels)


def test_release_refuses_running_units_without_touching_the_process(tmp_path):
    parts, coordinator, channels = bootstrap(tmp_path)
    release = fx.cleanup_operation(parts, "release")
    channel = fx.sleeping_process()
    try:
        channels.register(parts["unit"].public_ref, channel)
        refusal_context = release["issued"]()
        with pytest.raises(ClaudeTerminationRefused, match="stop the unit first"):
            coordinator.release(parts["unit"].public_ref, refusal_context)
        assert channels.is_owned(parts["unit"].public_ref) and channel.is_alive()
        assert parts["issuer"].verified_consumption(refusal_context) is False
        with parts["journal"]._connect() as db:
            assert db.execute("SELECT count(*) FROM harness_unit_terminations").fetchone()[0] == 0
    finally:
        teardown_channel(channels)


def test_forged_or_unobserved_evidence_never_confirms(tmp_path):
    parts, coordinator, channels = bootstrap(tmp_path)
    stop = fx.cleanup_operation(parts, "stop")
    effect = fx.sleeping_process()
    try:
        channels.register(parts["unit"].public_ref, effect)

        class FabricatingEffects(ClaudeTerminationEffects):
            def termination_effect(self, unit, action, context):
                super().termination_effect(unit, action, context)
                # A caller substitution born nowhere: never observed by the port.
                return {"outcome": "confirmed", "exitCode": "0", "reaped": "1",
                        "claim": "caller-string-only"}

        fabricating = FabricatingEffects(channels, parts["records"].termination_evidence,
                                         close_timeout=0.5)
        forged = ClaudeTerminationCoordinator(records=parts["records"],
                                              verifier=parts["records"].verifier,
                                              projection=parts["projection"], effects=fabricating)
        reply = forged.stop(parts["unit"].public_ref, stop["issued"]())
        assert reply["state"] == "unknown"  # fabricated proof is never stored
        projection = parts["records"].owner_read_termination(parts["unit"].unit_ref, "stop")
        assert projection["state"] == "unknown" and projection["outcome"] is None
        # The true coordinator over the still-registered owned channel concludes later.
        assert coordinator.reconcile(parts["unit"].public_ref, "stop", stop["query"]())["state"] == "confirmed"
    finally:
        teardown_channel(channels)


def test_damaged_port_refusal_records_unknown_and_keeps_ownership(tmp_path):
    parts, coordinator, channels = bootstrap(tmp_path)
    stop = fx.cleanup_operation(parts, "stop")
    channel = fx.sleeping_process()
    try:
        channels.register(parts["unit"].public_ref, channel)
        evidence = parts["records"].termination_evidence

        def broken_verify(*args, **kwargs):
            raise RuntimeError("proof surface surfaced typed")

        broken = type("Broken", (), {"observe": evidence.observe,
                                     "verify_termination": staticmethod(broken_verify)})()
        parts["records"].termination_evidence = broken  # deployment miscomposition
        try:
            damaged = ClaudeTerminationCoordinator(
                records=parts["records"], verifier=parts["records"].verifier,
                projection=parts["projection"],
                effects=ClaudeTerminationEffects(channels, broken, close_timeout=0.5))
            reply = damaged.stop(parts["unit"].public_ref, stop["issued"]())
            # The real effect ran (the owned test process is gone) but nothing
            # is confirmed: the attempt records unknown and nothing is released.
            assert reply["state"] == "unknown"
            assert not channel.is_alive()
            assert channels.is_owned(parts["unit"].public_ref)  # the hold stays owned-place
            assert parts["records"].owner_read_termination(
                parts["unit"].unit_ref, "stop")["state"] == "unknown"
        finally:
            parts["records"].termination_evidence = evidence
    finally:
        teardown_channel(channels)


def test_coordinator_gate_requires_complete_port_surface(tmp_path):
    parts = fx.family_core_parts(tmp_path)
    coordinator, channels = wired(parts)
    with pytest.raises(ClaudeTerminationRefused, match="ledger methods required"):
        ClaudeTerminationCoordinator(records=object(), verifier=object(),
                                     projection=parts["projection"], effects=coordinator.effects)
    with pytest.raises(ClaudeTerminationRefused, match="registry required"):
        ClaudeTerminationEffects(object(), object())
    with pytest.raises(ClaudeTerminationRefused, match="evidence port required"):
        ClaudeTerminationEffects(channels, object())
    with pytest.raises(ClaudeTerminationRefused, match="projection required"):
        ClaudeTerminationCoordinator(records=parts["records"], verifier=parts["records"].verifier,
                                     projection=object(), effects=coordinator.effects)
    with pytest.raises(ClaudeTerminationRefused, match="effects required"):
        ClaudeTerminationCoordinator(records=parts["records"], verifier=parts["records"].verifier,
                                     projection=parts["projection"], effects=object())

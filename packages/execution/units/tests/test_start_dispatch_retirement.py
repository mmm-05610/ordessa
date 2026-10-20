"""Retained no-resend guarantees on real Unit start/SQLite/native ownership.

The retired Work/Execution dispatcher has no production writer. Unit start is
single-use; its original receipt is read rather than returned by dispatching
again. Controlled callbacks surround the actual Local/ACP process boundary.
"""
from dataclasses import replace
from types import SimpleNamespace

import pytest

from test_unit_instance import flow, Scope, Preparation
from ordessa_units.management import UnitInstance
from ordessa_units.records import UnitRecords, OperationJournal
from ordessa_units.sessions.evidence import AcpUnitEvidence
from ordessa_units.admission.connection import ConnectionLeasePort
from ordessa_units.lifecycle.unit_lifecycle import UnitLifecycleRefused
from ordessa_units.records.unit_records import UnitRecordsRefused
from ordessa_environments.composition import (
    CompositionRejected, CompositionErrorCode, RuntimePreparationRejected,
)


class InterruptedStart(BaseException):
    pass


@pytest.mark.parametrize("mode", [
    "accepted", "lost", "callback-rejected", "callback-valueerror",
    "callback-preparation", "preflight", "invalid-receipt", "requested",
])
def test_actual_unit_start_preserves_original_receipt_and_never_resends(flow, monkeypatch, mode):
    prepared = flow.instance.prepare(flow.plan, flow.authority.issue("prepare"))
    original_open = flow.instance.channel_factory.open
    if mode == "preflight":
        flow.instance.descriptor = replace(flow.instance.descriptor,
            supported_methods=tuple(x for x in flow.instance.descriptor.supported_methods if x != "start"))
    elif mode == "invalid-receipt":
        establish = flow.instance.channel_factory.establish_session
        def invalid(*args, **kwargs):
            establish(*args, **kwargs)
            return SimpleNamespace()
        monkeypatch.setattr(flow.instance.channel_factory, "establish_session", invalid)
    elif mode != "accepted":
        def uncertain(*args, **kwargs):
            original_open(*args, **kwargs)
            if mode == "requested":
                raise InterruptedStart("interrupted after owned process launch")
            if mode == "callback-preparation":
                raise RuntimePreparationRejected("callback mislabeled after launch")
            if mode == "callback-rejected":
                raise CompositionRejected(CompositionErrorCode.CAPABILITY_UNSUPPORTED, "after launch")
            raise ValueError("lost receipt" if mode == "lost" else "callback after launch")
        monkeypatch.setattr(flow.instance.channel_factory, "open", uncertain)

    if mode == "accepted":
        result = flow.instance.start(prepared, flow.authority.issue("start"))
        assert result["state"] == "confirmed"
    else:
        with pytest.raises(InterruptedStart if mode == "requested" else UnitLifecycleRefused):
            flow.instance.start(prepared, flow.authority.issue("start"))
    identity = prepared["unitRef"]["unitId"]
    expected = "confirmed" if mode == "accepted" else "notCreated" if mode == "preflight" else "opening" if mode == "requested" else "unknown"
    receipt = flow.records.owner_read_session(identity)
    assert receipt.state == expected
    assert receipt.source_revision == (1 if mode == "preflight" else 2 if mode == "requested" else 3)
    assert flow.events.count("spawn") == (0 if mode == "preflight" else 1)
    with flow.records.journal._connect() as db:
        before = tuple(tuple(row) for row in db.execute("SELECT * FROM harness_unit_sessions"))
        assert len(before) == 1

    def no_open(*_args, **_kwargs):
        raise AssertionError("retained start reached a new native launch")
    monkeypatch.setattr(flow.instance.channel_factory, "open", no_open)
    with pytest.raises((UnitLifecycleRefused, UnitRecordsRefused)):
        flow.instance.start(prepared, flow.authority.issue("start"))
    assert flow.records.owner_read_session(identity) == receipt
    with flow.records.journal._connect() as db:
        assert tuple(tuple(row) for row in db.execute("SELECT * FROM harness_unit_sessions")) == before
    assert flow.events.count("spawn") == (0 if mode == "preflight" else 1)

    if mode != "preflight":
        evidence = AcpUnitEvidence(preparation_authority=lambda plan, facts: plan["context"]["privateRootFacts"],
                                  start_authority=flow.authority.continuation)
        records = UnitRecords(OperationJournal(flow.records.journal.path), scope_authority=Scope(),
            native_evidence=evidence, verifier=flow.authority,
            epoch_port=SimpleNamespace(current_epoch=lambda _node: 0), termination_evidence=evidence)
        evidence.attach_owner(records)
        original = flow.instance
        cold = UnitInstance(descriptor=original.descriptor, agent_id=original.agent_id,
            profile_revision=original.profile_revision, environment_instance=flow.environments,
            environment_sharing=True, environment_reference=original.definition.environment_reference,
            preparation=Preparation(flow.events), materializer=lambda *_args: None,
            records=records, projection=evidence, verifier=flow.authority,
            lease_port=ConnectionLeasePort(), termination_evidence=evidence, timeout=2)
        monkeypatch.setattr(cold.channel_factory, "open", no_open)
        with pytest.raises((UnitLifecycleRefused, UnitRecordsRefused)):
            cold.start(prepared, flow.authority.issue("start"))
        if mode == "accepted":
            # A cold facade has no same-channel native proof. It must refuse
            # live confirmation while preserving the exact durable receipt.
            with pytest.raises(UnitLifecycleRefused, match="same-channel session receipt"):
                records.owner_read_session(identity)
        else:
            assert records.owner_read_session(identity) == receipt
        with records.journal._connect() as db:
            assert tuple(tuple(row) for row in db.execute("SELECT * FROM harness_unit_sessions")) == before
        assert flow.events.count("spawn") == 1

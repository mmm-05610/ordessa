"""PE2-4 controlled tests: native evidence present/absent/readback-inconsistent.

Driven exclusively by controlled brand stand-ins against the real operation
journal; zero real-model calls. An absent fact must read back as None, never
as a synthesized bundle.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import sqlite3

import pytest

from ordessa_harness_api import ApplicationTarget, Confirmed, ContractError, Plan
from ordessa_harness_api.native_evidence import (
    LaunchProvenanceFacts, NativeEvidence, NativeOwnerReceiptFacts,
    NativeSessionIdentityFacts,
)
from ordessa_harness.application import (
    ControlledNativeStandIn, EVIDENCE_SUPPORTED_BRANDS, EVIDENCE_UNSUPPORTED_BRANDS,
    FenceObservation, NativeActivationReceipt, NativeEvidenceService,
    NativeEvidenceUnsupported, OperationJournal, supply_brand_evidence,
)
from ordessa_harness.registry.loader import load_builtin_registry
from ordessa_harness.server_acp.registry import NativeSessionObservation


NOW = datetime(2026, 9, 28, 12, 0, tzinfo=timezone.utc)
TARGET = ApplicationTarget("server", "session", "channel", 7)


def plan(*, plan_id="plan-a", digest="a" * 64, target=TARGET):
    return Plan(plan_id, target, digest, "before-1", "native-1", 3,
                "auth-1", "secret-refs-1", (NOW + timedelta(minutes=5)).isoformat())


def journal(tmp_path):
    return OperationJournal(tmp_path / "operation.sqlite")


def reserved(store, selected, key="one", principal="alice"):
    store.register_plan(principal, selected)
    record, created = store.reserve_new(principal, selected.plan_id, key,
                                        FenceObservation.from_plan(selected), now=NOW)
    assert created
    return record


def digest_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def test_receipt_facts_dto_is_frozen_to_the_c4_receipt_shape():
    receipt = NativeActivationReceipt("op-1", TARGET, "f" * 64, "pi:native-session-1",
                                      "applied-1", "pi:native-owner:op-1")
    facts = NativeOwnerReceiptFacts(receipt.operation_id, receipt.target,
                                    receipt.manifest_digest, receipt.native_session_identity,
                                    receipt.applied_revision, receipt.evidence_ref)
    assert facts.kind == "native-owner-receipt"
    with pytest.raises(ContractError):
        NativeOwnerReceiptFacts("op-1", TARGET, "not-a-digest", "s", "r", "e")
    complete_receipt = NativeOwnerReceiptFacts("op-1", TARGET, "f" * 64, "s", "r", "e")
    with pytest.raises(ContractError):
        NativeEvidence(complete_receipt, None, "complete")
    with pytest.raises(ContractError):
        NativeEvidence(complete_receipt, None, "partial")
    with pytest.raises(ContractError):
        LaunchProvenanceFacts("pi", "pi", "2.0", "sha256:x", "upstream", "pi",
                              (("exec", ("pi",), "stdio"),), "not-bool")
    with pytest.raises(ContractError):
        NativeSessionIdentityFacts("pi", "conn", "exec", "ledger", " ")


def test_absent_operation_and_bare_reservation_read_as_none(tmp_path):
    store = journal(tmp_path)
    service = NativeEvidenceService(store)
    assert service.operation_evidence("alice", TARGET, "missing-op") is None
    record = reserved(store, plan())
    assert service.operation_evidence("alice", TARGET, record.operation_id) is None
    store.bind_native_manifest("alice", TARGET, record.operation_id, "f" * 64)
    assert service.operation_evidence("alice", TARGET, record.operation_id) is None
    assert service.operation_evidence("bob", TARGET, record.operation_id) is None


def test_receipt_without_independent_readback_is_partial(tmp_path):
    store = journal(tmp_path)
    service = NativeEvidenceService(store)
    record = reserved(store, plan())
    receipt = NativeActivationReceipt(record.operation_id, TARGET, "f" * 64,
                                      "pi:native-session-1", "applied-1", "pi:native-owner:1")
    store.bind_native_manifest("alice", TARGET, record.operation_id, receipt.manifest_digest)
    store.record_native_receipt("alice", TARGET, receipt)
    evidence = service.operation_evidence("alice", TARGET, record.operation_id)
    assert evidence is not None and evidence.status == "partial"
    assert evidence.readback is None and evidence.reason


@pytest.mark.parametrize("brand", EVIDENCE_SUPPORTED_BRANDS)
def test_supported_brands_supply_complete_evidence_from_durable_state(tmp_path, brand):
    store = journal(tmp_path)
    service = NativeEvidenceService(store)
    selected = plan(plan_id=f"plan-{brand}", digest=digest_of(brand))
    store.register_plan("alice", selected)
    stand_in = ControlledNativeStandIn(brand=brand)
    evidence = supply_brand_evidence(store, service, stand_in, "alice", selected,
                                     f"supply-{brand}", now=NOW)
    operation_id = evidence.receipt.operation_id
    assert evidence.status == "complete"
    assert evidence.receipt.native_session_identity == f"{brand}:native-session-1"
    assert evidence.receipt.evidence_ref == f"{brand}:native-owner:{operation_id}"
    assert evidence.readback.readback_evidence_ref == f"{brand}:native-readback:{operation_id}"
    assert evidence.readback.distinct_from_receipt
    assert evidence.readback.consistent_with_receipt
    reopened = NativeEvidenceService(journal(tmp_path))
    assert reopened.operation_evidence("alice", TARGET, operation_id) == evidence


def test_readback_recorded_before_confirmation_is_partial(tmp_path):
    store = journal(tmp_path)
    service = NativeEvidenceService(store)
    selected = plan(plan_id="plan-pi", digest=digest_of("pi"))
    store.register_plan("alice", selected)
    stand_in = ControlledNativeStandIn(brand="pi")
    record = reserved(store, selected, key="pi-key")
    receipt = stand_in.issue_receipt(record.operation_id, TARGET, digest_of("manifest"))
    store.bind_native_manifest("alice", TARGET, record.operation_id, receipt.manifest_digest)
    store.record_native_receipt("alice", TARGET, receipt)
    store.record_native_verification("alice", TARGET, record.operation_id,
                                     f"pi:native-readback:{record.operation_id}")
    evidence = service.operation_evidence("alice", TARGET, record.operation_id)
    assert evidence.status == "partial"
    assert evidence.readback.consistent_with_receipt is False


def _tamper(tmp_path_store, sql, params):
    with sqlite3.connect(tmp_path_store.path) as db:
        db.execute(sql, params)


def test_readback_reusing_activation_ref_is_inconsistent(tmp_path):
    store = journal(tmp_path)
    service = NativeEvidenceService(store)
    selected = plan(plan_id="plan-pi", digest=digest_of("pi"))
    record = reserved(store, selected)
    receipt = NativeActivationReceipt(record.operation_id, TARGET, "f" * 64,
                                      "pi:native-session-1", "applied-1", "pi:native-owner:1")
    store.bind_native_manifest("alice", TARGET, record.operation_id, receipt.manifest_digest)
    store.record_native_receipt("alice", TARGET, receipt)
    store.record_native_verification("alice", TARGET, record.operation_id, "pi:native-readback:1")
    confirmed = Confirmed(record.operation_id, "applied-1", "pi:native-session-1", 7,
                          "pi:native-readback:1", ("private-generation",))
    store.record_result("alice", TARGET, record.operation_id, confirmed)
    assert service.operation_evidence("alice", TARGET, record.operation_id).status == "complete"
    # controlled fault injection: a readback row that reuses the activation ref
    _tamper(store, "UPDATE native_verifications SET readback_evidence_ref=? WHERE operation_id=?",
            ("pi:native-owner:1", record.operation_id))
    evidence = service.operation_evidence("alice", TARGET, record.operation_id)
    assert evidence.status == "inconsistent"
    assert "reuses the activation evidence ref" in evidence.reason
    assert evidence.readback.distinct_from_receipt is False


def test_confirmed_identity_conflicting_with_receipt_is_inconsistent(tmp_path):
    store = journal(tmp_path)
    service = NativeEvidenceService(store)
    selected = plan(plan_id="plan-pi", digest=digest_of("pi"))
    record = reserved(store, selected)
    receipt = NativeActivationReceipt(record.operation_id, TARGET, "f" * 64,
                                      "pi:native-session-1", "applied-1", "pi:native-owner:1")
    store.bind_native_manifest("alice", TARGET, record.operation_id, receipt.manifest_digest)
    store.record_native_receipt("alice", TARGET, receipt)
    store.record_native_verification("alice", TARGET, record.operation_id, "pi:native-readback:1")
    forged = Confirmed(record.operation_id, "applied-1", "forged-session", 7,
                       "pi:native-readback:1", ())
    # the journal itself refuses this confirmation...
    with pytest.raises(Exception, match="differs"):
        store.record_result("alice", TARGET, record.operation_id, forged)
    # ...so inject the contradictory durable row directly (fault injection)
    _tamper(store, "UPDATE operations SET state='confirmed', result_json=? WHERE operation_id=?",
            (json.dumps(asdict(forged)), record.operation_id))
    evidence = service.operation_evidence("alice", TARGET, record.operation_id)
    assert evidence.status == "inconsistent"
    assert evidence.readback.consistent_with_receipt is False


def test_unsupported_brands_are_registered_with_reasons_not_fabrication():
    assert set(EVIDENCE_UNSUPPORTED_BRANDS) == {"hermes", "opencode", "dsh", "kilo"}
    assert set(EVIDENCE_SUPPORTED_BRANDS) == {"pi", "codex", "claude-code"}
    for brand, reason in EVIDENCE_UNSUPPORTED_BRANDS.items():
        with pytest.raises(NativeEvidenceUnsupported) as refused:
            ControlledNativeStandIn(brand=brand)
        assert refused.value.args[0] == reason
    with pytest.raises(NativeEvidenceUnsupported):
        ControlledNativeStandIn(brand="not-a-registered-brand")


class _FakeChannel:
    def __init__(self, harness_id):
        self.harness_id = harness_id


class _FakeChannelReader:
    def __init__(self):
        self._observations = {("conn-1", "native-1"): NativeSessionObservation(
            "conn-1", "exec-1", "ledger-1", "native-1")}

    def native_session_observation(self, connection_id, native_session_id):
        return self._observations.get((connection_id, native_session_id))

    def get(self, connection_id):
        return _FakeChannel("pi") if connection_id == "conn-1" else None


def test_session_identity_maps_agent_confirmed_observation(tmp_path):
    service = NativeEvidenceService(journal(tmp_path), channel_reader=_FakeChannelReader())
    assert service.session_identity("conn-1", "native-1") == NativeSessionIdentityFacts(
        "pi", "conn-1", "exec-1", "ledger-1", "native-1")
    assert service.session_identity("conn-1", "unknown-native") is None
    assert service.session_identity("gone-conn", "native-1") is None
    assert NativeEvidenceService(journal(tmp_path)).session_identity("conn-1", "native-1") is None


def test_launch_provenance_reads_declared_registry_facts(tmp_path):
    service = NativeEvidenceService(journal(tmp_path), registry=load_builtin_registry())
    facts = service.launch_provenance("pi")
    assert facts is not None and facts.driver == "pi"
    assert facts.launch_source == "upstream" and facts.launch_profile_id == "pi"
    assert any(mode[0] == "exec" for mode in facts.launch_modes)
    assert not facts.controlled
    assert service.launch_provenance("not-a-brand") is None
    assert service.launch_provenance("opencode") is None  # canonical route is declared null

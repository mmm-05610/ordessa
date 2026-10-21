"""Read-only native evidence projection on the original operation journal.

Optional captured registry and live channel observation ports supply already
observed facts. This projection creates no ledger, receipts, authority or effects.
"""
from __future__ import annotations
import json
from ordessa_agents.harness.definitions import ApplicationTarget
from ordessa_agents.harness.definitions.native_evidence import (
    LaunchProvenanceFacts, NativeEvidence, NativeOwnerReceiptFacts,
    NativeReadbackVerificationFacts, NativeSessionIdentityFacts,
)
from .operation_journal import OperationJournal

class NativeEvidenceService:
    """Read-only projection of persisted native facts; writes nothing."""

    def __init__(self, journal: OperationJournal, *, registry=None, channel_reader=None):
        self.journal = journal
        self.registry = registry
        self.channel_reader = channel_reader

    def operation_evidence(self, principal: str, target: ApplicationTarget,
                           operation_id: str) -> NativeEvidence | None:
        facts = self.journal.read_native_evidence(principal, target, operation_id)
        if facts is None or facts["receipt_json"] is None:
            return None
        data = json.loads(facts["receipt_json"])
        receipt = NativeOwnerReceiptFacts(data["operation_id"],
                                          ApplicationTarget(**data["target"]),
                                          data["manifest_digest"],
                                          data["native_session_identity"],
                                          data["applied_revision"], data["evidence_ref"])
        readback_ref = facts["readback_evidence_ref"]
        if readback_ref is None:
            return NativeEvidence(receipt, None, "partial",
                                  reason="native activation acknowledged; no independent readback verification recorded")
        distinct = readback_ref != receipt.evidence_ref
        if not distinct:
            verification = NativeReadbackVerificationFacts(receipt.operation_id, readback_ref,
                                                            False, False)
            return NativeEvidence(receipt, verification, "inconsistent",
                                  reason="readback verification reuses the activation evidence ref")
        result = json.loads(facts["result_json"]) if facts["result_json"] else None
        confirmed = (facts["state"] == "confirmed" and result is not None
                     and result.get("operation_id") == receipt.operation_id
                     and result.get("native_session_identity") == receipt.native_session_identity
                     and result.get("applied_revision") == receipt.applied_revision
                     and result.get("verification_evidence_ref") == readback_ref)
        verification = NativeReadbackVerificationFacts(receipt.operation_id, readback_ref,
                                                        True, confirmed)
        if facts["state"] == "confirmed" and not confirmed:
            return NativeEvidence(receipt, verification, "inconsistent",
                                  reason="confirmed result differs from native owner receipt")
        if not confirmed:
            return NativeEvidence(receipt, verification, "partial",
                                  reason="readback recorded; durable confirmation not established yet")
        return NativeEvidence(receipt, verification, "complete")

    def session_identity(self, connection_id: str,
                         native_session_id: str) -> NativeSessionIdentityFacts | None:
        if self.channel_reader is None:
            return None
        observation = self.channel_reader.native_session_observation(connection_id, native_session_id)
        if observation is None:
            return None
        channel = self.channel_reader.get(connection_id)
        if channel is None:
            return None
        return NativeSessionIdentityFacts(channel.harness_id, observation.connection_id,
                                         observation.execution_id, observation.ledger_session_id,
                                         observation.native_session_id)

    def launch_provenance(self, harness_type: str, *,
                          controlled: bool = False) -> LaunchProvenanceFacts | None:
        if self.registry is None:
            return None
        try:
            definition = self.registry.get(harness_type)
        except KeyError:
            definition = None
        descriptors = getattr(self.registry, "launch_descriptors", None) or {}
        route = (descriptors.get(harness_type) or {}).get("launch")
        if definition is None or route is None:
            return None
        return LaunchProvenanceFacts(harness_type, definition.driver,
                                     definition.identity.version, self.registry.digest,
                                     route["source"], route["profile_id"],
                                     tuple((mode.name, mode.argv, mode.io) for mode in definition.launch_modes),
                                     controlled)


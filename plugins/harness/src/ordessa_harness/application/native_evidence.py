"""PE2 native observation facts: read-side service over the C4 receipt protocol.

The three observation surfaces (native owner receipt, native session identity,
launch provenance) are read from the surfaces that already produce them:
``OperationJournal`` native evidence rows, the ACP channel registry's
Agent-confirmed session observation, and the built-in Harness registry's
declared launch reference.  Nothing here synthesizes an observation: an absent
fact returns None, a contradicting pair of proofs reports ``inconsistent``,
and an acknowledged effect without independent readback reports ``partial``.

``ControlledNativeStandIn`` is the controlled substitute driver required by
the dispatch: it exercises the real journal receipt sequence per brand with
zero real-model calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json

from ordessa_harness_api import ApplicationTarget, Confirmed, Plan, Refused
from ordessa_harness_api.native_evidence import (
    LaunchProvenanceFacts, NativeEvidence, NativeOwnerReceiptFacts,
    NativeReadbackVerificationFacts, NativeSessionIdentityFacts,
)

from .operation_journal import (
    FenceObservation, NativeActivationReceipt, OperationJournal,
)

EVIDENCE_SUPPORTED_BRANDS = ("pi", "codex", "claude-code")
EVIDENCE_UNSUPPORTED_BRANDS = {
    "hermes": "no owner-side activation receipt surface in the brand adapter; "
              "016 brand ruling defers this brand to phase-two design",
    "opencode": "no owner-side activation receipt surface in the brand adapter; "
                "016 brand ruling defers this brand to phase-two design",
    "dsh": "no owner-side activation receipt surface in the brand adapter; "
           "016 brand ruling defers this brand to phase-two design",
    "kilo": "no owner-side activation receipt surface in the brand adapter; "
            "016 brand ruling defers this brand to phase-two design",
}


class NativeEvidenceUnsupported(ValueError):
    """Raised when a brand has no registered evidence supply."""


def _manifest_digest(files: tuple[tuple[tuple[str, ...], str], ...]) -> str:
    encoded = json.dumps(files, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ControlledNativeStandIn:
    """One brand's controlled native owner: issues C4 receipts, touches no model."""

    brand: str
    native_session_identity: str = "native-session-1"
    applied_revision: str = "applied-1"

    def __post_init__(self) -> None:
        if self.brand in EVIDENCE_UNSUPPORTED_BRANDS:
            raise NativeEvidenceUnsupported(EVIDENCE_UNSUPPORTED_BRANDS[self.brand])
        if self.brand not in EVIDENCE_SUPPORTED_BRANDS:
            raise NativeEvidenceUnsupported(f"brand {self.brand!r} has no registered evidence supply")

    def generation_files(self, operation_id: str) -> tuple[tuple[tuple[str, ...], str], ...]:
        content_digest = hashlib.sha256(f"{self.brand}:{operation_id}".encode("utf-8")).hexdigest()
        return ((("private", "settings.json"), content_digest),)

    def issue_receipt(self, operation_id: str, target: ApplicationTarget,
                      manifest_digest: str) -> NativeActivationReceipt:
        return NativeActivationReceipt(operation_id, target, manifest_digest,
                                       f"{self.brand}:{self.native_session_identity}",
                                       self.applied_revision,
                                       f"{self.brand}:native-owner:{operation_id}")

    def observe(self, receipt: NativeActivationReceipt,
                files: tuple[tuple[tuple[str, ...], str], ...]):
        from .configuration_service import NativeReadback
        return NativeReadback(receipt.target, receipt.native_session_identity,
                              receipt.applied_revision, {"stand-in": self.brand}, files,
                              f"{self.brand}:native-readback:{receipt.operation_id}",
                              ("private-generation",), receipt)


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


def supply_brand_evidence(journal: OperationJournal, service: NativeEvidenceService,
                          stand_in: ControlledNativeStandIn, principal: str,
                          plan: Plan, operation_key: str,
                          now: datetime | None = None) -> NativeEvidence:
    """Drive the C4 receipt sequence once for one brand through its stand-in.

    Every step goes through the journal's existing protocol methods; the
    evidence returned is read back from durable state, never constructed inline.
    """
    reservation, created = journal.reserve_new(
        principal, plan.plan_id, operation_key, FenceObservation.from_plan(plan),
        now=now or datetime.now(timezone.utc))
    if isinstance(reservation, Refused) or not created:
        raise NativeEvidenceUnsupported("controlled supply requires a fresh reservation")
    receipt = stand_in.issue_receipt(reservation.operation_id, plan.target,
                                     _manifest_digest(stand_in.generation_files(reservation.operation_id)))
    journal.bind_native_manifest(principal, plan.target, reservation.operation_id, receipt.manifest_digest)
    journal.record_native_receipt(principal, plan.target, receipt)
    readback = stand_in.observe(receipt, stand_in.generation_files(reservation.operation_id))
    journal.record_native_verification(principal, plan.target, reservation.operation_id,
                                       readback.evidence_ref)
    journal.record_result(principal, plan.target, reservation.operation_id,
                          Confirmed(reservation.operation_id, readback.applied_revision,
                                    readback.native_session_identity,
                                    plan.target.runtime_generation, readback.evidence_ref,
                                    readback.resource_changes))
    evidence = service.operation_evidence(principal, plan.target, reservation.operation_id)
    if evidence is None:
        raise NativeEvidenceUnsupported("controlled supply produced no durable evidence")
    return evidence

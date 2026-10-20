"""Controlled brand stand-ins for original native evidence regression tests.

These fixtures exercise real journal transactions and receipts. They never
claim real native/model quality or provide a production fallback.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from ordessa_execution_agents.harness.definitions import ApplicationTarget, Confirmed, Plan, Refused
from ordessa_execution_agents.harness.definitions.native_evidence import NativeEvidence
from ordessa_execution_agents.units.records.operation_journal import (
    FenceObservation, NativeActivationReceipt, OperationJournal,
)
from ordessa_execution_agents.units.records.native_evidence import NativeEvidenceService

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
        from ordessa_execution_agents.harness.contracts.models.application import NativeReadback
        return NativeReadback(receipt.target, receipt.native_session_identity,
                              receipt.applied_revision, {"stand-in": self.brand}, files,
                              f"{self.brand}:native-readback:{receipt.operation_id}",
                              ("private-generation",), receipt)


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



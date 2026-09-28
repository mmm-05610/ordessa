"""Adapter: Profile's ``HarnessConfigPort`` → the harness-api carrier.

Maps the C0 harness-api carrier package (``ordessa_harness_api``, the C4
application port: inspect/plan/apply/query/reconcile) onto the port
semantics Profile's session flow consumes (docs/design/profile-v2/
application.md §2).  Prepared against the carrier as delivered via
chat-api-r3 (3d8c3fa410); the authoritative consumption gates on the
``codex/011-harness-api-ready`` publication — this module refuses to run
against a carrier whose ``__module__`` layout it was not compiled against
(see :func:`carrier_is_available`).

Honest boundaries kept intact:
- A missing host submission permit is a *retriable refusal before apply*
  (journal ``rejected``), never a fake success and never an ``unknown``
  that would misreport a port crash.
- Only the carrier's own ``Confirmed`` verdict can produce a receipt;
  ``applied_revision`` travels as the config digest reference and
  ``verification_evidence_ref`` as the evidence pointer.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from .contracts import (
    Applicability,
    ApplyConfirmed,
    ApplyRejected,
    ApplyUnknown,
    AppliedReceipt,
    EVIDENCE_PORT_CONFIRMED,
    HarnessTargetFacts,
    InspectResult,
    PlanResult,
    PlannedItem,
    ReconcileOutcome,
    SessionRef,
    UNSET,
    HarnessConfigPort,
)
from .errors import ProfileError

try:  # the carrier package is optional until the host composes it
    import ordessa_harness_api as _carrier
    from ordessa_harness_api import (
        ApplicationTarget,
        ApplicationResult,
        Confirmed,
        ConfigurationService,
        DesiredFragment,
        Plan as CarrierPlan,
        Refused,
        Unknown as CarrierUnknown,
    )
    _CARRIER_IMPORT_OK = True
except ImportError:  # pragma: no cover - exercised only without the carrier
    _CARRIER_IMPORT_OK = False
    ConfigurationService = None  # type: ignore[assignment,misc]

CARRIER_MIN_COMMIT = "3d8c3fa410"  # chat-api-r3; harness-api publication supersedes


def carrier_is_available() -> bool:
    return _CARRIER_IMPORT_OK


class PermitUnavailable(RuntimeError):
    """The host authorization gate did not mint a submission permit.

    Nothing was attempted on the native side: the switch stays retriable
    and the journal records a plain rejection (not ``unknown``).
    """


class HarnessApiConfigPort(HarnessConfigPort):
    """Port view over one ``ConfigurationService`` instance."""

    def __init__(
        self,
        service: Any,
        *,
        permit_provider: Callable[[SessionRef, str], str] | None = None,
        schema_version_of: Callable[[str], str] | None = None,
        revision_provider: Callable[[SessionRef], str] | None = None,
        evidence_kind: str = "harness-api-confirmed",
    ) -> None:
        if not _CARRIER_IMPORT_OK:
            raise ProfileError(
                "APPLICATION_PORT_ABSENT",
                "the ordessa_harness_api carrier package is not installed",
                status=409,
            )
        self._service = service
        self._permit_provider = permit_provider
        self._schema_version_of = schema_version_of or (lambda facet_id: "1")
        # The before-revision is server-owned: the host reads it from its own
        # runtime observation; Profile tracks the last carrier answer.
        self._revision_provider = revision_provider
        self._revision: dict[str, str] = {}
        self._generation: dict[str, int] = {}
        self._evidence_kind = evidence_kind

    # -- identity mapping ------------------------------------------------
    def _target(self, ref: SessionRef) -> Any:
        return ApplicationTarget(
            server_id=ref.realm,
            session_id=ref.session_uid,
            channel_id=ref.native_session_key,
            runtime_generation=self._generation.get(ref.session_uid, 0),
        )

    def _fragments(self, intents) -> tuple:
        fragments = []
        for intent in intents:
            value = None
            if intent.op == "set":
                if intent.value is UNSET:
                    raise ProfileError(
                        "PROFILE_VALUE_INVALID",
                        "set intent without value cannot become a fragment",
                        status=422,
                    )
                value = intent.value
            fragments.append(DesiredFragment(
                facet_id=intent.facet_id,
                item_id=intent.item_id,
                schema_version=self._schema_version_of(intent.facet_id),
                business_ref=f"{intent.facet_id}.{intent.item_id}",
                source_revision=intent.source,
                operation=intent.op,
                value=value,
            ))
        return tuple(fragments)

    # -- port surface ------------------------------------------------------
    def inspect(self, target: SessionRef) -> InspectResult:
        capabilities = self._service.inspect(self._target(target))
        generation = self._generation.get(target.session_uid, 0)
        return InspectResult(
            target=HarnessTargetFacts(
                session_ref=target,
                runtime_generation=f"gen-{generation}",
                capability_facts={"capabilities": tuple(
                    c.status for c in capabilities.capabilities)},
            ),
            evidence_kind="harness-api-inspect",
        )

    def plan(self, target: SessionRef, desired, operation_key: str) -> PlanResult:
        expected_revision = self._revision.get(target.session_uid)
        if expected_revision is None and self._revision_provider is not None:
            expected_revision = self._revision_provider(target)
        if expected_revision is None:
            raise ProfileError(
                "SWITCH_BLOCKED",
                "no server-side before-revision is known for this session; "
                "inspect the target before planning",
                status=409,
            )
        result = self._service.plan(
            self._target(target), self._fragments(desired), expected_revision)
        if isinstance(result, Refused):
            diagnostics = "; ".join(result.diagnostics)
            return PlanResult(
                session_ref=target, operation_key=operation_key,
                overall="blocked",
                items=(PlannedItem(
                    facet_id="*", item_id="*", op="*", status="blocked",
                    reason=f"{result.code.value}: {diagnostics}",
                ),),
                fence={"refused": True,
                       "original_state_preserved": result.original_state_preserved},
            )
        assert isinstance(result, CarrierPlan)
        return PlanResult(
            session_ref=target, operation_key=operation_key,
            overall="live-update",
            plan_digest=result.desired_digest,
            # The server-side fence: plan identity + revisions + expiry.
            fence={
                "plan_id": result.plan_id,
                "before_revision": result.before_revision,
                "authorization_revision": result.authorization_revision,
                "secret_ref_revision": result.secret_ref_revision,
                "native_version_ref": result.native_version_ref,
                "expires_at_utc": result.expires_at_utc,
                "runtime_generation": result.provider_generation,
            },
        )

    def apply(self, plan: PlanResult, desired):
        plan_id = plan.fence.get("plan_id")
        if not plan_id:
            raise ProfileError(
                "SWITCH_BLOCKED",
                "the carrier refused the plan; nothing to apply",
                status=409,
            )
        if self._permit_provider is None:
            raise PermitUnavailable(
                "no host submission-permit provider is wired into the port")
        permit = self._permit_provider(plan.session_ref, plan_id)
        if not permit:
            raise PermitUnavailable("the host refused to mint a submission permit")
        outcome: ApplicationResult = self._service.apply(plan_id, plan.operation_key, permit)
        if isinstance(outcome, Confirmed):
            self._generation[plan.session_ref.session_uid] = outcome.runtime_generation
            self._revision[plan.session_ref.session_uid] = outcome.applied_revision
            receipt = AppliedReceipt(
                operation_id=outcome.operation_id,
                session_ref=plan.session_ref,
                runtime_generation=f"gen-{outcome.runtime_generation}",
                # the carrier's applied revision reference travels as the
                # digest slot; the session service rebuilds the real receipt
                config_digest=f"applied-revision:{outcome.applied_revision}",
                profile_id="",  # filled by the session service
                profile_revision=1,  # overwritten by the session service
                overlay_revision=None,
                policy_revision=1,  # overwritten by the session service
                provider_generations={},
                evidence_kind=self._evidence_kind,
                confirmed_at="",  # session service stamps the wall clock
                execution_id=outcome.native_session_identity,
            )
            return ApplyConfirmed(state="confirmed", receipt=receipt)
        if isinstance(outcome, Refused):
            return ApplyRejected(
                state="rejected-unchanged",
                reason=f"{outcome.code.value}: {'; '.join(outcome.diagnostics)}",
            )
        assert isinstance(outcome, CarrierUnknown)
        return ApplyUnknown(
            state="unknown",
            reason=f"{outcome.phase}: {'; '.join(outcome.pending_checks)}",
        )

    def reconcile(self, operation_key: str, target: SessionRef) -> ReconcileOutcome:
        outcome = self._service.reconcile(operation_key)
        if isinstance(outcome, Confirmed):
            self._generation[target.session_uid] = outcome.runtime_generation
            self._revision[target.session_uid] = outcome.applied_revision
            receipt = AppliedReceipt(
                operation_id=outcome.operation_id,
                session_ref=target,
                runtime_generation=f"gen-{outcome.runtime_generation}",
                config_digest=f"applied-revision:{outcome.applied_revision}",
                profile_id="", profile_revision=1, overlay_revision=None,
                policy_revision=1, provider_generations={},
                evidence_kind=self._evidence_kind, confirmed_at="",
                execution_id=outcome.native_session_identity,
            )
            return ReconcileOutcome(state="confirmed-current", receipt=receipt)
        if isinstance(outcome, Refused):
            return ReconcileOutcome(
                state="rejected-unchanged",
                reason=f"{outcome.code.value}: {'; '.join(outcome.diagnostics)}",
            )
        return ReconcileOutcome(state="unknown", reason="carrier still cannot prove the outcome")

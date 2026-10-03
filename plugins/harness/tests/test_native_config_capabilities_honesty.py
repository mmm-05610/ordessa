"""T007-03 pins: native configuration capabilities are declared honestly.

Facts pinned against this tree (source-inspected, not aspirational):

* Contract level: ``ConfigurationCapability`` / ``Assessment`` /
  ``ReconfigurationDecision`` cannot represent ``unsupported``/``unknown``
  without a reason, and the status vocabulary is closed. ``RuntimeRefused`` is
  a typed member of the ``RuntimeResult`` family; there is no empty-success
  variant.
* Real implementation: ``ConfigurationApplicationService.inspect`` reports
  nothing when no adapter is published (no fabricated support), and its
  compare-and-apply ``plan`` path answers undeclared/stale requests with typed
  ``Refused`` (``adapter-missing`` / ``stale-plan`` / ``invalid-fragment``);
  no native effect can run on those refusals.
* Controlled fake over the public ``ConfigurationService`` types: a capability
  declared ``supported`` accepts compare-and-apply only when
  ``expected_revision`` matches; an unsupported or unknown capability is a
  typed ``Refused(CAPABILITY_UNSUPPORTED)`` and never a ``Plan``/``Confirmed``
  /empty success. An unknown capability can never satisfy a required native
  guarantee.

Pin level: the positive acceptance path is pinned at the contract level with a
controlled fake; wiring it to a live adapter remains for 010/011 (the real
positive integration lives in
``plugins/harness/tests/test_configuration_service_controlled.py``).
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from ordessa_harness_api import (
    AdapterContext,
    ApplicationTarget,
    Assessment,
    ConfigurationAdapterDescriptor,
    ConfigurationCapabilities,
    ConfigurationCapability,
    Confirmed,
    ContractError,
    DesiredFragment,
    ErrorCode,
    FieldClaim,
    Installation,
    NotFound,
    Plan,
    Refused,
    ReconfigurationDecision,
    RuntimeRefused,
    TargetDescriptor,
    TargetHandle,
    ValueSchema,
    VersionRange,
)
from ordessa_harness_api.contracts import RuntimeConfirmed, RuntimeUnknown
from ordessa_harness.application import (
    ConfigurationApplicationService,
    OperationJournal,
    RuntimeSnapshot,
)
from ordessa_harness.materialization import MergeAuthority, TargetAuthority

_TARGET = ApplicationTarget("server-1", "session-1", "channel-1", 7)
_REVISION = "native-rev-7"
_CONFIDENCE_REASON = "native version unobserved; refusing to promise support"


def _refused(code: ErrorCode, message: str) -> Refused:
    return Refused(code, (message,), True)


class _ControlledCapabilityService:
    """Minimal ``ConfigurationService`` over the public C4 DTOs.

    The declaration surface is explicit: only a capability declared
    ``supported`` (with evidence) may accept a compare-and-apply plan; a
    missing, ``unsupported`` or ``unknown`` declaration is answered with a
    typed ``Refused`` carrying ``CAPABILITY_UNSUPPORTED``. ``guarantee=
    "required"`` models a caller that cannot accept an unknown native
    guarantee.
    """

    def __init__(self, target: ApplicationTarget, *, revision: str) -> None:
        self.target = target
        self.revision = revision
        self._declared: dict[tuple[str, str], ConfigurationCapability] = {}
        self._plans: dict[str, Plan] = {}

    def declare(
        self,
        facet_id: str,
        operation: str,
        status: str,
        *,
        reason: str | None = None,
        evidence_ref: str | None = None,
    ) -> ConfigurationCapability:
        capability = ConfigurationCapability(
            facet_id,
            "controlled-harness",
            (1, 0, 0),
            (1, 0, 0),
            "acp",
            "instance",
            operation,
            status,
            evidence_ref=evidence_ref,
            reason=reason,
        )
        self._declared[(facet_id, operation)] = capability
        return capability

    # -- ConfigurationService surface --------------------------------------
    def inspect(self, target: ApplicationTarget) -> ConfigurationCapabilities:
        assert target == self.target
        return ConfigurationCapabilities(target, tuple(self._declared.values()))

    def plan(
        self,
        target: ApplicationTarget,
        desired_fragments: tuple[DesiredFragment, ...],
        expected_revision: str,
        *,
        guarantee: str = "best-effort",
    ):
        if (
            not isinstance(desired_fragments, tuple)
            or not desired_fragments
            or any(not isinstance(item, DesiredFragment) for item in desired_fragments)
        ):
            return _refused(ErrorCode.INVALID_FRAGMENT, "nonempty typed fragments required")
        if guarantee not in {"best-effort", "required"}:
            return _refused(ErrorCode.INVALID_FRAGMENT, "unknown guarantee mode")
        for fragment in desired_fragments:
            capability = self._declared.get((fragment.facet_id, fragment.operation))
            if capability is None:
                return _refused(
                    ErrorCode.CAPABILITY_UNSUPPORTED,
                    f"{fragment.facet_id}/{fragment.operation} is undeclared",
                )
            if capability.status != "supported":
                detail = f"{fragment.facet_id}/{fragment.operation} is {capability.status}"
                if capability.reason:
                    detail = f"{detail}: {capability.reason}"
                return _refused(ErrorCode.CAPABILITY_UNSUPPORTED, detail)
            if guarantee == "required" and not capability.evidence_ref:
                return _refused(
                    ErrorCode.CAPABILITY_UNSUPPORTED,
                    f"{fragment.facet_id}/{fragment.operation} lacks required native evidence",
                )
        if expected_revision != self.revision:
            return _refused(ErrorCode.STALE_PLAN, "expected revision changed")
        digest = hashlib.sha256(
            json.dumps(
                [
                    [item.facet_id, item.item_id, item.operation, item.value]
                    for item in desired_fragments
                ],
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        plan = Plan(
            f"plan-{len(self._plans) + 1}",
            target,
            digest,
            self.revision,
            "native-version-1",
            1,
            "auth-1",
            "secret-ref-1",
            "2030-01-01T00:00:00+00:00",
        )
        self._plans[plan.plan_id] = plan
        return plan

    def apply(self, plan_id: str, operation_key: str, submission_permit: str):
        if plan_id not in self._plans:
            return _refused(ErrorCode.STALE_PLAN, "plan unavailable")
        return _refused(ErrorCode.AUTHORIZATION_REFUSED, "controlled fake never applies")

    def query(self, operation_key: str):
        return NotFound(operation_key)

    def reconcile(self, operation_key: str):
        return _refused(ErrorCode.OPERATION_UNKNOWN, "operation not found")


class _CaptureOnlyRuntime:
    """Real ``ControlledRuntime`` seam that can only snapshot, never affect."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.activate_calls = 0

    def capture(self, target: ApplicationTarget) -> RuntimeSnapshot:
        descriptor = ConfigurationAdapterDescriptor(
            "controlled.capture-only",
            "v1",
            "model",
            "v1",
            "controlled-harness",
            VersionRange((1, 0, 0)),
            VersionRange((1, 0, 0)),
            ("acp",),
            ValueSchema("object", properties=(("model", ValueSchema("string")),)),
            (FieldClaim("file", "controlled-config", ("model",)),),
        )
        context = AdapterContext(
            (TargetDescriptor(TargetHandle("controlled-config", 7), "file", "json", "instance"),),
            Installation("controlled-harness", (1, 0, 0), (1, 0, 0), "fixture:capture-only"),
            "acp",
            "instance",
            "fixture:capability",
        )
        return RuntimeSnapshot(
            target,
            context,
            MergeAuthority(()),
            {},
            {},
            self.root,
            {},
            _REVISION,
            "native-version-1",
            1,
            "auth-1",
            "secret-ref-1",
        )

    def activate_generation(self, *args):
        self.activate_calls += 1
        raise AssertionError("a refused plan must never reach the native effect")

    def observe(self, *args):
        self.activate_calls += 1
        raise AssertionError("a refused plan must never reach native readback")


class _AbsentCarrier:
    """No published contribution; ``contributions`` is deliberately absent."""


class _RefusingPermit:
    def verify(self, *args):
        raise AssertionError("a refused plan must never spend a permit")


def _fragment(facet_id: str = "model", operation: str = "set") -> DesiredFragment:
    return DesiredFragment(
        facet_id,
        "controlled-item",
        "v1",
        "business:controlled",
        "source-1",
        operation,
        {"model": "controlled-model"} if operation == "set" else None,
    )


def test_capability_contract_rejects_silent_unsupported_claims():
    for status in ("unsupported", "unknown"):
        with pytest.raises(ContractError):
            ConfigurationCapability(
                "model", "controlled-harness", None, None, "acp", "instance", "set", status
            )
        assessment = Assessment(status, reason=_CONFIDENCE_REASON)
        assert assessment.status == status and assessment.reason
    with pytest.raises(ContractError):
        Assessment("maybe")
    supported = ConfigurationCapability(
        "model",
        "controlled-harness",
        (1, 0, 0),
        (1, 0, 0),
        "acp",
        "instance",
        "set",
        "supported",
        evidence_ref="fixture:model-pin",
    )
    assert supported.status == "supported" and supported.evidence_ref
    with pytest.raises(ContractError):
        ReconfigurationDecision("unsupported", ())
    assert ReconfigurationDecision("unsupported", (), reason="no native reload").mode == "unsupported"


def test_runtime_result_family_keeps_refusal_typed_and_distinct():
    refused = RuntimeRefused(ErrorCode.CAPABILITY_UNSUPPORTED, _CONFIDENCE_REASON)
    assert refused.kind == "refused" and refused.code is ErrorCode.CAPABILITY_UNSUPPORTED
    with pytest.raises(ContractError):
        RuntimeRefused(ErrorCode.CAPABILITY_UNSUPPORTED, "")
    assert RuntimeConfirmed("instance-1", "native-1", 1, "fixture:proof").kind == "confirmed"
    unknown = RuntimeUnknown("instance-1", (), ("read-back",))
    assert unknown.kind == "unknown" and unknown.pending_checks
    with pytest.raises(ContractError):
        RuntimeUnknown("instance-1", (), ())


def test_real_service_declares_nothing_without_a_published_adapter(tmp_path):
    runtime = _CaptureOnlyRuntime(tmp_path / "generations")
    journal = OperationJournal(tmp_path / "operations.sqlite")
    service = ConfigurationApplicationService(
        principal="controlled-principal",
        target=_TARGET,
        carrier=_AbsentCarrier(),
        runtime=runtime,
        permits=_RefusingPermit(),
        journal=journal,
    )

    declaration = service.inspect(_TARGET)
    assert isinstance(declaration, ConfigurationCapabilities)
    assert declaration.target == _TARGET
    assert declaration.capabilities == ()

    stale = service.plan(_TARGET, (_fragment(),), "rev-does-not-match")
    assert isinstance(stale, Refused) and stale.code is ErrorCode.STALE_PLAN

    undeclared = service.plan(_TARGET, (_fragment(),), _REVISION)
    assert isinstance(undeclared, Refused)
    assert undeclared.code is ErrorCode.ADAPTER_MISSING
    assert undeclared.original_state_preserved is True

    empty = service.plan(_TARGET, (), _REVISION)
    assert isinstance(empty, Refused) and empty.code is ErrorCode.INVALID_FRAGMENT

    assert runtime.activate_calls == 0


def test_compare_and_apply_accepted_only_for_declared_supported_capability():
    service = _ControlledCapabilityService(_TARGET, revision=_REVISION)
    service.declare("model", "set", "supported", evidence_ref="fixture:model-pin")

    declaration = service.inspect(_TARGET)
    assert [(item.facet_id, item.operation, item.status) for item in declaration.capabilities] == [
        ("model", "set", "supported")
    ]

    planned = service.plan(_TARGET, (_fragment(),), _REVISION)
    assert isinstance(planned, Plan) and planned.kind == "plan"
    assert planned.before_revision == _REVISION

    stale = service.plan(_TARGET, (_fragment(),), "rev-does-not-match")
    assert isinstance(stale, Refused) and stale.code is ErrorCode.STALE_PLAN

    undeclared_facet = service.plan(_TARGET, (_fragment("theme"),), _REVISION)
    assert isinstance(undeclared_facet, Refused)
    assert undeclared_facet.code is ErrorCode.CAPABILITY_UNSUPPORTED
    assert not isinstance(undeclared_facet, Plan)

    undeclared_operation = service.plan(_TARGET, (_fragment("model", "reset"),), _REVISION)
    assert isinstance(undeclared_operation, Refused)
    assert undeclared_operation.code is ErrorCode.CAPABILITY_UNSUPPORTED


def test_unknown_capability_is_refused_not_reported_as_empty_success():
    service = _ControlledCapabilityService(_TARGET, revision=_REVISION)
    declaration = service.declare("model", "set", "unknown", reason=_CONFIDENCE_REASON)
    assert declaration.evidence_ref is None

    inspected = service.inspect(_TARGET).capabilities
    assert len(inspected) == 1
    assert inspected[0].status == "unknown"
    assert inspected[0].reason == _CONFIDENCE_REASON

    result = service.plan(_TARGET, (_fragment(),), _REVISION)
    assert isinstance(result, Refused)
    assert result.kind == "refused"
    assert result.code is ErrorCode.CAPABILITY_UNSUPPORTED
    assert "unknown" in result.diagnostics[0]
    assert not isinstance(result, (Plan, Confirmed))


def test_unsupported_capability_is_refused_not_reported_as_empty_success():
    service = _ControlledCapabilityService(_TARGET, revision=_REVISION)
    service.declare("model", "set", "unsupported", reason="native pin has no CAS surface")

    result = service.plan(_TARGET, (_fragment(),), _REVISION)
    assert isinstance(result, Refused)
    assert result.kind == "refused"
    assert result.code is ErrorCode.CAPABILITY_UNSUPPORTED
    assert "unsupported" in result.diagnostics[0]
    assert not isinstance(result, (Plan, Confirmed))


def test_unknown_capability_cannot_satisfy_a_required_guarantee():
    service = _ControlledCapabilityService(_TARGET, revision=_REVISION)
    service.declare("model", "set", "unknown", reason=_CONFIDENCE_REASON)
    service.declare("theme", "set", "supported", evidence_ref="fixture:theme-pin")

    refused = service.plan(_TARGET, (_fragment(),), _REVISION, guarantee="required")
    assert isinstance(refused, Refused)
    assert refused.code is ErrorCode.CAPABILITY_UNSUPPORTED
    assert "unknown" in refused.diagnostics[0]
    assert refused.original_state_preserved is True

    satisfiable = service.plan(_TARGET, (_fragment("theme"),), _REVISION, guarantee="required")
    assert isinstance(satisfiable, Plan), "the refusal must be specific to the unknown capability"

"""`PermissionsAcpAdmission` - the public ACP admission port over the §C1 authorizer.

This is the module the harness-api checkpoint registered as missing (G1: "The
default product's ACP admission port reports ready=False: Q5 authorizer ...
not wired"). It adapts the neutral `server_plugin_api` admission DTOs onto
`Authorizer`; it imports the plugin contract and the permissions domain and
nothing else - no host, no harness, no transport internals.

Translation contract (v1), shared verbatim with the port's consumers:

* a `AcpChannelBinding` supplies the trusted channel identity: ledger session,
  execution, native session and native generation (``str(runtime_generation)``),
  the principal from the composition's selected-identity provider (the binding
  itself carries no principal - a renderer never picks one) and the server
  instance from the composition;
* a `AcpSubmissionRequest` supplies the operation: ``command_id`` names the
  tool key (a submission with no declared tool identity is refused, never
  treated as "no rule"), the ``configuration_digest`` is the target, and the
  argument digest is the sha256 of the canonical submit snapshot
  (`submission_argument_digest`), never the raw arguments;
* the ceiling and policy revisions are derived from the providers actually in
  force (the same providers the authorizer rules under), and the
  ``submission_id`` is the native request id;
* an `AcpPermissionDecision` binds ``interaction_id`` to the recorded
  approvalId, ``run_id`` to the recorded native request id and ``option_id``
  to the recorded verdict ("allow"/"deny"), and is checked against the
  approval fact - cross-session, cross-run, foreign generation, forged
  option, staleness or a missing native receipt is a refusal.

Admission is granted for a submission only when the authorizer answers
`AllowedOnce` with a grant that binds this exact operation digest, target,
ceiling/policy revision and native generation (`BoundGrant.matches`). A
permission answer additionally spends the approval's one-use grant atomically
exactly once: a replay is `APPROVAL_STALE`, never a second `accepted`.

`ready` is derived, never assumed: it is true only while an authority is
installed AND the composition has configured an authoritative native-session
and runtime-generation evidence source that is currently answering complete
evidence. A version match alone is not readiness, and an incomplete binding is
refused regardless of readiness. Anything that cannot be resolved answers the
`unknown` shape only; the three shapes are mutually exclusive by the DTO, and
this module never catches that construction to fake an answer.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from typing import Any, Callable, Mapping, Protocol

from ordessa_permissions_api import (
    ApprovalDecision,
    ApprovalStateKind,
    BoundGrant,
    Denied,
    AllowedOnce,
    PendingApproval,
    PolicyCeiling,
    PolicyDenyCode,
    PermissionIntent,
    PolicyRefusal,
    RefusalCode,
    build_operation_request,
    intersect_ceilings,
)
from server_plugin_api import (
    ACP_ADMISSION_PORT_VERSION,
    AcpAdmissionResult,
    AcpChannelBinding,
    AcpPermissionDecision,
    AcpSubmissionRequest,
)

__all__ = ["PermissionsAcpAdmission", "submission_argument_digest"]

_VALID_OPTIONS = frozenset({"allow", "deny"})


def submission_argument_digest(submission: AcpSubmissionRequest) -> str:
    """The 64-hex digest of one submit snapshot - identity, not payload.

    Canonical JSON over exactly the protocol-relevant fields, so the same
    submission always digests the same and nothing else can ride along.
    """
    canonical = json.dumps({
        "nativeSessionId": submission.native_session_id,
        "text": submission.text,
        "attachments": [
            {"name": item.name, "uri": item.uri, "sha256": item.sha256,
             "mimeType": item.mime_type}
            for item in submission.attachments
        ],
        "configurationDigest": submission.configuration_digest,
        "commandId": submission.command_id,
    }, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class _AuthorizerLike(Protocol):
    """The exact §C1 surface this adapter may touch - nothing host-internal."""

    facts: Any
    ceiling_provider: Callable[[], Any]
    intent_provider: Callable[[], Any]
    clock: Callable[[], dt.datetime]

    def evaluate(self, **_kwargs: Any) -> Any: ...


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _text(value: Any) -> str:
    return value if isinstance(value, str) and value.strip() else ""


def _refusal_reason(refusal: PolicyRefusal) -> str:
    return refusal.human_readable[:240]


class PermissionsAcpAdmission:
    """An explicit `AcpAdmissionPort` adapter (composition installs it; the
    protocol is deliberately not runtime-checkable and grants no authority).
    """

    #: The harness gate refuses to call anything whose marker is not exactly
    #: an `int` equal to the frozen version, so this stays a plain attribute.
    public_acp_admission_port_version = ACP_ADMISSION_PORT_VERSION

    def __init__(self, *, authorizer: Any | None,
                 native_evidence: Callable[[], Mapping[str, Any] | None] | None = None,
                 principal_provider: Callable[[AcpChannelBinding], Any] | None = None,
                 server_instance_id: Any | None = None,
                 clock: Callable[[], dt.datetime] | None = None,
                 closed: Callable[[], bool] | None = None) -> None:
        self._authorizer: _AuthorizerLike | None = authorizer
        self._native_evidence = native_evidence
        self._principal_provider = principal_provider
        self._server_instance_id = server_instance_id
        self._clock = clock or _utc_now
        # The plugin's route lifecycle (T018): once the host's stop round has
        # accepted the deactivation, the grant route accepts no new decision -
        # a refused admission is the honest answer of a provider on its way
        # out, and absence of the gate means "always accepting".
        self._closed = closed if closed is not None else (lambda: False)

    # -- readiness ------------------------------------------------------------------

    @property
    def ready(self) -> bool:
        """True only with an installed authority AND an authoritative,
        currently-complete native-session/generation evidence source. A
        closed route lifecycle (T018) is never ready."""
        if self._closed():
            return False
        if self._authorizer is None or not callable(self._native_evidence):
            return False
        try:
            evidence = self._native_evidence()
        except Exception:
            return False
        return self._valid_evidence(evidence)

    def _closed_refusal(self) -> AcpAdmissionResult:
        """The deactivation answer of the grant route: a typed refusal, never
        a pass-through and never a fake `unknown` the transport would retry
        against a provider that is going away."""
        return self._refused(
            RefusalCode.POLICY_ADAPTER_MISSING,
            "the permissions backend is deactivating; no new decision is"
            " accepted while its provider settles")

    @staticmethod
    def _valid_evidence(evidence: Any) -> bool:
        if not isinstance(evidence, Mapping):
            return False
        native = evidence.get("nativeSessionId")
        generation = evidence.get("runtimeGeneration")
        return (isinstance(native, str) and bool(native.strip())
                and type(generation) is int and generation >= 0)

    # -- the port surface ------------------------------------------------------------

    def authorize_submission(self, binding: AcpChannelBinding,
                             submission: AcpSubmissionRequest) -> AcpAdmissionResult:
        submission_id = _text(getattr(submission, "submission_id", None)) or "invalid-submission"
        if self._closed():
            return self._closed_refusal()
        try:
            return self._authorize_submission(binding, submission)
        except Exception:
            # The port may have reserved or consumed a permit before its reply
            # failed: only its own typed refusal can prove refusal.
            return AcpAdmissionResult(
                kind="unknown", operation_id=submission_id,
                reason="the admission outcome could not be resolved; reconcile before retry")

    def authorize_permission(self, binding: AcpChannelBinding,
                             decision: AcpPermissionDecision) -> AcpAdmissionResult:
        interaction_id = _text(getattr(decision, "interaction_id", None)) or "invalid-permission"
        if self._closed():
            return self._closed_refusal()
        try:
            return self._authorize_permission(binding, decision)
        except Exception:
            return AcpAdmissionResult(
                kind="unknown", operation_id=interaction_id,
                reason="the permission outcome could not be resolved; reconcile before retry")

    # -- submission -------------------------------------------------------------------

    def _authorize_submission(self, binding: AcpChannelBinding,
                              submission: AcpSubmissionRequest) -> AcpAdmissionResult:
        if self._authorizer is None:
            return self._refused(RefusalCode.POLICY_ADAPTER_MISSING,
                                 "no permission authority is installed; absence refuses")
        if (not isinstance(binding, AcpChannelBinding)
                or not isinstance(submission, AcpSubmissionRequest)):
            return self._refused(RefusalCode.POLICY_SCOPE_UNVERIFIED,
                                 "admission inputs must be the public ACP DTOs")
        observed = self._observe_binding(binding)
        if isinstance(observed, AcpAdmissionResult):
            return observed
        native_session, generation_text = observed
        if submission.native_session_id != native_session:
            return self._refused(
                RefusalCode.POLICY_SCOPE_UNVERIFIED,
                "the submission names another native session than the bound channel")
        tool_key = _text(submission.command_id)
        if not tool_key:
            return self._refused(
                RefusalCode.PERMISSION_UNKNOWN_TOOL,
                "a submission with no command identity names no declared tool; "
                "an unknown tool is never treated as 'no rule'")
        principal = _text(self._principal(binding))
        if not principal:
            return self._refused(RefusalCode.POLICY_SCOPE_UNVERIFIED,
                                 "the selected identity for this channel cannot be attributed")
        instance = _text(self._server_instance_id()
                         if callable(self._server_instance_id)
                         else self._server_instance_id)
        if not instance:
            return self._refused(RefusalCode.POLICY_SCOPE_UNVERIFIED,
                                 "the server instance identity is not configured")
        try:
            operation = build_operation_request(
                principal=principal, server_instance_id=instance,
                session_id=binding.ledger_session_id, native_session_id=native_session,
                execution_id=binding.execution_id, native_generation=generation_text,
                tool_key=tool_key, target=submission.configuration_digest,
                argument_digest=submission_argument_digest(submission),
                native_request_id=submission.submission_id,
                ceilings=self._ceilings_in_force(), intent=self._intent_in_force())
        except PolicyRefusal as refusal:
            return self._refused(self._refusal_code(refusal), _refusal_reason(refusal))

        outcome = self._authorizer.evaluate(
            principal=operation.principal,
            session_ref={"serverInstanceId": operation.server_instance_id,
                         "sessionId": operation.session_id,
                         "nativeSessionId": operation.native_session_id},
            execution_ref=operation.execution_id,
            native_generation=operation.native_generation,
            tool_identity=operation.tool_key,
            target_facts={"target": operation.target},
            argument_digest=operation.argument_digest.value,
            ceiling_revision=operation.ceiling_revision,
            policy_revision=operation.policy_revision,
            native_request_id=operation.native_request_id)

        if isinstance(outcome, AllowedOnce):
            # accepted ONLY when the grant binds this exact operation digest,
            # target, ceiling/policy revision and native generation.
            if not self._grant_bound_to(operation, outcome.grant, generation_text):
                return self._refused(
                    RefusalCode.APPROVAL_STALE,
                    "the issued grant does not bind this exact operation, target,"
                    " revisions or native generation")
            return AcpAdmissionResult(kind="accepted", submission_id=submission.submission_id)
        if isinstance(outcome, PendingApproval):
            # An unresolved ask is a definite "not yet": the transport does not
            # carry the submission, and the id names what to decide.
            return self._refused(
                RefusalCode.APPROVAL_RESULT_UNKNOWN,
                f"the operation awaits approval {outcome.approval_id}; nothing may"
                " proceed before the native owner confirms")
        if isinstance(outcome, Denied):
            return self._refused(outcome.code,
                                 None if outcome.reason is None else outcome.reason.message)
        return self._unknown(submission.submission_id,
                             "the authorizer answered a shape this port cannot resolve")

    # -- permission answer --------------------------------------------------------------

    def _authorize_permission(self, binding: AcpChannelBinding,
                              decision: AcpPermissionDecision) -> AcpAdmissionResult:
        if self._authorizer is None:
            return self._refused(RefusalCode.POLICY_ADAPTER_MISSING,
                                 "no permission authority is installed; absence refuses")
        if (not isinstance(binding, AcpChannelBinding)
                or not isinstance(decision, AcpPermissionDecision)):
            return self._refused(RefusalCode.POLICY_SCOPE_UNVERIFIED,
                                 "admission inputs must be the public ACP DTOs")
        observed = self._observe_binding(binding)
        if isinstance(observed, AcpAdmissionResult):
            return observed
        native_session, generation_text = observed
        if decision.native_session_id != native_session:
            return self._refused(RefusalCode.POLICY_SCOPE_UNVERIFIED,
                                 "the decision names another native session than the bound channel")
        fact = self._authorizer.facts.approval_fact(decision.interaction_id)
        if fact is None:
            # An approval id is minted by the authority; one it never recorded
            # corroborates nothing.
            return self._refused(RefusalCode.APPROVAL_RESULT_UNKNOWN,
                                 "no recorded approval carries this interaction id")
        stale = "the decision does not bind the recorded approval's "
        if fact.state.session_id != binding.ledger_session_id:
            return self._refused(RefusalCode.APPROVAL_STALE,
                                 stale + "ledger session (cross-session answer)")
        if fact.state.execution_id != binding.execution_id:
            return self._refused(RefusalCode.APPROVAL_STALE,
                                 stale + "execution (cross-run answer)")
        if (fact.state.native_request_id != decision.run_id
                or fact.request.native_request_id != decision.run_id):
            return self._refused(RefusalCode.APPROVAL_STALE,
                                 stale + "native request id")
        if fact.request.native_generation != generation_text:
            return self._refused(RefusalCode.APPROVAL_STALE,
                                 stale + "native generation (the runtime moved)")
        now = self._moment()
        if not fact.request.alive_at(now):
            return self._refused(RefusalCode.APPROVAL_STALE,
                                 "the recorded approval has expired; request a fresh one")
        if decision.option_id not in _VALID_OPTIONS:
            return self._refused(RefusalCode.APPROVAL_STALE,
                                 "the option id names no verdict this port records")
        if fact.state.state is ApprovalStateKind.OPEN:
            return self._refused(RefusalCode.APPROVAL_RESULT_UNKNOWN,
                                 "the approval carries no recorded decision yet")
        if fact.state.state is ApprovalStateKind.INVALID:
            return self._refused(RefusalCode.APPROVAL_NOT_ACTIONABLE,
                                 "the approval was invalidated and can no longer act")
        recorded = ApprovalDecision(fact.state.decision.value)
        if decision.option_id != recorded.value:
            return self._refused(
                RefusalCode.APPROVAL_STALE,
                "the option id contradicts the recorded decision (forged answer)")
        if recorded is ApprovalDecision.DENY:
            # An honest denial answer is still a denial: refused, with the
            # stable policy code - never a pass-through.
            return self._refused(PolicyDenyCode.POLICY_DENY,
                                 "the user's recorded denial stands; nothing proceeds")
        if fact.receipt is None or not fact.receipt.confirmed:
            return self._refused(
                RefusalCode.APPROVAL_RESULT_UNKNOWN,
                "the native owner has not confirmed this approval; allow is not execution")
        spent = self._authorizer.facts.consume_grant(
            approval_id=fact.approval_id,
            operation_digest=fact.request.operation_digest,
            native_request_id=decision.run_id, moment=now)
        if not spent:
            return self._refused(
                RefusalCode.APPROVAL_STALE,
                "the one-use permit for this approval is spent or unbound;"
                " a replay never earns a second accepted")
        return AcpAdmissionResult(kind="accepted", submission_id=decision.interaction_id)

    # -- shared checks ---------------------------------------------------------------------

    def _observe_binding(self, binding: AcpChannelBinding):
        """(native session, generation text) or a refusal result: the binding's
        optional evidence must be observed AND agree with the authoritative
        source, or nothing proceeds."""
        if not self._authoritative_ready():
            return self._refused(
                RefusalCode.POLICY_ADAPTER_MISSING,
                "no authoritative native-session/generation evidence source is configured")
        if binding.native_session_id is None or binding.runtime_generation is None:
            return self._refused(
                RefusalCode.POLICY_SCOPE_UNVERIFIED,
                "the channel binding carries no observed native session or"
                " runtime generation; unobserved evidence never admits")
        evidence = self._native_evidence()
        if (evidence.get("nativeSessionId") != binding.native_session_id
                or evidence.get("runtimeGeneration") != binding.runtime_generation):
            return self._refused(
                RefusalCode.POLICY_SCOPE_UNVERIFIED,
                "the binding's native session or generation disagrees with the"
                " authoritative observation")
        return binding.native_session_id, str(binding.runtime_generation)

    def _authoritative_ready(self) -> bool:
        if self._authorizer is None or not callable(self._native_evidence):
            return False
        try:
            evidence = self._native_evidence()
        except Exception:
            return False
        return self._valid_evidence(evidence)

    def _principal(self, binding: AcpChannelBinding) -> Any:
        if not callable(self._principal_provider):
            return None
        return self._principal_provider(binding)

    def _ceilings_in_force(self) -> list[PolicyCeiling]:
        provider = getattr(self._authorizer, "ceiling_provider", None)
        raw = provider() if callable(provider) else ()
        items = list(raw or ())
        if not items:
            raise PolicyRefusal(RefusalCode.POLICY_ADAPTER_MISSING,
                                source="admission.ceilings_in_force",
                                target="no trusted ceiling is in force")
        intersect_ceilings(items)  # an unusable intersection refuses, never passes
        return items

    def _intent_in_force(self) -> PermissionIntent | None:
        provider = getattr(self._authorizer, "intent_provider", None)
        if not callable(provider):
            return None
        try:
            intent = provider()
        except PolicyRefusal:
            raise
        except Exception:
            raise PolicyRefusal(RefusalCode.POLICY_ADAPTER_MISSING,
                                source="admission.intent_in_force") from None
        return intent if isinstance(intent, PermissionIntent) else None

    @staticmethod
    def _grant_bound_to(operation: Any, grant: BoundGrant, generation_text: str) -> bool:
        try:
            return grant.matches(operation) and grant.native_generation == generation_text
        except (AttributeError, PolicyRefusal):
            return False

    @staticmethod
    def _refusal_code(refusal: PolicyRefusal) -> RefusalCode:
        code = refusal.refusal_code
        return code if code is not None else RefusalCode.POLICY_SCOPE_UNVERIFIED

    def _moment(self) -> dt.datetime:
        authorizer = self._authorizer
        clock = getattr(authorizer, "clock", None) if authorizer is not None else None
        return (clock() if callable(clock) else None) or self._clock()

    # -- result shapes ------------------------------------------------------------------------

    @staticmethod
    def _refused(code: Any, reason: str | None) -> AcpAdmissionResult:
        value = code.value if isinstance(code, (RefusalCode, PolicyDenyCode)) else str(code)
        text = (reason or value)[:240].replace("\n", " ").replace("\r", " ")
        return AcpAdmissionResult(kind="refused", code=value, reason=text)

    @staticmethod
    def _unknown(operation_id: str, reason: str) -> AcpAdmissionResult:
        return AcpAdmissionResult(kind="unknown",
                                  operation_id=_text(operation_id) or "unidentified-operation",
                                  reason=reason[:240])

"""`PermissionsHostAcpAuthority` - this lane, offered as the ACP admission
authority that the managed-channel fence asks for.

Why the seam is only half open, stated honestly because it decides what this
module may and may not promise:

* the tool-execution half is a plain `bool`. The fence admits an answer only
  when the authority's verdict *is* `True`, so a plugin can be that verifier
  with nothing but the public contract: it reads the live channel identity off
  the connection object the fence hands it, translates the camelCase wire
  members into the public DTOs, and answers through the admission port. `True`
  only for an `accepted` result that names this exact interaction; a refusal,
  an `unknown`, a malformed identity or an unavailable port is `False`.
* the submission half cannot be minted here. The fence verifies the permit
  against a frozen record type the composition owns itself, digests the prompt
  with its own private canonicalisation, and maps only its own exception type
  to a typed refusal - a plugin-raised refusal reaches the public port adapter
  as `unknown`. This package's dependency gate forbids importing or even
  naming that composition, so the permit record is **injected** as
  `permit_binder`: the one callable that only the composition can supply.
  Without a binder this authority refuses an otherwise-allowed submission with
  the same stable code the fence uses for a missing capability, never admits it.

Registered consequence of that ordering, measured by the suite rather than
argued: the ruling is made before the binder is consulted, so an
approval-bound allow burns its one-use grant while still admitting nothing.
A composition must therefore never install this authority without a binder
(that hazard, the absence of the binder in any shipped composition, and the
un-published permit record are the named public-contract gaps).

`request` (the fence's observed permission params) is deliberately not trusted
for identity: the port binds the interaction id to the recorded approval fact,
which is the only place a verdict exists.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from server_plugin_api import (
    AcpAdmissionResult,
    AcpAttachmentReference,
    AcpChannelBinding,
    AcpPermissionDecision,
    AcpSubmissionRequest,
)

__all__ = ["PERMIT_SEAM_UNPUBLISHED", "PluginAdmissionRefused",
           "PermissionsHostAcpAuthority"]

#: The spelling the fence itself uses for "no authority here": an absent
#: capability, never a permit and never a silent pass.
PERMIT_SEAM_UNPUBLISHED = "CAPABILITY_UNSUPPORTED"
_UNRESOLVED = "APPROVAL_RESULT_UNKNOWN"
_UNVERIFIED = "POLICY_SCOPE_UNVERIFIED"
_MISSING_PORT = "POLICY_ADAPTER_MISSING"


class PluginAdmissionRefused(ValueError):
    """A refusal that carries a stable code beside its message.

    It is a `ValueError`, the same base the fence's own refusal uses, so a
    caller that only knows how to stop can still treat it as "nothing
    proceeds"; it is not the composition's type and cannot become one here.
    """

    def __init__(self, code: str, reason: str) -> None:
        super().__init__(reason)
        self.code = code


class PermissionsHostAcpAuthority:
    """The submission and permission verifiers the channel fence calls.

    `admission` is this lane's public port (`PermissionsAcpAdmission` or the
    composition's adapter of it); `permit_binder` is the composition's own
    `(connection, submission) -> permit record` callable, absent until the
    public contract publishes a mintable permit record.
    """

    def __init__(self, *, admission: Any,
                 permit_binder: Callable[[Any, Mapping[str, Any]], Any] | None = None) -> None:
        if (admission is None
                or not callable(getattr(admission, "authorize_submission", None))
                or not callable(getattr(admission, "authorize_permission", None))):
            raise ValueError(
                "the authority needs an admission port that answers both ACP fences")
        self._admission = admission
        self._permit_binder = permit_binder

    # -- the submission fence ------------------------------------------------------

    def authorize_submission(self, connection: object,
                             submission: Mapping[str, object]) -> Any:
        """Return the bound permit the policy granted, or refuse outright.

        Never a permit the ruling did not grant, and never an admission that
        carries no permit: the caller's fence only stores a bound record.
        """
        binding = self._binding(connection)
        request = self._submission(submission)
        if not request.submission_id:
            raise self._refused(_UNVERIFIED, "the submission names no operation")
        try:
            result = self._admission.authorize_submission(binding, request)
        except PluginAdmissionRefused:
            raise
        except Exception as exc:  # noqa: BLE001 - an unresolved ruling admits nothing
            raise self._refused(_UNRESOLVED,
                                "the admission ruling could not be resolved") from exc
        if not self._accepted(result, request.submission_id):
            code, reason = self._outcome(result)
            raise self._refused(code, reason)
        if self._permit_binder is None:
            raise self._refused(
                PERMIT_SEAM_UNPUBLISHED,
                "no public permit record exists for a plugin to bind: the"
                " composition must supply the bound admission itself")
        try:
            permit = self._permit_binder(connection, submission)
        except PluginAdmissionRefused:
            raise
        except Exception as exc:  # noqa: BLE001 - a failed binder is not a permit
            raise self._refused(_UNRESOLVED,
                                "the supplied permit could not be bound") from exc
        if (getattr(permit, "submission_id", None) != request.submission_id
                or getattr(permit, "connection_id", None) != binding.connection_id):
            # A permit for any other operation is not this one's permit.
            raise self._refused(_UNVERIFIED,
                                "the supplied permit does not bind this submission")
        return permit

    # -- the tool-execution fence ----------------------------------------------------

    def authorize_permission(self, connection: object, request: Mapping[str, object],
                             decision: Mapping[str, object]) -> bool:
        """`True` only for an `accepted` answer naming this exact interaction.

        Anything else - a refusal, an `unknown`, an unreadable identity, a port
        that raised - answers `False`, which the fence reads as "the verifier
        refused" and relay nothing. `request` is not used for identity: the
        recorded approval is (see the module docstring).
        """
        del request
        try:
            binding = self._binding(connection)
            ask = self._decision(decision)
            if not ask.interaction_id:
                return False
            result = self._admission.authorize_permission(binding, ask)
        except Exception:  # noqa: BLE001 - a verifier that cannot answer never allows
            return False
        return self._accepted(result, ask.interaction_id)

    # -- translation: wire mapping -> the public DTOs ---------------------------------

    @staticmethod
    def _binding(connection: object) -> AcpChannelBinding:
        """The channel identity the fence hands the authority, as a binding.

        A value that is not a non-empty trimmed string is empty here, so the
        port's own unattributed-identity refusal fires instead of a guessed one;
        optional native evidence stays `None` when the channel never observed it.
        """
        def identity(name: str) -> str:
            value = getattr(connection, name, None)
            return value if isinstance(value, str) and value.strip() else ""
        native = getattr(connection, "native_session_id", None)
        generation = getattr(connection, "runtime_generation", None)
        try:
            return AcpChannelBinding(
                connection_id=identity("connection_id"),
                execution_id=identity("execution_id"),
                ledger_session_id=identity("session_id"),
                harness_id=identity("harness_id"),
                workspace_id=identity("workspace_id"),
                native_session_id=native if isinstance(native, str) and native.strip() else None,
                runtime_generation=generation
                if type(generation) is int and generation >= 0 else None)
        except (TypeError, ValueError) as exc:
            raise PermissionsHostAcpAuthority._refused(
                _UNVERIFIED, "the live channel identity is not attributable") from exc

    @staticmethod
    def _submission(submission: Mapping[str, object]) -> AcpSubmissionRequest:
        if not isinstance(submission, Mapping):
            raise PermissionsHostAcpAuthority._refused(
                _UNVERIFIED, "the ACP submission is not an object")
        raw_attachments = submission.get("attachments")
        if not isinstance(raw_attachments, list):
            raise PermissionsHostAcpAuthority._refused(
                _UNVERIFIED, "the ACP submission carries no attachment list")
        references: list[AcpAttachmentReference] = []
        for item in raw_attachments:
            if not isinstance(item, Mapping):
                raise PermissionsHostAcpAuthority._refused(
                    _UNVERIFIED, "an ACP attachment is not an object")
            references.append(AcpAttachmentReference(
                name=item.get("name"), uri=item.get("uri"), sha256=item.get("sha256"),
                mime_type=item.get("mimeType")))
        try:
            return AcpSubmissionRequest(
                submission_id=submission.get("submissionId"),
                native_session_id=submission.get("nativeSessionId"),
                text=submission.get("text"),
                attachments=tuple(references),
                configuration_digest=submission.get("configurationDigest"),
                command_id=submission.get("commandId"))
        except (TypeError, ValueError) as exc:
            raise PermissionsHostAcpAuthority._refused(
                _UNVERIFIED, "the ACP submission is not a well-formed snapshot") from exc

    @staticmethod
    def _decision(decision: Mapping[str, object]) -> AcpPermissionDecision:
        if not isinstance(decision, Mapping):
            raise PermissionsHostAcpAuthority._refused(
                _UNVERIFIED, "the ACP permission answer is not an object")
        try:
            return AcpPermissionDecision(
                native_session_id=decision.get("nativeSessionId"),
                interaction_id=decision.get("interactionId"),
                run_id=decision.get("runId"),
                option_id=decision.get("optionId"))
        except (TypeError, ValueError) as exc:
            raise PermissionsHostAcpAuthority._refused(
                _UNVERIFIED, "the ACP permission answer has no readable identity") from exc

    # -- outcome reading ---------------------------------------------------------------

    @staticmethod
    def _accepted(result: Any, identity: str) -> bool:
        return (type(result) is AcpAdmissionResult and result.kind == "accepted"
                and result.submission_id == identity)

    @staticmethod
    def _outcome(result: Any) -> tuple[str, str]:
        """The port's own answer, or the code for an answer this seam cannot read."""
        if type(result) is not AcpAdmissionResult:
            return _MISSING_PORT, "the admission port answered no typed result"
        if result.kind == "refused":
            return (result.code or _UNVERIFIED,
                    result.reason or "the permission policy refused this operation")
        if result.kind == "unknown":
            return _UNRESOLVED, result.reason or "the admission outcome needs reconciliation"
        return _UNVERIFIED, result.reason or "the admission answer binds no identity"

    @staticmethod
    def _refused(code: str, reason: str) -> PluginAdmissionRefused:
        return PluginAdmissionRefused(code, reason[:240].replace("\n", " ").replace("\r", " "))

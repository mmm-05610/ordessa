"""Server-side admission and one-use relay fence for managed ACP channels.

The authority is injected from a selected product. There is deliberately no
default permit verifier. A missing authority refuses admission and the raw
relay refuses prompts/answers that would consume it.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from threading import RLock
from typing import Mapping, Protocol

from server_plugin_api import (
    AcpAdmissionResult, AcpChannelBinding, AcpPermissionDecision,
    AcpSubmissionRequest,
)


class AcpAdmissionRefused(ValueError):
    def __init__(self, code: str, reason: str):
        super().__init__(reason)
        self.code = code


@dataclass(frozen=True)
class BoundAdmission:
    principal: str
    connection_id: str
    native_session_id: str
    runtime_generation: int
    submission_id: str
    input_digest: str
    configuration_digest: str
    expires_at: float


class AcpPermitAuthority(Protocol):
    def authorize_submission(self, connection: object, submission: Mapping[str, object]) -> BoundAdmission: ...
    def authorize_permission(self, connection: object, request: Mapping[str, object],
                             decision: Mapping[str, object]) -> bool: ...


def _record(value: object) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise AcpAdmissionRefused("INVALID_REQUEST", "ACP frame must be an object")
    return value


def _name(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise AcpAdmissionRefused("INVALID_REQUEST", "ACP identity is missing")
    return value


def _rpc_id(value: object) -> str:
    if isinstance(value, str) and value or type(value) is int:
        return str(value)
    raise AcpAdmissionRefused("INVALID_REQUEST", "ACP request id is missing")


def _canonical(value: object) -> str:
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise AcpAdmissionRefused("INVALID_REQUEST", "ACP content is not serializable") from exc


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def prompt_input(submission: Mapping[str, object]) -> tuple[str, list[dict[str, object]]]:
    text = submission.get("text")
    items = submission.get("attachments")
    if not isinstance(text, str) or not isinstance(items, list):
        raise AcpAdmissionRefused("INVALID_REQUEST", "ACP submission lacks text or attachments")
    blocks: list[dict[str, object]] = [{"type": "text", "text": text}]
    for item in items:
        item = _record(item)
        name, uri = _name(item.get("name")), _name(item.get("uri"))
        sha = item.get("sha256")
        if not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise AcpAdmissionRefused("INVALID_REQUEST", "ACP attachment digest is invalid")
        block: dict[str, object] = {"type": "resource_link", "name": name, "uri": uri}
        if item.get("mimeType") is not None:
            block["mimeType"] = _name(item["mimeType"])
        blocks.append(block)
    return _name(submission.get("nativeSessionId")), blocks


class AcpAdmissionGate:
    """One runtime's volatile fence. Restart loses permits and therefore denies replay."""

    def __init__(self, authority: AcpPermitAuthority | None = None, *, clock=None):
        import time
        self.authority = authority
        self.clock = clock or time.time
        self._lock = RLock()
        self._submissions: dict[tuple[str, str], tuple[BoundAdmission, str, str]] = {}
        self._prompt_requests: dict[tuple[str, str], tuple[str, str]] = {}
        self._used_prompt_ids: set[tuple[str, str]] = set()
        self._permission_requests: dict[tuple[str, str], Mapping[str, object]] = {}
        self._permissions: dict[tuple[str, str], str] = {}
        self._answered_permissions: set[tuple[str, str]] = set()
        self._reverse_requests: set[tuple[str, str]] = set()
        self._answered_reverse: set[tuple[str, str]] = set()
        self._seen_reverse_ids: set[tuple[str, str]] = set()
        self._blocked_reverse_ids: set[tuple[str, str]] = set()

    def authorize_submission(self, connection: object, submission: Mapping[str, object],
                             *, expected_generation: int | None = None) -> dict[str, str]:
        if self.authority is None:
            raise AcpAdmissionRefused("CAPABILITY_UNSUPPORTED", "ACP submission authority is absent")
        connection_id = _name(getattr(connection, "connection_id", None))
        submission_id = _name(submission.get("submissionId"))
        native_id, blocks = prompt_input(submission)
        config_digest = _name(submission.get("configurationDigest"))
        expected = _digest({"sessionId": native_id, "prompt": blocks})
        key = (connection_id, submission_id)
        with self._lock:
            previous = self._submissions.get(key)
            if previous is not None:
                if expected_generation is not None and previous[0].runtime_generation != expected_generation:
                    raise AcpAdmissionRefused("AUTHORIZATION_REFUSED", "submission generation changed")
                if previous[0].input_digest != expected or previous[0].configuration_digest != config_digest:
                    raise AcpAdmissionRefused("TARGET_CONFLICT", "submission identity changed")
                return {"kind": "unknown", "operationId": submission_id, "reason": "prior admission needs reconciliation"}
            if any(record.connection_id == connection_id and state != "confirmed"
                   for record, state, _ in self._submissions.values()):
                raise AcpAdmissionRefused("BUSY", "channel has an unresolved submission")
            bound = self.authority.authorize_submission(connection, submission)
            if (not isinstance(bound, BoundAdmission) or bound.connection_id != connection_id
                    or bound.native_session_id != native_id or bound.submission_id != submission_id
                    or bound.input_digest != expected or bound.configuration_digest != config_digest
                    or type(bound.runtime_generation) is not int or bound.runtime_generation < 0
                    or (expected_generation is not None and bound.runtime_generation != expected_generation)
                    or not bound.principal or bound.expires_at <= self.clock()):
                raise AcpAdmissionRefused("AUTHORIZATION_REFUSED", "submission permit binding is invalid")
            self._submissions[key] = (bound, "ready", _canonical(blocks))
            return {"kind": "accepted", "submissionId": submission_id}

    def observe_agent_frame(self, connection_id: str, text: str) -> None:
        try:
            frame = _record(json.loads(text))
            request_id = _rpc_id(frame.get("id"))
            if frame.get("method") is None:
                result = frame.get("result")
                with self._lock:
                    key = self._prompt_requests.pop((connection_id, request_id), None)
                    if key is not None and isinstance(result, dict) and result.get("stopReason") in {
                        "end_turn", "cancelled", "max_turn_requests", "refusal", "max_tokens"}:
                        bound, _, expected = self._submissions[key]
                        self._submissions[key] = (bound, "confirmed", expected)
                return
            method = frame.get("method")
            params = None
            if method == "session/request_permission":
                params = _record(frame.get("params"))
                _name(params.get("sessionId"))
        except (ValueError, TypeError):
            return
        with self._lock:
            key = (connection_id, request_id)
            if key in self._seen_reverse_ids:
                self._blocked_reverse_ids.add(key)
                self._reverse_requests.discard(key)
                self._permission_requests.pop(key, None)
                self._permissions.pop(key, None)
                return
            self._seen_reverse_ids.add(key)
            if method == "session/request_permission":
                assert params is not None
                self._permission_requests[key] = params
            else:
                self._reverse_requests.add(key)

    def authorize_permission(self, connection: object, decision: Mapping[str, object],
                             *, expected_generation: int | None = None) -> dict[str, str]:
        if self.authority is None:
            raise AcpAdmissionRefused("CAPABILITY_UNSUPPORTED", "ACP permission authority is absent")
        connection_id = _name(getattr(connection, "connection_id", None))
        interaction_id = _name(decision.get("interactionId"))
        with self._lock:
            if expected_generation is not None and not any(
                    bound.connection_id == connection_id
                    and bound.native_session_id == decision.get("nativeSessionId")
                    and bound.runtime_generation == expected_generation
                    and bound.expires_at > self.clock()
                    for bound, _, _ in self._submissions.values()):
                raise AcpAdmissionRefused("AUTHORIZATION_REFUSED", "permission generation is not bound")
            matches = [(key, request) for key, request in self._permission_requests.items()
                       if key[0] == connection_id and request.get("sessionId") == decision.get("nativeSessionId")]
            if len(matches) != 1:
                raise AcpAdmissionRefused("AUTHORIZATION_REFUSED", "permission request is absent or moved")
            key, request = matches[0]
            option = _name(decision.get("optionId"))
            options = request.get("options")
            if not isinstance(options, list) or not any(isinstance(item, dict) and item.get("optionId") == option for item in options):
                raise AcpAdmissionRefused("AUTHORIZATION_REFUSED", "permission option is not offered")
            if key in self._permissions:
                return {"kind": "unknown", "operationId": interaction_id, "reason": "permission answer needs reconciliation"}
            if self.authority.authorize_permission(connection, request, decision) is not True:
                raise AcpAdmissionRefused("AUTHORIZATION_REFUSED", "permission verifier refused")
            self._permissions[key] = option
            return {"kind": "accepted", "submissionId": interaction_id}

    def admit_client_frame(self, connection: object, text: str) -> None:
        try:
            frame = _record(json.loads(text))
        except (ValueError, TypeError) as exc:
            raise AcpAdmissionRefused("INVALID_REQUEST", "ACP client frame is malformed") from exc
        connection_id = _name(getattr(connection, "connection_id", None))
        method = frame.get("method")
        if method == "session/prompt":
            request_id = _rpc_id(frame.get("id"))
            params = _record(frame.get("params"))
            native_id = _name(params.get("sessionId"))
            actual = _digest({"sessionId": native_id, "prompt": params.get("prompt")})
            with self._lock:
                rpc_key = (connection_id, request_id)
                if rpc_key in self._used_prompt_ids:
                    raise AcpAdmissionRefused("AUTHORIZATION_REFUSED", "ACP prompt request id was already used")
                matching = [(key, bound, expected) for key, (bound, state, expected) in self._submissions.items()
                            if key[0] == connection_id and state == "ready" and bound.native_session_id == native_id]
                if len(matching) != 1 or matching[0][1].expires_at <= self.clock() or matching[0][1].input_digest != actual:
                    raise AcpAdmissionRefused("AUTHORIZATION_REFUSED", "ACP prompt lacks matching one-use admission")
                key, bound, expected = matching[0]
                self._submissions[key] = (bound, "unknown", expected)  # before external send
                self._prompt_requests[rpc_key] = key
                self._used_prompt_ids.add(rpc_key)
        elif method is None and ("result" in frame or "error" in frame):
            request_id = _rpc_id(frame.get("id"))
            key = (connection_id, request_id)
            with self._lock:
                if key in self._blocked_reverse_ids:
                    raise AcpAdmissionRefused("AUTHORIZATION_REFUSED", "ACP reverse request id was reused")
                if key in self._answered_permissions or key in self._answered_reverse:
                    raise AcpAdmissionRefused("AUTHORIZATION_REFUSED", "ACP reverse answer was already consumed")
                if key in self._reverse_requests:
                    self._reverse_requests.remove(key)
                    self._answered_reverse.add(key)
                    return
                if key not in self._permission_requests:
                    raise AcpAdmissionRefused("AUTHORIZATION_REFUSED", "ACP reverse answer has no observed request")
                option = self._permissions.get(key)
                result = frame.get("result")
                outcome = _record(_record(result).get("outcome")) if result is not None else None
                if option is None or outcome is None or outcome.get("outcome") != "selected" or outcome.get("optionId") != option:
                    raise AcpAdmissionRefused("AUTHORIZATION_REFUSED", "ACP permission answer lacks matching admission")
                del self._permissions[key]  # one use before external send
                del self._permission_requests[key]
                self._answered_permissions.add(key)

    def forget_channel(self, connection_id: str) -> None:
        """Retire volatile facts only once the owned channel itself ends."""
        with self._lock:
            self._submissions = {key: value for key, value in self._submissions.items() if key[0] != connection_id}
            self._prompt_requests = {key: value for key, value in self._prompt_requests.items() if key[0] != connection_id}
            self._used_prompt_ids = {key for key in self._used_prompt_ids if key[0] != connection_id}
            self._permission_requests = {key: value for key, value in self._permission_requests.items() if key[0] != connection_id}
            self._permissions = {key: value for key, value in self._permissions.items() if key[0] != connection_id}
            self._answered_permissions = {key for key in self._answered_permissions if key[0] != connection_id}
            self._reverse_requests = {key for key in self._reverse_requests if key[0] != connection_id}
            self._answered_reverse = {key for key in self._answered_reverse if key[0] != connection_id}
            self._seen_reverse_ids = {key for key in self._seen_reverse_ids if key[0] != connection_id}
            self._blocked_reverse_ids = {key for key in self._blocked_reverse_ids if key[0] != connection_id}

    def observe_wire_result(self, method: str, params: Mapping[str, object], result: object,
                            stream_routes: object) -> None:
        """Retire a released channel even when no WebSocket was subscribed.

        The wire result alone is not proof: the host route must also have lost
        its owner. A failed or uncertain release leaves every fence in place.
        """
        if method != "acp.channel.release" or not isinstance(result, dict) or result.get("released") is not True:
            return
        connection_id = params.get("connectionId")
        if (not isinstance(connection_id, str) or not connection_id
                or result.get("connectionId") != connection_id):
            return
        if stream_routes.resolve("acp-channel", connection_id) is None:
            self.forget_channel(connection_id)

    def forget_all(self) -> None:
        """Retire this composition's volatile facts after its plugin round ends."""
        with self._lock:
            self._submissions.clear()
            self._prompt_requests.clear()
            self._used_prompt_ids.clear()
            self._permission_requests.clear()
            self._permissions.clear()
            self._answered_permissions.clear()
            self._reverse_requests.clear()
            self._answered_reverse.clear()
            self._seen_reverse_ids.clear()
            self._blocked_reverse_ids.clear()


class AcpAdmissionPortAdapter:
    """Public DTO boundary over the host's live channel and internal relay gate."""

    # An owner can reject the old Mapping/dict gate without importing this class.
    public_acp_admission_port_version = 1

    def __init__(self, gate: AcpAdmissionGate, stream_routes: object):
        self._gate = gate
        self._stream_routes = stream_routes

    @property
    def ready(self) -> bool:
        """Whether product authority and native/generation evidence are wired.

        S-06/S-03 (2026-09-29): authority from the permissions domain
        (``PermissionsAcpAdmission``) is injected by the product composition
        (``_wire_admission_authority``); the gate is honest about its
        presence — an absent authority refuses and reports, a present one
        permits the capability row to flip. Native evidence wiring is the
        next increment (recorded, not faked).
        """
        return self._gate.authority is not None

    def _connection(self, binding: AcpChannelBinding) -> object:
        if not isinstance(binding, AcpChannelBinding):
            raise AcpAdmissionRefused("INVALID_REQUEST", "ACP channel binding is invalid")
        connection = self._stream_routes.resolve("acp-channel", binding.connection_id)
        if connection is None or getattr(connection, "ended", False) or getattr(connection, "transport", None) is None:
            raise AcpAdmissionRefused("AUTHORIZATION_REFUSED", "ACP channel is not live")
        observed = (
            getattr(connection, "connection_id", None),
            getattr(connection, "execution_id", None),
            getattr(connection, "session_id", None),
            getattr(connection, "harness_id", None),
            getattr(connection, "workspace_id", None),
        )
        claimed = (
            binding.connection_id, binding.execution_id, binding.ledger_session_id,
            binding.harness_id, binding.workspace_id,
        )
        if observed != claimed:
            raise AcpAdmissionRefused("AUTHORIZATION_REFUSED", "ACP channel identity changed")
        if binding.native_session_id is None or binding.runtime_generation is None:
            raise AcpAdmissionRefused("AUTHORIZATION_REFUSED", "ACP native session or generation is unobserved")
        for field, expected in (("native_session_id", binding.native_session_id),
                                ("runtime_generation", binding.runtime_generation)):
            actual = getattr(connection, field, None)
            if actual is None or type(actual) is not type(expected) or actual != expected:
                raise AcpAdmissionRefused("AUTHORIZATION_REFUSED", "ACP channel evidence is absent or changed")
        return connection

    @staticmethod
    def _result(value: Mapping[str, str]) -> AcpAdmissionResult:
        kind = value.get("kind")
        if kind == "accepted":
            return AcpAdmissionResult(kind="accepted", submission_id=value["submissionId"])
        if kind == "unknown":
            return AcpAdmissionResult(kind="unknown", operation_id=value["operationId"], reason=value["reason"])
        raise AcpAdmissionRefused("AUTHORIZATION_REFUSED", "ACP authority returned an invalid outcome")

    def authorize_submission(self, binding: AcpChannelBinding,
                             submission: AcpSubmissionRequest) -> AcpAdmissionResult:
        try:
            if not isinstance(submission, AcpSubmissionRequest):
                raise AcpAdmissionRefused("INVALID_REQUEST", "ACP submission DTO is invalid")
            connection = self._connection(binding)
            if binding.native_session_id != submission.native_session_id:
                raise AcpAdmissionRefused("AUTHORIZATION_REFUSED", "ACP native session changed")
            attachments = []
            for item in submission.attachments:
                attachment = {"name": item.name, "uri": item.uri, "sha256": item.sha256}
                if item.mime_type is not None:
                    attachment["mimeType"] = item.mime_type
                attachments.append(attachment)
            request = {
                "submissionId": submission.submission_id,
                "nativeSessionId": submission.native_session_id,
                "text": submission.text,
                "attachments": attachments,
                "configurationDigest": submission.configuration_digest,
            }
            if submission.command_id is not None:
                request["commandId"] = submission.command_id
            return self._result(self._gate.authorize_submission(
                connection, request, expected_generation=binding.runtime_generation))
        except AcpAdmissionRefused as exc:
            return AcpAdmissionResult(kind="refused", code=exc.code, reason=str(exc))
        except Exception:
            return AcpAdmissionResult(kind="unknown", operation_id=getattr(submission, "submission_id", None) or "invalid-submission",
                                      reason="ACP admission outcome needs reconciliation")

    def authorize_permission(self, binding: AcpChannelBinding,
                             decision: AcpPermissionDecision) -> AcpAdmissionResult:
        try:
            if not isinstance(decision, AcpPermissionDecision):
                raise AcpAdmissionRefused("INVALID_REQUEST", "ACP permission DTO is invalid")
            connection = self._connection(binding)
            if binding.native_session_id != decision.native_session_id:
                raise AcpAdmissionRefused("AUTHORIZATION_REFUSED", "ACP native session changed")
            request = {
                "nativeSessionId": decision.native_session_id,
                "interactionId": decision.interaction_id,
                "runId": decision.run_id,
                "optionId": decision.option_id,
            }
            return self._result(self._gate.authorize_permission(
                connection, request, expected_generation=binding.runtime_generation))
        except AcpAdmissionRefused as exc:
            return AcpAdmissionResult(kind="refused", code=exc.code, reason=str(exc))
        except Exception:
            return AcpAdmissionResult(kind="unknown", operation_id=getattr(decision, "interaction_id", None) or "invalid-permission",
                                      reason="ACP permission outcome needs reconciliation")

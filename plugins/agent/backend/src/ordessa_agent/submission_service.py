"""Reliable Agent submission orchestration over the composition Environment.

The Agent journal owns its durable request-to-domain-result mapping; the
Environment owns effect admission and its namespaced request claim; a declared
Harness adapter owns native conditional submission and native queries. This
module is the narrow coordinator between those authorities. It never retries a
possibly-submitted request and never invents an accepted result from capture.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Literal, Mapping, Protocol

from ordessa_environment_api import RequestKey
from ordessa_environment_api.guarantee import GuaranteeLevel

from .capture import CaptureTransaction
from .owners import AgentOwnerRegistry
from .submission_journal import (
    JournalConflictError,
    ReliableCapabilities,
    ReliableSubmissionUnsupported,
    SubmissionJournal,
    SubmissionRecord,
)


SubmissionMode = Literal["existing", "createWithConfig"]


@dataclass(frozen=True)
class NativeSubmitDeclaration:
    """Declared native conditions; values must come from the selected adapter."""

    owner_ref: str
    existing_conditional: bool
    create_with_config_conditional: bool
    immutable_attachments: bool


@dataclass(frozen=True)
class NativeSubmitBinding:
    """A fresh trusted native binding resolved for a first submission only."""

    target: str
    owner_ref: str
    mode: SubmissionMode
    surface_id: str
    base_revision: str
    identity: Mapping[str, str]


@dataclass(frozen=True)
class NativeSubmitResult:
    """Native facts observed by query after a conditional request."""

    outcome: Literal["accepted", "known-rejected", "unknown"]
    config_apply: Mapping[str, Any] | None = None
    input_acceptance: Mapping[str, Any] | None = None
    run_result: Mapping[str, Any] | None = None


class NativeSubmitPort(Protocol):
    """Public Harness adapter seam, explicitly declared by its owner."""

    @property
    def declaration(self) -> NativeSubmitDeclaration: ...

    def resolve_binding(self, target: str) -> NativeSubmitBinding: ...

    def read_attachment(self, target: str, attachment_id: str) -> bytes: ...

    def submit_existing(self, request: RequestKey, capture: CaptureTransaction) -> Any: ...

    def create_with_config(self, request: RequestKey, capture: CaptureTransaction) -> Any: ...

    def query(self, request: RequestKey) -> NativeSubmitResult | None: ...

    def list_sessions(self, target: str) -> tuple[Mapping[str, Any], ...]: ...


@dataclass(frozen=True)
class SubmissionInput:
    """Caller-owned draft material plus stable submission identity.

    Binding, base revision, configuration facts and attachment bytes are
    resolved on the trusted side and are never accepted from this input.
    """

    submission_id: str
    principal_scope: str
    target: str
    mode: SubmissionMode
    draft: Mapping[str, Any]
    config_operation_ids: tuple[str, ...]
    schema: str


@dataclass(frozen=True)
class SubmissionResult:
    request: RequestKey
    outcome: Literal["accepted", "known-rejected", "unknown"]
    record: SubmissionRecord
    replayed: bool


@dataclass(frozen=True)
class SubmissionObservation:
    submission: SubmissionRecord
    backend_fact: Any
    native_fact: NativeSubmitResult | None


class AgentSubmissionService:
    """Coordinate capture, the durable submit fence, one Environment invoke,
    and separately recorded native result facts.

    ``owners`` is the canonical Agent-domain owner registry. ``native_submit_port``
    is supplied by product composition only when the Harness publicly declares
    the conditional operation that this target requires.
    """

    def __init__(
        self,
        *,
        environment: Any,
        journal: SubmissionJournal,
        owners: AgentOwnerRegistry,
        native_submit_port: NativeSubmitPort,
    ) -> None:
        if not callable(getattr(environment, "invoke", None)) or not callable(
            getattr(environment, "query", None)
        ):
            raise ReliableSubmissionUnsupported("Agent submission requires the composed Environment")
        if not callable(getattr(journal, "capture", None)):
            raise ReliableSubmissionUnsupported("Agent submission requires the durable journal")
        if not callable(getattr(owners, "owners_of", None)):
            raise TypeError("owners must expose the Agent domain's public owner lookup")
        self.environment = environment
        self.journal = journal
        self.owners = owners
        self.native_submit_port = native_submit_port

    @property
    def declaration(self) -> NativeSubmitDeclaration:
        declaration = getattr(self.native_submit_port, "declaration", None)
        if not isinstance(declaration, NativeSubmitDeclaration):
            raise ReliableSubmissionUnsupported("native submit adapter has no valid capability declaration")
        return declaration

    def _request_key(self, target: str, submission_id: str, principal_scope: str,
                     binding_identity: Mapping[str, str]) -> RequestKey:
        binding_digest = hashlib.sha256(_canonical(binding_identity).encode("utf-8")).hexdigest()
        return RequestKey(
            environment_namespace=self.environment.environment_id,
            principal_scope=principal_scope,
            request_id=submission_id,
            comparison={"target": target, "binding": binding_digest},
        )

    @staticmethod
    def _validate_input(item: SubmissionInput) -> None:
        if not isinstance(item, SubmissionInput):
            raise TypeError("submit requires a SubmissionInput")
        for name, value in (("submission_id", item.submission_id), ("target", item.target),
                            ("schema", item.schema)):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be non-empty")
        if not isinstance(item.principal_scope, str) or not item.principal_scope.strip():
            raise ValueError("principal_scope must be non-empty")
        if item.mode not in ("existing", "createWithConfig"):
            raise ReliableSubmissionUnsupported(f"unsupported conditional submission mode {item.mode!r}")
        if not isinstance(item.draft, Mapping):
            raise ValueError("draft must be a mapping")

    def submit(self, item: SubmissionInput) -> SubmissionResult:
        """Run a new captured submission or query an existing stable request.

        Any prior journal mapping takes the query-only branch. The branch first
        checks the caller-supplied text/draft/config intent against the frozen
        capture, then reads the original backend key and native owner. It never
        resolves a replacement binding or invokes a second submit.
        """
        self._validate_input(item)
        prior = self._find_prior(item)
        if prior is not None:
            self._assert_retry_matches(prior, item)
            observation = self.query(item.target, item.submission_id, item.principal_scope)
            if observation is None:
                return SubmissionResult(prior.request, "unknown", prior, replayed=True)
            result = self._result_from_observation(prior, observation.native_fact)
            if (result in ("accepted", "known-rejected")
                    and prior.stage == "possibly-submitted"
                    and observation.native_fact is not None):
                self._record_native_result(prior.request, observation.native_fact)
                refreshed = self.journal.read(prior.request)
                if refreshed is not None:
                    prior = refreshed
            return SubmissionResult(prior.request, result, prior, replayed=True)

        declaration = self.declaration
        if not callable(getattr(self.native_submit_port, "resolve_binding", None)):
            raise ReliableSubmissionUnsupported("native submit adapter cannot resolve an owner binding")
        try:
            binding = self.native_submit_port.resolve_binding(item.target)
        except Exception as exc:
            raise ReliableSubmissionUnsupported(
                f"native owner binding is unavailable: {exc}"
            ) from exc
        self._validate_binding(item, declaration, binding)
        method_name = "submit_existing" if item.mode == "existing" else "create_with_config"
        if not callable(getattr(self.native_submit_port, method_name, None)):
            raise ReliableSubmissionUnsupported(
                f"native adapter does not implement declared conditional {item.mode} submission"
            )
        if not callable(getattr(self.native_submit_port, "query", None)):
            raise ReliableSubmissionUnsupported("native submit adapter has no read-only query surface")
        try:
            environment_binding = self.environment.bind(binding.surface_id)
        except Exception as exc:
            raise ReliableSubmissionUnsupported(
                f"native binding is not an active Environment capability: {exc}"
            ) from exc
        if environment_binding.environment != self.environment.environment_id:
            raise ReliableSubmissionUnsupported("Environment binding identity does not match the composed Environment")
        preflight = getattr(self.environment, "check_invocation", None)
        if not callable(preflight):
            raise ReliableSubmissionUnsupported(
                "Environment has no reliable effect preflight; submission remains unsupported"
            )
        preflight_result = preflight(
            binding.surface_id,
            guarantee=GuaranteeLevel.RELIABLE,
            principal=item.principal_scope,
            effect=True,
        )
        backend_durable = getattr(preflight_result, "backend_durable", False) is True
        if not backend_durable:
            raise ReliableSubmissionUnsupported(
                "Environment did not declare durable reliable dispatch support"
            )

        owners = self.owners.owners_of(item.target)
        if owners is None or "config" not in owners:
            raise ReliableSubmissionUnsupported("Agent target has no registered configuration owner")
        config_owner = owners["config"]
        capture_configuration = getattr(config_owner, "capture_configuration", None)
        if not callable(capture_configuration):
            raise ReliableSubmissionUnsupported(
                "configuration owner cannot atomically capture its snapshot and operations"
            )
        config_snapshot, config_operations = capture_configuration()
        if (not all(isinstance(operation_id, str) and operation_id
                    for operation_id in item.config_operation_ids)
                or len(set(item.config_operation_ids)) != len(item.config_operation_ids)):
            raise ReliableSubmissionUnsupported("configuration operation ids are malformed or duplicated")
        pending_operation_ids = {
            operation.operation_id for operation in config_operations
            if operation.state == "pending"
        }
        if pending_operation_ids != set(item.config_operation_ids):
            raise ReliableSubmissionUnsupported(
                "configuration operation ids must exactly capture the trusted owner's pending operations"
            )
        config_facts = {
            "ownerRef": config_snapshot.owner_ref,
            "revision": str(config_snapshot.revision),
            "observedEvidence": config_snapshot.observed_evidence,
            "fields": dict(config_snapshot.fields),
            "resolved": _plain(config_snapshot.resolved),
        }

        draft = self._normalize_draft(item.draft)
        if draft.get("draftId") is None or draft.get("draftRevision") is None or not isinstance(
            draft.get("text"), str
        ):
            raise ReliableSubmissionUnsupported("draftId, draftRevision and text are required for capture")
        attachment_ids = draft.get("attachmentIds", ())
        if not isinstance(attachment_ids, (tuple, list)) or not all(
            isinstance(value, str) and value for value in attachment_ids
        ):
            raise ReliableSubmissionUnsupported("attachment ids are malformed")
        if len(set(attachment_ids)) != len(attachment_ids):
            raise ReliableSubmissionUnsupported("attachment ids must be unique in one capture")
        attachment_bytes: dict[str, bytes] = {}
        if attachment_ids and not callable(getattr(self.native_submit_port, "read_attachment", None)):
            raise ReliableSubmissionUnsupported("native adapter cannot resolve immutable attachment bytes")
        for attachment_id in attachment_ids:
            try:
                content = self.native_submit_port.read_attachment(item.target, attachment_id)
            except Exception as exc:
                raise ReliableSubmissionUnsupported(
                    f"immutable attachment {attachment_id!r} is unavailable: {exc}"
                ) from exc
            if not isinstance(content, (bytes, bytearray, memoryview)):
                raise ReliableSubmissionUnsupported(
                    f"attachment {attachment_id!r} has no immutable content bytes"
                )
            attachment_bytes[attachment_id] = bytes(content)

        binding_identity = {
            **{str(key): str(value) for key, value in binding.identity.items()},
            "ownerRef": binding.owner_ref,
            "surfaceId": binding.surface_id,
            "environment": self.environment.environment_id,
            "environmentContextRevision": environment_binding.environment_context_revision,
            "providerActivation": environment_binding.provider_activation.plugin_id + ":"
            + str(environment_binding.provider_activation.generation),
        }
        request = self._request_key(
            item.target, item.submission_id, item.principal_scope, binding_identity
        )
        capture = CaptureTransaction.capture(
            submission_id=item.submission_id,
            draft=draft,
            config_op_ids=item.config_operation_ids,
            base=binding.base_revision,
            target={"target": item.target, "mode": item.mode, "config": config_facts},
            binding=binding_identity,
            schema=item.schema,
            guarantee=GuaranteeLevel.RELIABLE,
            configuration_free=not pending_operation_ids,
        )
        snapshot = self._capture_snapshot(capture)
        capabilities = ReliableCapabilities(
            backend_durable=backend_durable,
            conditional_submit=(
                declaration.existing_conditional if item.mode == "existing"
                else declaration.create_with_config_conditional
            ),
            immutable_attachments=declaration.immutable_attachments and all(
                isinstance(value, bytes) for value in attachment_bytes.values()
            ),
        )
        record = self.journal.capture(
            request, snapshot, attachments=attachment_bytes, capabilities=capabilities,
        )
        # A concurrent first caller may have won the journal insert. The
        # journal has no caller-ownership token, so both callers may reach the
        # same stable Environment key; its atomic durable dispatch claim is the
        # sole authority that may enter the native handler.
        if record.stage != "mapped":
            observation = self.query(item.target, item.submission_id, item.principal_scope)
            outcome = self._result_from_observation(record, observation.native_fact if observation else None)
            return SubmissionResult(record.request, outcome, record, replayed=True)
        record = self.journal.mark_possibly_submitted(request, record.digest)

        def dispatch() -> None:
            method = (self.native_submit_port.submit_existing if item.mode == "existing"
                      else self.native_submit_port.create_with_config)
            method(request, capture)

        try:
            self.environment.invoke(
                binding.surface_id,
                request,
                guarantee=GuaranteeLevel.RELIABLE,
                input_digest=record.digest,
                principal=item.principal_scope,
                handler=dispatch,
            )
        except Exception:
            # Even a transport loss after an effect is an unknown. Never repeat
            # the callback; query the exact persisted request/native key below.
            observation = self.query(item.target, item.submission_id, item.principal_scope)
            native_fact = observation.native_fact if observation else None
            outcome = self._result_from_observation(record, native_fact)
            if native_fact is not None and native_fact.outcome in ("accepted", "known-rejected"):
                self._record_native_result(request, native_fact)
                record = self.journal.read(request) or record
            return SubmissionResult(record.request, outcome, record, replayed=False)

        observation = self.query(item.target, item.submission_id, item.principal_scope)
        native_fact = observation.native_fact if observation else None
        if native_fact is None or native_fact.outcome == "unknown":
            return SubmissionResult(record.request, "unknown", record, replayed=False)
        self._record_native_result(request, native_fact)
        completed = self.journal.read(request)
        if completed is None:
            raise ReliableSubmissionUnsupported("submission result disappeared after durable recording")
        return SubmissionResult(request, native_fact.outcome, completed, replayed=False)

    def query(self, target: str, submission_id: str,
              principal_scope: str) -> SubmissionObservation | None:
        """Read-only reconciliation by the original RequestKey; never invoke."""
        lookup = RequestKey(
            environment_namespace=self.environment.environment_id,
            principal_scope=principal_scope,
            request_id=submission_id,
        )
        record = self.journal.read(lookup)
        if record is None:
            return None
        try:
            frozen = json.loads(record.encoded_input)["capture"]["target"]["target"]
        except (KeyError, TypeError, json.JSONDecodeError):
            return None
        if frozen != target:
            return None
        observation = self.journal.reconcile(record.request, self.environment.query)
        if observation is None:
            return None
        # A native query is also read-only and is bound to the durable request
        # identity. No current binding resolution or new request key occurs.
        try:
            native = self.native_submit_port.query(record.request)
        except Exception:
            native = None
        if native is not None and not isinstance(native, NativeSubmitResult):
            native = None
        return SubmissionObservation(observation.submission, observation.backend_fact, native)

    def _find_prior(self, item: SubmissionInput) -> SubmissionRecord | None:
        request = RequestKey(
            environment_namespace=self.environment.environment_id,
            principal_scope=item.principal_scope,
            request_id=item.submission_id,
        )
        return self.journal.read(request)

    @staticmethod
    def _validate_binding(item: SubmissionInput, declaration: NativeSubmitDeclaration,
                          binding: NativeSubmitBinding) -> None:
        if not isinstance(declaration.owner_ref, str) or not declaration.owner_ref:
            raise ReliableSubmissionUnsupported("native adapter declaration has no owner binding")
        if not isinstance(binding, NativeSubmitBinding):
            raise ReliableSubmissionUnsupported("native adapter returned an invalid owner binding")
        if binding.owner_ref != declaration.owner_ref or binding.target != item.target:
            raise ReliableSubmissionUnsupported("native owner binding does not match the requested target")
        if binding.mode != item.mode:
            raise ReliableSubmissionUnsupported("native owner binding mode differs from the requested operation")
        if not binding.surface_id or not binding.base_revision or not binding.identity:
            raise ReliableSubmissionUnsupported("native owner binding is incomplete")
        if (not isinstance(binding.identity, Mapping)
                or not all(isinstance(key, str) and isinstance(value, str)
                           for key, value in binding.identity.items())):
            raise ReliableSubmissionUnsupported("native owner binding identity is malformed")
        supported = (declaration.existing_conditional if item.mode == "existing"
                     else declaration.create_with_config_conditional)
        if supported is not True:
            raise ReliableSubmissionUnsupported(
                f"native adapter does not declare conditional {item.mode} submission"
            )

    @staticmethod
    def _capture_snapshot(capture: CaptureTransaction) -> Mapping[str, Any]:
        return {
            "submissionId": capture.submission_id,
            "draft": _plain(capture.draft),
            "configOperationIds": list(capture.config_op_ids),
            "baseRevision": capture.base,
            "target": _plain(capture.target),
            "binding": _plain(capture.binding),
            "schema": capture.schema,
            "guarantee": capture.guarantee.value,
        }

    @staticmethod
    def _assert_retry_matches(record: SubmissionRecord, item: SubmissionInput) -> None:
        encoded = json.loads(record.encoded_input)
        capture = encoded["capture"]
        draft = capture.get("draft", {})
        requested_draft = AgentSubmissionService._normalize_draft(item.draft)
        if (draft != requested_draft
                or capture.get("configOperationIds") != list(item.config_operation_ids)
                or capture.get("target", {}).get("target") != item.target
                or capture.get("target", {}).get("mode") != item.mode
                or capture.get("schema") != item.schema):
            raise JournalConflictError(
                "logical RequestKey is already mapped to different immutable submission input"
            )

    @staticmethod
    def _normalize_draft(draft: Mapping[str, Any]) -> dict[str, Any]:
        allowed = {"draftId", "draftRevision", "text", "attachmentIds"}
        if not set(draft).issubset(allowed):
            raise ReliableSubmissionUnsupported(
                "draft input contains undeclared fields; result facts are native-query only"
            )
        return {key: _plain(value) for key, value in draft.items()}

    def _record_native_result(self, request: RequestKey, result: NativeSubmitResult) -> None:
        if result.outcome not in ("accepted", "known-rejected"):
            return
        if not all(isinstance(value, Mapping) for value in (
            result.config_apply, result.input_acceptance, result.run_result,
        )):
            return
        self._settle_captured_configuration(request, result.config_apply)
        if result.outcome == "accepted":
            self._record_native_session(request, result.input_acceptance)
        self.journal.record_config_apply(request, result.config_apply)
        self.journal.record_input_acceptance(request, result.input_acceptance)
        self.journal.record_run_result(request, result.run_result)
        self.journal.record_completed(request)

    def _record_native_session(self, request: RequestKey,
                               input_acceptance: Mapping[str, Any]) -> None:
        session = input_acceptance.get("session")
        if not isinstance(session, Mapping):
            return
        record = self.journal.read(request)
        if record is None:
            return
        try:
            capture = json.loads(record.encoded_input)["capture"]
            target = capture["target"]["target"]
            binding = capture["binding"]
        except (KeyError, TypeError, json.JSONDecodeError):
            return
        session_id = session.get("sessionId")
        native_session_id = session.get("nativeSessionId")
        generation = session.get("generation")
        owner_ref = session.get("ownerRef")
        bound_native_id = binding.get("nativeSessionId", binding.get("sessionId"))
        if (not all(isinstance(value, str) and value for value in
                    (session_id, native_session_id, owner_ref))
                or native_session_id != bound_native_id
                or str(generation) != str(binding.get("generation"))
                or owner_ref != binding.get("ownerRef")):
            return
        owners = self.owners.owners_of(target)
        if owners is None or "session" not in owners:
            raise ReliableSubmissionUnsupported(
                "captured session owner disappeared before trusted native evidence was recorded"
            )
        owners["session"].upsert(session_id, {
            "sessionId": session_id,
            "nativeSessionId": native_session_id,
            "generation": generation,
            "ownerRef": owner_ref,
            "source": "native-submission-query",
        })

    def list_sessions(self, target: str) -> tuple[tuple[Mapping[str, Any], ...], str]:
        """Project explicitly queried native history into the SessionOwner.

        If the adapter has no declared read-only history query, return only
        already persisted observations and label them as such.
        """
        owners = self.owners.owners_of(target)
        if owners is None or "session" not in owners:
            return (), "persisted"
        native_list = getattr(self.native_submit_port, "list_sessions", None)
        if not callable(native_list):
            return tuple(owners["session"].list()), "persisted"
        try:
            observations = native_list(target)
        except Exception:
            return tuple(owners["session"].list()), "persisted"
        if not isinstance(observations, (tuple, list)):
            return tuple(owners["session"].list()), "persisted"
        try:
            declared_owner_ref = self.declaration.owner_ref
        except ReliableSubmissionUnsupported:
            return tuple(owners["session"].list()), "persisted"
        accepted: list[Mapping[str, Any]] = []
        for observation in observations:
            if not isinstance(observation, Mapping):
                continue
            session_id = observation.get("sessionId")
            native_session_id = observation.get("nativeSessionId")
            generation = observation.get("generation")
            owner_ref = observation.get("ownerRef")
            if (not all(isinstance(value, str) and value for value in
                        (session_id, native_session_id, owner_ref))
                    or not isinstance(generation, (str, int))
                    or observation.get("target") != target
                    or owner_ref != declared_owner_ref):
                continue
            fact = {
                "target": target,
                "sessionId": session_id,
                "nativeSessionId": native_session_id,
                "generation": generation,
                "ownerRef": owner_ref,
                "source": "native-session-query",
            }
            owners["session"].upsert(session_id, fact)
            accepted.append(fact)
        return tuple(accepted), "native-query"

    def _settle_captured_configuration(self, request: RequestKey,
                                       config_apply: Mapping[str, Any]) -> None:
        """Settle only the captured pending operations proven applied by query."""
        if config_apply.get("outcome") != "applied":
            return
        record = self.journal.read(request)
        if record is None:
            return
        try:
            capture = json.loads(record.encoded_input)["capture"]
            target = capture["target"]["target"]
            expected = tuple(capture["configOperationIds"])
        except (KeyError, TypeError, json.JSONDecodeError):
            return
        reported = config_apply.get("operationIds")
        if (not isinstance(reported, (tuple, list))
                or tuple(reported) != expected
                or not expected):
            return
        owners = self.owners.owners_of(target)
        if owners is None or "config" not in owners:
            raise ReliableSubmissionUnsupported(
                "captured configuration owner disappeared before native application could be settled"
            )
        settle = getattr(owners["config"], "settle_operations", None)
        if not callable(settle):
            raise ReliableSubmissionUnsupported(
                "configuration owner cannot durably settle native-applied operations"
            )
        settle(expected, state="applied")

    @staticmethod
    def _result_from_observation(record: SubmissionRecord,
                                 native: NativeSubmitResult | None) -> Literal[
                                     "accepted", "known-rejected", "unknown"
                                 ]:
        if native is not None and native.outcome in ("accepted", "known-rejected"):
            return native.outcome
        if record.stage == "completed" and record.input_acceptance is not None:
            outcome = record.input_acceptance.get("outcome")
            if outcome in ("accepted", "known-rejected"):
                return outcome
        return "unknown"


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    return value

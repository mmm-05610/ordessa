"""One-shot managed Codex input over the existing Agent and Harness owners.

This module creates no capture, workspace, session, or result store. Missing
production owners are typed unsupported. The service is programmatic only;
wire, UI, interrupt effects, and cold recovery are separate work.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Mapping, Protocol

from ordessa_infrastructure.identifiers import RequestKey
from ordessa_execution_api.environment import (
    AdmissionRefusedError, GuaranteeUnavailableError, IdentityMismatchError,
    ParticipantInstanceRef,
)
from ordessa_execution_api.environment.operations import OperationStorePort, safe_json

from ordessa_units.channels.reservations import (
    CapturedInputEvidence, CapturedInputRef, ManagedInputReservations,
    NativeInputState,
)
from ordessa_units.admission.owner_ports import AgentOwnerPorts
from ordessa_units.public import (
    ManagedInputOutcome, WorkspaceExecutionEvidence, WorkspaceExecutionPort,
    plain_json_mapping,
)

TEXT_CAPTURE_VERSION = "managed-codex-text/1"
DISPATCH_BINDING_VERSION = "harness-managed-codex-turn/1"
TURN_RECEIPT_VERSION = "codex-turn-receipt/1"
TURN_TERMINAL_VERSION = "codex-turn-terminal/1"


def _digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _node(value: Mapping) -> ParticipantInstanceRef:
    if (not isinstance(value, Mapping)
            or set(value) != {"environmentNamespace", "instanceId", "generation"}):
        raise GuaranteeUnavailableError("complete original managed Node reference is unavailable")
    try:
        return ParticipantInstanceRef(value["environmentNamespace"], value["instanceId"],
                                      value["generation"])
    except (TypeError, ValueError):
        raise GuaranteeUnavailableError("complete original managed Node reference is unavailable") from None


@dataclass(frozen=True)
class ManagedTextCapture:
    """The capture owner's text-only canonical envelope and loss checks."""
    evidence: CapturedInputEvidence
    envelope: Mapping
    metadata: Mapping

    def canonical_bytes(self) -> bytes:
        if not isinstance(self.evidence, CapturedInputEvidence):
            raise GuaranteeUnavailableError("original captured-input metadata is unavailable")
        if (not isinstance(self.envelope, Mapping)
                or set(self.envelope) != {"schemaVersion", "text"}
                or self.envelope.get("schemaVersion") != TEXT_CAPTURE_VERSION
                or type(self.envelope.get("text")) is not str):
            raise GuaranteeUnavailableError("only the canonical managed Codex text envelope is supported")
        if (not isinstance(self.metadata, Mapping)
                or set(self.metadata) != {"attachmentDigests", "configOperationIds", "handles", "baseRevision"}
                or self.metadata["attachmentDigests"] not in ((), [])
                or self.metadata["configOperationIds"] not in ((), [])
                or self.metadata["handles"] not in ((), [])
                or self.metadata["baseRevision"] is not None):
            raise GuaranteeUnavailableError("capture contains unsupported attachments or configuration")
        try:
            body = safe_json(self.envelope).encode("utf-8")
        except (TypeError, ValueError, UnicodeError):
            raise GuaranteeUnavailableError("capture text is not canonical finite UTF-8 JSON") from None
        if len(body) > 262144:
            raise GuaranteeUnavailableError("managed Codex text capture exceeds the supported size")
        return body


class ManagedTextCaptureContentPort(Protocol):
    """Read the exact immutable text owned by the existing capture authority."""
    def read_content(self, captured_ref: CapturedInputRef, principal: str) -> ManagedTextCapture | None: ...


class ManagedCodexInputService:
    """Single-use bridge; all authorities are explicit existing-owner ports."""
    def __init__(self, environment, managed_inputs: ManagedInputReservations,
                 owner_ports: AgentOwnerPorts, provider: Any,
                 capture_content: ManagedTextCaptureContentPort | None = None,
                 workspace_execution: WorkspaceExecutionPort | None = None):
        if (not isinstance(managed_inputs, ManagedInputReservations)
                or not isinstance(owner_ports, AgentOwnerPorts)):
            raise GuaranteeUnavailableError("the original Agent owner bundle is required")
        owner_ports.validate_for(environment)
        capture_content = capture_content or owner_ports.managed_capture_content_port
        workspace_execution = workspace_execution or owner_ports.workspace_execution_port
        if (capture_content is not owner_ports.managed_capture_content_port
                or workspace_execution is not owner_ports.workspace_execution_port):
            raise IdentityMismatchError("managed input ports must be frozen in the original owner bundle")
        if (managed_inputs._environment is not environment
                or getattr(managed_inputs._nodes, "_environment", None) is not environment
                or getattr(environment, "_agent_services", None) is None
                or environment._agent_services.managed_inputs is not managed_inputs
                or getattr(environment, "_agent_owner_ports", None) is not owner_ports
                or managed_inputs._issuer is not owner_ports.issuer
                or owner_ports.provider_view.records is not getattr(provider, "records", None)
                or owner_ports.provider_view.verifier is not getattr(provider, "verifier", None)):
            raise IdentityMismatchError("managed input must use the same Environment, issuer, UnitRecords and verifier")
        if (not callable(getattr(capture_content, "read_content", None))
                or not callable(getattr(workspace_execution, "authorize_execute", None))
                or not callable(getattr(workspace_execution, "revalidate_execute", None))):
            raise GuaranteeUnavailableError("original capture-content and Workspace execute ports are required")
        self._require_managed_turn(owner_ports.provider_view.records)
        self.environment, self.reservations, self.owner_ports = environment, managed_inputs, owner_ports
        self.provider = provider
        self.capture_content, self.workspace_execution = capture_content, workspace_execution
        self.records = owner_ports.provider_view.records
        self.verifier = owner_ports.provider_view.verifier

    @staticmethod
    def _require_managed_turn(records):
        if getattr(records, "managed_turn_available", False) is not True:
            raise GuaranteeUnavailableError("managed turn records require explicit fresh-journal opt-in")

    def _require_registered_provider(self, node, provider_ref):
        from ordessa_execution_agents.harness.providers.registry.definition_admission import HarnessAdmission
        admitted = HarnessAdmission(self.environment).describe(node["binding"]["harnessDefinitionRef"])
        if safe_json(admitted.provider_ref) != safe_json(provider_ref):
            raise IdentityMismatchError("managed Codex provider is not the currently admitted original owner")
        # A declaration pin proves metadata, not the retired runtime
        # provider's identity. This old Codex coordinator is outside the
        # first-edition Unit path; never dispatch using a metadata match.
        raise GuaranteeUnavailableError("legacy Codex managed-input runtime owner is unsupported")

    def _read_capture(self, captured_ref, principal):
        metadata = self.reservations._inspect(self.reservations._capture, captured_ref, principal)
        content = self.capture_content.read_content(captured_ref, principal)
        if (not isinstance(metadata, CapturedInputEvidence)
                or not isinstance(content, ManagedTextCapture)
                or content.evidence != metadata or content.evidence.ref != captured_ref):
            raise GuaranteeUnavailableError("capture owner did not return the exact immutable capture")
        body = content.canonical_bytes()
        if _digest(body) != captured_ref.content_digest:
            raise IdentityMismatchError("canonical capture digest differs from its original reference")
        return content, body

    @staticmethod
    def _node_ref(value):
        return {"environmentNamespace": value.environment,
                "instanceId": value.instance_id, "generation": value.generation}

    @staticmethod
    def _request_key(request):
        return safe_json({"environmentNamespace": request.environment_namespace,
            "principalScope": request.principal_scope, "requestId": request.request_id})

    def _existing(self, request, node_ref, captured_ref):
        operation = self.reservations.read_existing(request)
        if operation is None:
            return None
        context = operation.intent.context_ref
        if (operation.intent.kind != "managed-input"
                or context.get("nodeRef") != self._node_ref(node_ref)
                or context.get("capturedInputRef") != captured_ref.to_dict()):
            raise IdentityMismatchError("request key is already bound to a different managed input")
        node = self.reservations._nodes.read(node_ref)
        binding = context.get("managedDispatchBinding")
        if (node is None or not isinstance(binding, Mapping)
                or node["binding"].get("harnessUnitRef") != binding.get("unitRef")):
            raise GuaranteeUnavailableError("original managed Node/Unit binding is unavailable")
        return self._outcome(operation)

    def _outcome(self, operation):
        if not callable(getattr(self.records, "read_managed_turn", None)):
            return ManagedInputOutcome("managed-codex-input/1", operation.intent.operation_ref,
                                       "unknown", None, None)
        record = self.records.read_managed_turn(operation.intent.operation_ref,
                                                input_digest=operation.digest)
        if record is None:
            # A Core reservation/claim without the original UnitRecords fact is
            # a partial commit. It is query-only and can never create a frame.
            return ManagedInputOutcome("managed-codex-input/1", operation.intent.operation_ref,
                                       "unknown", None, None)
        receipt_ref = None if record.receipt is None else f"unit-records:{record.operation_ref}:receipt"
        terminal_ref = None if record.terminal is None else f"unit-records:{record.operation_ref}:terminal"
        return ManagedInputOutcome("managed-codex-input/1", record.operation_ref,
                                   record.state, receipt_ref, terminal_ref)

    def submit(self, request: RequestKey, node_ref: ParticipantInstanceRef,
               captured_ref: CapturedInputRef, *, timeout: float = 10.0):
        self._require_managed_turn(self.records)
        env = self.environment
        if not isinstance(request, RequestKey) or not isinstance(node_ref, ParticipantInstanceRef):
            raise ValueError("authenticated RequestKey and complete NodeRef required")
        if not isinstance(captured_ref, CapturedInputRef):
            raise ValueError("original CapturedInputRef required")
        with env._admission_lock:
            prior = self._existing(request, node_ref, captured_ref)
            if prior is not None:
                return prior
            # Keep the original admission cut through read, single prepare,
            # Core reservation/claim and owner prewrite.
            node = self.reservations.check_draft_attempt(request, node_ref, captured_ref)
            content, body = self._read_capture(captured_ref, request.principal_scope)
            state = self.reservations._inspect(self.reservations._native,
                                               node_ref, request.principal_scope)
            if not isinstance(state, NativeInputState):
                raise GuaranteeUnavailableError("managed turn requires an existing confirmed native Session")
            provider_ref = state.provider_ref
            unit_ref = state.unit_ref
            self._require_registered_provider(node, provider_ref)
            operation_ref = "input-" + hashlib.sha256(safe_json({
                "environmentNamespace": env.environment_id,
                "principalScope": request.principal_scope,
                "requestId": request.request_id}).encode()).hexdigest()[:48]
            execution = self.workspace_execution.authorize_execute(
                request, node_ref, unit_ref, operation_ref, captured_ref.to_dict(),
                captured_ref.content_digest, state.management_epoch)
            if not isinstance(execution, WorkspaceExecutionEvidence):
                raise GuaranteeUnavailableError("original Workspace execute authority is unavailable")
            execution_json = execution.to_dict()
            if (execution.environment_namespace != env.environment_id
                    or execution.principal_scope != request.principal_scope
                    or execution.node_ref != self._node_ref(node_ref)
                    or execution.unit_ref != unit_ref
                    or execution.operation_ref != operation_ref
                    or execution.capture_ref != captured_ref.to_dict()
                    or execution.content_digest != captured_ref.content_digest
                    or execution.management_epoch != state.management_epoch):
                raise IdentityMismatchError("Workspace execute evidence differs from the original input")
            prepare = getattr(self.provider, "prepare_managed_turn", None)
            if not callable(prepare):
                raise GuaranteeUnavailableError("Codex prepared-frame owner is unavailable")
            prepared = prepare(unit_ref, content.envelope["text"])
            frame = getattr(prepared, "frame", None)
            frame_binding = getattr(prepared, "binding", None)
            if frame is None or not isinstance(frame_binding, Mapping):
                discard = getattr(self.provider, "discard_managed_turn", None)
                if callable(discard):
                    try: discard(unit_ref, prepared, frame_binding)
                    except BaseException: pass
                raise GuaranteeUnavailableError("Codex owner returned no original prepared frame")
            try:
                binding = plain_json_mapping(frame_binding)
            except BaseException:
                discard = getattr(self.provider, "discard_managed_turn", None)
                if callable(discard):
                    try: discard(unit_ref, prepared, frame_binding)
                    except BaseException: pass
                raise
            payload = getattr(frame, "payload", None)
            params = payload.get("params") if isinstance(payload, Mapping) else None
            frame_matches = (isinstance(params, Mapping)
                and payload.get("method") == "turn/start"
                and params.get("threadId") == binding.get("nativeThreadId")
                and params.get("input") == [{"type": "text", "text": content.envelope["text"]}]
                and getattr(frame, "protocol", None) == binding.get("protocol")
                and getattr(frame, "request_id", None) == binding.get("nativeRequestId")
                and getattr(frame, "frame_digest", None) == binding.get("frameDigest"))
            if not frame_matches:
                discard = getattr(self.provider, "discard_managed_turn", None)
                if callable(discard):
                    try: discard(unit_ref, prepared, binding)
                    except BaseException: pass
                raise IdentityMismatchError("prepared frame facts do not match the exact original text")
            binding.update({"contractVersion": DISPATCH_BINDING_VERSION,
                "operationRef": operation_ref, "unitRef": plain_json_mapping(unit_ref),
                "providerRef": plain_json_mapping(provider_ref), "managementEpoch": state.management_epoch,
                "capturedInputRef": captured_ref.to_dict(),
                "contentDigest": captured_ref.content_digest})
            claimed = False
            try:
                operation = self.reservations.reserve(request, node_ref, captured_ref,
                    {"environmentNamespace": env.environment_id,
                     "protocol": binding.get("protocol"),
                     "requestId": binding.get("nativeRequestId")},
                    managed_context={"managedDispatchBinding": binding,
                                     "workspaceExecutionEvidence": execution_json})
                if operation.intent.operation_ref != operation_ref:
                    raise IdentityMismatchError("Core operation reference differs from the prepared frame")
                invocation = self.reservations.claim_dispatch(request, self.owner_ports.issuer)
                claimed = True
                self.records.reserve_managed_turn(operation_ref=operation_ref,
                    request_key=self._request_key(request), unit_ref=unit_ref["unitId"],
                    input_digest=operation.digest, binding=binding,
                    execution_evidence=execution_json)

                def before_write(_wire):
                    current, current_body = self._read_capture(captured_ref, request.principal_scope)
                    if current_body != body or current.envelope != content.envelope:
                        raise IdentityMismatchError("captured content changed after frame preparation")
                    current_execution = self.workspace_execution.revalidate_execute(execution)
                    if (not isinstance(current_execution, WorkspaceExecutionEvidence)
                            or safe_json(current_execution.to_dict()) != safe_json(execution_json)):
                        raise AdmissionRefusedError("Workspace execute authority changed before native write")
                    self._require_registered_provider(node, provider_ref)
                    validate = getattr(self.provider, "validate_managed_turn", None)
                    if not callable(validate) or validate(unit_ref, binding) is not True:
                        raise AdmissionRefusedError("original Codex Unit/Session changed before native write")
                    target = operation.intent.context_ref["invocationBindings"]["native-input"]["targetRef"]
                    self.verifier.verify_and_consume(invocation, "submitInput", provider_ref,
                                                     target, operation.digest)
                    self.records.transition_managed_turn(operation_ref,
                        expected_revision=1, state="possibly-written")

                dispatch = getattr(self.provider, "dispatch_managed_turn", None)
                if not callable(dispatch):
                    raise GuaranteeUnavailableError("Codex one-shot dispatch owner is unavailable")
                receipt = dispatch(unit_ref, prepared, invocation, before_write=before_write,
                                   binding=binding, timeout=timeout)
                if not isinstance(receipt, Mapping):
                    raise GuaranteeUnavailableError("original Codex receipt is unavailable")
                record = self.records.read_managed_turn(operation_ref,
                                                        input_digest=operation.digest)
                self.records.transition_managed_turn(operation_ref,
                    expected_revision=record.revision, state="accepted", receipt=receipt)
                return self._outcome(operation)
            except BaseException:
                # A claim or a consumed frame is spent even if a later owner
                # transaction failed. Preserve unknown; never prepare again.
                self._mark_unknown(request, operation_ref)
                if not claimed:
                    discard = getattr(self.provider, "discard_managed_turn", None)
                    if callable(discard):
                        try:
                            discard(unit_ref, prepared, binding)
                        except BaseException:
                            pass
                raise

    def _mark_unknown(self, request, operation_ref):
        operation = self.environment._store.read_operation(request)
        if operation is None:
            return
        step = self.environment._store.read_operation_step(request, "native-input")
        if step is not None and step.outcome == "possibly-dispatched":
            try:
                self.environment._store.record_operation_step(request, operation.digest,
                    "native-input", operation.digest, step.revision, "unknown", {})
            except Exception:
                pass
        if operation_ref:
            record = self.records.read_managed_turn(operation_ref, input_digest=operation.digest)
            if record is not None and record.state in {"reserved", "possibly-written", "accepted"}:
                try:
                    self.records.transition_managed_turn(operation_ref,
                        expected_revision=record.revision, state="unknown")
                except Exception:
                    pass

    def query(self, request: RequestKey, *, timeout: float = 0.0):
        """Observe only the exact original operation and live native client."""
        self._require_managed_turn(self.records)
        env = self.environment
        with env._admission_lock:
            env._check_open()
            env._check_environment(request.environment_namespace)
            if request.principal_scope != env._principal_scope:
                raise AdmissionRefusedError("managed input query principal differs")
            if (env._policy is None or not env._policy.admit_invoke(
                    env._principal_scope, "pacthold.agents.inputs.query", "reliable")):
                raise AdmissionRefusedError("managed input query admission refused")
            if not isinstance(env._store, OperationStorePort):
                raise GuaranteeUnavailableError("original managed operation store is unavailable")
            operation = env._store.read_operation(request)
            if operation is None:
                return None
            if operation.intent.kind != "managed-input":
                raise IdentityMismatchError("request key belongs to a different operation")
            node_ref = _node(operation.intent.node_ref)
            node = self.reservations._nodes.read(node_ref)
            frozen_binding = operation.intent.context_ref.get("managedDispatchBinding")
            if (node is None or not isinstance(frozen_binding, Mapping)
                    or node["binding"].get("harnessUnitRef") != frozen_binding.get("unitRef")):
                raise GuaranteeUnavailableError("original managed Node/Unit binding is unavailable")
            self._require_registered_provider(node, frozen_binding["providerRef"])
            outcome = self._outcome(operation)
            if outcome.state != "accepted":
                return outcome
            record = self.records.read_managed_turn(operation.intent.operation_ref,
                                                    input_digest=operation.digest)
            observe = getattr(self.provider, "observe_managed_turn", None)
            if record is None or record.state != "accepted" or record.receipt is None or not callable(observe):
                return outcome
            query = self.owner_ports.issuer.issue_query(request, operation.digest, "native-input")
        query_target = operation.intent.context_ref["invocationBindings"]["native-input"]["targetRef"]
        unit_ref = record.binding["unitRef"]
        event = observe(unit_ref, record.binding, authorized_read_context=query,
            target_ref=query_target, operation_digest=operation.digest,
            native_turn_id=record.receipt["nativeTurnId"], timeout=timeout)
        if event is None:
            return outcome
        if not self.owner_ports.issuer.verified_observation(query):
            raise GuaranteeUnavailableError("original Codex owner did not verify the read-only query")
        verifier = self.owner_ports.issuer.verifier()
        verifier.verify_claimed_query(query, record.binding["providerRef"], query_target,
            operation.digest, operation_kind="managed-input")
        terminal = plain_json_mapping(event)
        status_map = {"completed": "completed", "failed": "failed", "interrupted": "interrupted"}
        if (set(terminal) != {"nativeThreadId", "nativeTurnId", "status", "event"}
                or terminal["nativeThreadId"] != record.binding["nativeThreadId"]
                or terminal["nativeTurnId"] != record.receipt["nativeTurnId"]
                or terminal["status"] not in status_map
                or not isinstance(terminal["event"], Mapping)):
            return outcome
        final = {"contractVersion": TURN_TERMINAL_VERSION,
            "nativeThreadId": terminal["nativeThreadId"],
            "nativeTurnId": terminal["nativeTurnId"], "status": terminal["status"],
            "eventDigest": _digest(safe_json(terminal["event"]).encode("utf-8")),
            "evidenceRef": f"unit-records:{record.operation_ref}:terminal"}
        state = status_map[terminal["status"]]
        with env._admission_lock:
            verifier.verify_claimed_query(query, record.binding["providerRef"], query_target,
                operation.digest, operation_kind="managed-input")
            current = self.records.read_managed_turn(record.operation_ref, input_digest=operation.digest)
            if current is None or current.state != "accepted":
                return self._outcome(operation)
            updated = self.records.transition_managed_turn(record.operation_ref,
                expected_revision=current.revision, state=state, terminal=final)
            step = env._store.read_operation_step(request, "native-input")
            if step is not None and step.outcome == "possibly-dispatched":
                evidence = {"contractVersion": "managed-turn-core-reference/1",
                    "operationRef": operation.intent.operation_ref,
                    "unitRecordsRef": f"unit-records:{updated.operation_ref}:terminal",
                    "terminalDigest": final["eventDigest"]}
                env._store.record_operation_step(request, operation.digest,
                    "native-input", operation.digest, step.revision, "concluded", evidence)
            return self._outcome(operation)


__all__ = ["TEXT_CAPTURE_VERSION", "DISPATCH_BINDING_VERSION", "TURN_RECEIPT_VERSION",
           "TURN_TERMINAL_VERSION", "ManagedTextCapture", "ManagedTextCaptureContentPort",
           "ManagedCodexInputService"]

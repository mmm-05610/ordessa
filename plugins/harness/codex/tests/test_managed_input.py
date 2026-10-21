"""Managed text codec and fail-closed contract tests; no native/model effects."""
import hashlib
import json
import os
from types import SimpleNamespace

import pytest

from ordessa_units.errors import UnitGuaranteeUnavailable, UnitOperationUnknown
from ordessa_units.channels.reservations import CapturedInputEvidence, CapturedInputRef
from ordessa_harness_codex.managed_input import ManagedTextCapture, TEXT_CAPTURE_VERSION
from ordessa_units.channels.reservations import ManagedInputReservations
from ordessa_units.admission.owner_ports import AgentOwnerPorts, AgentProviderView
from ordessa_harness_codex.managed_input import ManagedCodexInputService
from ordessa_units.public import (
    AgentContributionSet, AgentOwnerPorts, AgentProviderView,
    InvocationCurrentState, InvocationGrant, InvocationIssuer,
)
from ordessa_units.bindings.contracts import DirectoryBindingRef
from pacthold.environment import Environment, InstallationRecord
from ordessa_infrastructure.identifiers import RequestKey
from ordessa_units.definitions.admission_identity import AgentNodeRef
from ordessa_units.definitions.operations import OperationIntent, StepIntent
from ordessa_infrastructure.encoding.immutable_json import safe_json
from pacthold.adapters.security.fingerprint import ProtectedFingerprintHmac
from pacthold.adapters.sqlite.environment.store import SqliteStorePort
from ordessa_harness_codex import CodexRuntimeProvider
from ordessa_harness_codex.client import CodexAppServerClient
from ordessa_harness_codex.projection import CodexUnitProjection
from ordessa_units.records.operation_journal import OperationJournal
from ordessa_units.records.unit_records import (
    CanonicalConfigurationScopeRef, UnitRecords,
)
from ordessa_agents.harness.transport import Message, RequestTimeout


NODE = {"environmentNamespace": "test", "instanceId": "node", "generation": 1}


def capture(envelope, metadata):
    body = __import__("json").dumps(envelope, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")
    ref = CapturedInputRef("test", "capture-1", 2,
        "sha256:" + hashlib.sha256(body).hexdigest())
    evidence = CapturedInputEvidence(ref, NODE, "draft-1", 3)
    return ManagedTextCapture(evidence, envelope, metadata)


def test_managed_capture_freezes_canonical_text_without_normalizing_it():
    value = capture({"schemaVersion": TEXT_CAPTURE_VERSION, "text": "原文\n"},
        {"attachmentDigests": (), "configOperationIds": (), "handles": (), "baseRevision": None})
    assert value.canonical_bytes() == b'{"schemaVersion":"managed-codex-text/1","text":"' + "原文\\n".encode() + b'"}'


@pytest.mark.parametrize("envelope,metadata", [
    ({"schemaVersion": TEXT_CAPTURE_VERSION, "text": "text", "configuration": {}},
     {"attachmentDigests": (), "configOperationIds": (), "handles": (), "baseRevision": None}),
    ({"schemaVersion": TEXT_CAPTURE_VERSION, "text": "text"},
     {"attachmentDigests": ("sha256:" + "a" * 64,), "configOperationIds": (), "handles": (), "baseRevision": None}),
])
def test_managed_capture_refuses_unrepresented_or_attached_facts(envelope, metadata):
    value = capture(envelope, metadata)
    with pytest.raises(UnitGuaranteeUnavailable):
        value.canonical_bytes()


def test_managed_capture_rejects_changed_canonical_content_digest():
    value = capture({"schemaVersion": TEXT_CAPTURE_VERSION, "text": "original"},
        {"attachmentDigests": (), "configOperationIds": (), "handles": (), "baseRevision": None})
    object.__setattr__(value, "envelope", {"schemaVersion": TEXT_CAPTURE_VERSION, "text": "changed"})
    assert value.evidence.ref.content_digest != "sha256:" + hashlib.sha256(value.canonical_bytes()).hexdigest()


def test_missing_original_capture_and_workspace_ports_keep_use_unavailable():
    class Issuer:
        def __init__(self):
            self._store = object()

        def verify(self, *_args):
            return None

    issuer = Issuer()

    class Verifier:
        _verify = issuer.verify

    class Records:
        verifier = Verifier()

    class Environment:
        _store = issuer._store

    environment = Environment()
    owners = AgentOwnerPorts(issuer, AgentProviderView(Records(), Records.verifier))
    reservations = ManagedInputReservations(environment, SimpleNamespace(_environment=environment),
                                            invocation_issuer=issuer)
    environment._agent_services = SimpleNamespace(managed_inputs=reservations)
    environment._agent_owner_ports = owners
    provider = type("Provider", (), {"records": owners.provider_view.records,
                                     "verifier": owners.provider_view.verifier})()
    with pytest.raises(UnitGuaranteeUnavailable, match="original capture-content and Workspace execute"):
        ManagedCodexInputService(environment, reservations, owners, provider)


class _Policy:
    def admit_invoke(self, *_args): return True
    def admit_object_access(self, *_args): return True


class _Authority:
    issuer_ref = {"environmentNamespace": "managed-test", "authorityId": "controlled"}

    def authorize(self, request, actions, target_ref, delegation_ref):
        return InvocationGrant(request.principal_scope, delegation_ref, actions, target_ref,
            "controlled-revision", 10000.0, self.issuer_ref)

    def revalidate(self, grant, request, actions, target_ref): return grant


class _CurrentState:
    def __init__(self, directory_ref): self.directory_ref = directory_ref

    def inspect(self, request, provider_ref, context_ref, target_ref, action):
        return InvocationCurrentState(provider_ref, True, 1, self.directory_ref, True)


class _Scope:
    def issue_scope(self, provider_ref, node_ref, private_root_facts):
        return CanonicalConfigurationScopeRef("managed-test", "controlled-scope", "1")

    def verify_scope(self, scope_ref, private_root_facts):
        return scope_ref == CanonicalConfigurationScopeRef("managed-test", "controlled-scope", "1")

    def map_legacy_scope(self, _target): return None


class _SessionEvidence:
    def verify_binding(self, unit, correlation, evidence):
        assert evidence == "controlled-session-proof"
        return {"nativeRealm": "controlled-codex", "sessionId": "thread-1",
                "evidenceRef": "controlled-session-proof"}


class _Epoch:
    def current_epoch(self, _node): return 1


class _Nodes:
    def __init__(self, node, environment): self.node, self._environment = node, environment
    def read(self, ref):
        return self.node if ref == AgentNodeRef("managed-test", "node", 1) else None


class _Capture:
    def __init__(self, evidence): self.evidence = evidence
    def inspect(self, captured_ref, principal):
        return self.evidence if captured_ref == self.evidence.ref and principal == "principal" else None


class _NativeInput:
    def __init__(self, state): self.state = state
    def inspect(self, _node_ref, _principal): return self.state


class _CaptureContent:
    def __init__(self, value): self.value = value
    def read_content(self, captured_ref, principal):
        return self.value if captured_ref == self.value.evidence.ref and principal == "principal" else None


class _Workspace:
    def authorize_execute(self, request, node_ref, unit_ref, operation_ref,
                          capture_ref, content_digest, management_epoch):
        from ordessa_units.channels.contracts import WorkspaceExecutionEvidence
        return WorkspaceExecutionEvidence(request.environment_namespace, request.principal_scope,
            {"environmentNamespace": node_ref.environment, "instanceId": node_ref.instance_id,
             "generation": node_ref.generation}, unit_ref, operation_ref, capture_ref,
            content_digest, management_epoch, "controlled-workspace-evidence")

    def revalidate_execute(self, evidence): return evidence


class _NativeChannel:
    def __init__(self, turn_id):
        self.turn_id = turn_id
        self.sent = []
        self.unknown = False
        self.messages = []

    def send_frame(self, wire, *, before_write):
        before_write()
        self.sent.append(wire)
        request = json.loads(wire)
        self.messages.append(Message({"id": request["id"], "result": {"turn": {
            "id": self.turn_id, "items": [], "status": "inProgress"}}}))
        self.messages.append(Message({"method": "turn/completed", "params": {
            "threadId": "thread-1", "turn": {"id": self.turn_id, "items": [],
            "status": "completed"}}}))

    def acknowledge_frame(self, _request_id): pass
    def mark_input_unknown(self): self.unknown = True
    def next_message(self, *, timeout):
        if self.messages: return self.messages.pop(0)
        raise RequestTimeout("controlled", None, timeout)


def _reserve_core_invocation(environment, issuer, provider_ref, directory_ref,
                             node_ref, action, request_id, target_ref, epoch=1):
    request = RequestKey("managed-test", "principal", request_id)
    digest = "sha256:" + hashlib.sha256(request_id.encode()).hexdigest()
    step_id = "controlled-" + action
    context = {"environmentNamespace": request.environment_namespace,
        "directoryBindingRef": directory_ref.to_dict(),
        "invocationBindings": {step_id: {"action": action, "targetRef": target_ref,
            "delegationRef": None, "cleanup": False}}}
    step = StepIntent(step_id, provider_ref, digest, request_id + "-correlation",
                      management_epoch=epoch)
    intent = OperationIntent("operation-" + request_id, "controlled-owner-setup", None,
        context, (step,), {"environmentNamespace": node_ref.environment,
            "instanceId": node_ref.instance_id, "generation": node_ref.generation}, epoch)
    environment._store.reserve_operation(request, digest, intent)
    return issuer.issue(request, digest, step_id, action, target_ref)


def test_managed_input_uses_same_environment_issuer_records_and_original_client(tmp_path):
    directory_ref = DirectoryBindingRef("managed-test", "workspace", 1, "sha256:" + "e" * 64)
    store = SqliteStorePort(tmp_path / "core.sqlite")
    environment = Environment("managed-test", store=store, policy=_Policy(),
        fingerprint_port=ProtectedFingerprintHmac(
            {"controlled": b"managed-input-controlled-key"}, active_key_id="controlled"),
        principal_scope="principal")
    authority = _Authority()
    issuer = InvocationIssuer(store, authority, _CurrentState(directory_ref), clock=lambda: 1.0)
    verifier = issuer.verifier()
    journal_path = tmp_path / "operations.sqlite"
    fd = os.open(journal_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    os.close(fd)
    journal = OperationJournal(journal_path, managed_turn_opt_in=True)
    records = UnitRecords(journal, scope_authority=_Scope(), native_evidence=_SessionEvidence(),
        verifier=verifier, epoch_port=_Epoch(), managed_turn_opt_in=True)

    definition_ref = {"environmentNamespace": "managed-test", "definitionId": "controlled-codex", "revision": "1"}
    projection = CodexUnitProjection(records, start_authority=lambda _unit, context: context.facts)
    channel = _NativeChannel("turn-1")
    client = CodexAppServerClient(channel)
    provider = CodexRuntimeProvider(definition_ref=definition_ref,
        implementation_digest="sha256:" + "a" * 64, unit_records=records,
        projection=projection, verifier=verifier,
        channel_factory=SimpleNamespace(open=lambda *_args: client))
    environment.install(InstallationRecord("controlled-codex", "a" * 64))
    environment.enable("controlled-codex")
    environment.activate("controlled-codex", AgentContributionSet(agent_runtime_providers=(provider,)))
    provider_ref = environment.agent_runtime_contribution(definition_ref).provider_ref
    node_ref = AgentNodeRef("managed-test", "node", 1)
    node_dict = {"environmentNamespace": node_ref.environment,
                 "instanceId": node_ref.instance_id, "generation": node_ref.generation}

    prepare_context = _reserve_core_invocation(environment, issuer, provider_ref, directory_ref,
        node_ref, "prepare", "unit-prepare", node_dict)
    unit, created = records.reserve_unit(prepare_context, provider_ref=provider_ref,
        node_ref=node_dict, input_digest=prepare_context.facts["inputDigest"],
        private_root_facts={"environmentNamespace": "managed-test", "rootRef": "controlled"})
    assert created
    start_context = _reserve_core_invocation(environment, issuer, provider_ref, directory_ref,
        node_ref, "start", "unit-start", node_dict)
    ticket = records.begin_session(unit.unit_ref, start_context,
                                   input_digest=start_context.facts["inputDigest"])
    records.record_session(ticket, expected_source_revision=2, state="confirmed",
                           evidence="controlled-session-proof")
    provider._channels[unit.unit_ref] = client

    session_ref = {"environmentNamespace": "managed-test", "ownerProviderRef": provider_ref,
                   "sourceRevision": "session-3", "sessionId": "thread-1"}
    state = __import__('ordessa_units.channels.reservations', fromlist=["NativeInputState"]).NativeInputState(
        node_dict, provider_ref, unit.public_ref, session_ref, 3, 1, directory_ref,
        {"environmentNamespace": "managed-test", "sourceRevision": "configuration-1"})
    envelope = {"schemaVersion": TEXT_CAPTURE_VERSION, "text": "controlled original"}
    body = json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    capture_ref = CapturedInputRef("managed-test", "capture-1", 1,
        "sha256:" + hashlib.sha256(body).hexdigest())
    evidence = CapturedInputEvidence(capture_ref, node_dict, "draft-1", 1)
    content = ManagedTextCapture(evidence, envelope,
        {"attachmentDigests": (), "configOperationIds": (), "handles": (), "baseRevision": None})
    node = {"binding": {"harnessProviderRef": provider_ref, "harnessDefinitionRef": definition_ref,
                        "harnessUnitRef": unit.public_ref},
            "lineage": {"profileSnapshotRef": {"environmentNamespace": "managed-test",
                "profileId": "controlled-profile", "revision": 1}}}
    nodes = _Nodes(node, environment)
    capture = _Capture(evidence)
    native_input = _NativeInput(state)
    content_port, workspace = _CaptureContent(content), _Workspace()
    owners = AgentOwnerPorts(issuer, AgentProviderView(records, verifier),
        input_capture_port=capture, native_input_state_port=native_input,
        managed_capture_content_port=content_port, workspace_execution_port=workspace)
    reservations = __import__('ordessa_units.channels.reservations', fromlist=["ManagedInputReservations"]).ManagedInputReservations(
        environment, nodes, capture_port=capture, native_state_port=native_input,
        invocation_issuer=issuer)
    environment._agent_owner_ports = owners
    environment._agent_services = SimpleNamespace(managed_inputs=reservations)
    service = ManagedCodexInputService(environment, reservations, owners, provider)
    request = RequestKey("managed-test", "principal", "input-request-1")

    accepted = service.submit(request, node_ref, capture_ref, timeout=1.0)
    assert accepted.state == "accepted" and accepted.native_receipt_ref
    assert len(channel.sent) == 1 and not channel.unknown
    replay = service.submit(request, node_ref, capture_ref, timeout=1.0)
    assert replay == accepted and len(channel.sent) == 1
    with pytest.raises(UnitOperationUnknown, match="unresolved attempt"):
        service.submit(RequestKey("managed-test", "principal", "input-request-2"),
                       node_ref, capture_ref, timeout=1.0)
    assert len(channel.sent) == 1
    completed = service.query(request, timeout=1.0)
    assert completed.state == "completed" and completed.terminal_evidence_ref
    assert len(channel.sent) == 1

    issuer.close()
    environment.close()
    store.close()

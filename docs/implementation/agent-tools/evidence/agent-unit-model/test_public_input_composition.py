"""Public composition of managed-input reservations on the existing Core.

These are controlled SQLite/Core/Issuer contract checks. The two fixtures
exercise ordinary Session and explicit Sessionless Unit bindings; neither
fixture sends input or establishes production owner/P/M evidence.
"""
from pathlib import Path
import sys

import pytest

_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(_ROOT / "products/agent-tools/tests/integration"))
sys.path.insert(0, str(_ROOT / "docs/implementation/agent-tools/evidence/agent-unit-model"))

# Import the provider fixture in this module as well: pytest does not discover
# a fixture merely because another fixture module imported it.
from test_node_publication import setup as node_fixture  # noqa: F401
from test_managed_input_reservations import Capture, Native, managed
from test_sessionless_input import first_input

from ordessa_environment_api import GuaranteeUnavailableError, RequestKey, UnknownResultError
from ordessa_environment_api.operations import node_holder
from ordessa_persistence_sqlite import SqliteStorePort
from pacthold.agents import inputs as input_contracts
from pacthold.agents import public as agent_public
from pacthold.agents.access.invocation import InvocationIssuer
from pacthold.agents.inputs import (
    CapturedInputEvidence,
    CapturedInputRef,
    FirstInputObservation,
    FirstInputObservationPort,
    ManagedInputReservations,
    NativeInputState,
    NativeInputStatePort,
    SessionlessNativeInputState,
    ControlledInputCapturePort,
)
from pacthold.agents.nodes.publication import encode_node_ref


class _FirstObserver:
    """Generic owner fixture; the wrong-store case must stop before observe."""

    def __init__(self):
        self.calls = 0

    def observe(self, operation, query_context):
        self.calls += 1
        return None


class _QueryTrackingIssuer(InvocationIssuer):
    """Observe that an unavailable reconciliation gate issues no query."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.query_calls = 0

    def issue_query(self, *args, **kwargs):
        self.query_calls += 1
        return super().issue_query(*args, **kwargs)


def _ports(parts):
    return parts[6], parts[7], _FirstObserver()


def _service_kwargs(parts, *, ports=None):
    capture, native, observer = ports if ports is not None else _ports(parts)
    return {
        "invocation_issuer": parts[13],
        "input_capture_port": capture,
        "native_input_state_port": native,
        "first_input_observation_port": observer,
    }


def _reserve_session(parts, services):
    node = parts[4]
    captured_ref = CapturedInputRef("env", "public-session-capture", 1,
                                    "sha256:" + "e" * 64)
    parts[6].evidence = CapturedInputEvidence(
        captured_ref, encode_node_ref(node), "public-session-draft", 1)
    request = RequestKey("env", "principal", "public-session-input")
    correlation = {"environmentNamespace": "env", "protocol": "controlled-record/7",
                   "requestId": "record-ticket-7"}
    operation = services.managed_inputs.reserve(request, node, captured_ref, correlation)
    return operation, request, correlation


def _reserve_sessionless(parts, services):
    node, capture, native = parts[2], parts[3], parts[4]
    captured_ref = CapturedInputRef("env", "public-unit-capture", 1,
                                    "sha256:" + "f" * 64)
    capture.values[captured_ref.capture_id] = CapturedInputEvidence(
        captured_ref, encode_node_ref(node), "public-unit-draft", 1)
    request = RequestKey("env", "principal", "public-unit-input")
    correlation = {"environmentNamespace": "env", "protocol": "controlled-unit-call/9",
                   "requestId": 9}
    operation = services.managed_inputs.reserve(request, node, captured_ref, correlation)
    return operation, request, correlation


def _assert_single_claim(parts, services, operation, request, expected_target, native, issuer):
    store = parts[0]
    fixed = operation.intent.context_ref
    assert fixed["nativeCorrelation"]["protocol"] in {
        "controlled-record/7", "controlled-unit-call/9"}
    assert fixed["invocationBindings"]["native-input"]["targetRef"] == expected_target
    context = services.managed_inputs.claim_dispatch(request, issuer)
    facts = issuer.verifier().verify_and_consume(
        context, "submitInput", operation.intent.steps[0].pinned_provider_ref,
        expected_target, operation.digest)
    assert facts["action"] == "submitInput"
    assert facts["targetRef"] == expected_target
    first_step = store.read_operation_step(request, "native-input")
    assert first_step is not None and first_step.outcome == "possibly-dispatched"
    with pytest.raises(UnknownResultError):
        services.managed_inputs.claim_dispatch(request, issuer)
    assert store.read_operation_step(request, "native-input") == first_step
    assert native.dispatch_calls == 0


def test_public_input_contract_exports_and_compose_once_identity(managed):
    parts = managed
    env = parts[1]
    ports = _ports(parts)
    names = (
        "CapturedInputRef", "CapturedInputEvidence", "ControlledInputCapturePort",
        "NativeInputState", "SessionlessNativeInputState", "NativeInputStatePort",
        "FirstInputObservation", "FirstInputObservationPort", "ManagedInputReservations",
    )
    for name in names:
        assert getattr(agent_public, name) is getattr(input_contracts, name)
    assert agent_public.AgentServices is not None
    services = agent_public.agent_services(env, **_service_kwargs(parts, ports=ports))
    assert isinstance(services.managed_inputs, ManagedInputReservations)
    assert services.managed_inputs._environment is env
    assert services.managed_inputs._nodes is services.nodes
    assert agent_public.agent_services(env, **_service_kwargs(parts, ports=ports)) is services
    assert agent_public.agent_services(env, **_service_kwargs(parts, ports=ports)).managed_inputs is services.managed_inputs
    assert services.profiles.capabilities()["managedInput"] is False


@pytest.mark.parametrize("port_name", [
    "input_capture_port", "native_input_state_port", "first_input_observation_port",
])
def test_public_input_port_cannot_be_added_after_initial_none(managed, port_name):
    parts = managed
    env = parts[1]
    ports = _ports(parts)
    port_by_name = dict(zip(("input_capture_port", "native_input_state_port",
                             "first_input_observation_port"), ports))
    agent_public.agent_services(env, invocation_issuer=parts[13])
    with pytest.raises(ValueError):
        agent_public.agent_services(env, **{port_name: port_by_name[port_name]})


@pytest.mark.parametrize("port_name", [
    "input_capture_port", "native_input_state_port", "first_input_observation_port",
])
def test_public_input_port_replacement_is_rejected(managed, port_name):
    parts = managed
    env = parts[1]
    ports = _ports(parts)
    port_by_name = dict(zip(("input_capture_port", "native_input_state_port",
                             "first_input_observation_port"), ports))
    original = port_by_name[port_name]
    if port_name == "input_capture_port":
        replacement = Capture(original.evidence)
    elif port_name == "native_input_state_port":
        replacement = Native(original.state)
    else:
        replacement = _FirstObserver()
    agent_public.agent_services(env, invocation_issuer=parts[13], **{port_name: original})
    with pytest.raises(ValueError):
        agent_public.agent_services(env, **{port_name: replacement})


@pytest.mark.parametrize("missing_ports", [
    pytest.param(("input_capture_port", "native_input_state_port"), id="both-missing"),
    pytest.param(("input_capture_port",), id="capture-missing"),
    pytest.param(("native_input_state_port",), id="native-state-missing"),
])
def test_unassembled_public_input_is_unavailable_without_request_step_or_usage(managed, missing_ports):
    parts = managed
    store, env, _, _, node, captured_ref, capture, native, _, request, _, _, _, issuer, _ = parts
    available_ports = {
        "input_capture_port": capture,
        "native_input_state_port": native,
    }
    kwargs = {name: port for name, port in available_ports.items() if name not in missing_ports}
    services = agent_public.agent_services(env, invocation_issuer=issuer, **kwargs)
    correlation = {"environmentNamespace": "env", "protocol": "controlled-unassembled/1",
                   "requestId": "unassembled"}
    holder = node_holder("env", node.instance_id, node.generation)
    usages_before = store.read_usages("env", holder)
    capture_calls, native_calls = capture.calls, native.calls
    with pytest.raises(GuaranteeUnavailableError):
        services.managed_inputs.reserve(request, node, captured_ref, correlation)
    assert store.read_operation(request) is None
    assert store.read_operation_step(request, "native-input") is None
    assert store.list_domain("env", input_contracts.DRAFT_ATTEMPTS) == ()
    assert store.list_domain("env", input_contracts.FIRST_SESSION_ATTEMPTS) == ()
    assert store.read_usages("env", holder) == usages_before
    assert capture.calls == capture_calls and native.calls == native_calls


def test_sessionless_reconcile_without_observation_port_issues_no_query_or_mutation(first_input):
    parts = first_input
    store, env, node, capture, native = parts[:5]
    observerless_issuer = _QueryTrackingIssuer(store, parts[6], parts[7], clock=lambda: 50)
    services = agent_public.agent_services(env, invocation_issuer=observerless_issuer,
        input_capture_port=capture, native_input_state_port=native)
    operation, request, _ = _reserve_sessionless(parts, services)
    holder = node_holder("env", node.instance_id, node.generation)
    usages_before = store.read_usages("env", holder)
    draft_domain_before = store.list_domain("env", input_contracts.DRAFT_ATTEMPTS)
    first_domain_before = store.list_domain("env", input_contracts.FIRST_SESSION_ATTEMPTS)
    step_before = store.read_operation_step(request, "native-input")
    assert step_before is None

    with pytest.raises(GuaranteeUnavailableError):
        services.managed_inputs.reconcile_first_input(request, observerless_issuer)

    assert observerless_issuer.query_calls == 0
    assert store.read_operation(request) == operation
    assert store.read_operation_step(request, "native-input") == step_before
    assert store.list_domain("env", input_contracts.DRAFT_ATTEMPTS) == draft_domain_before
    assert store.list_domain("env", input_contracts.FIRST_SESSION_ATTEMPTS) == first_domain_before
    assert store.read_usages("env", holder) == usages_before
    assert native.dispatch_calls == 0


def test_public_session_reservation_and_claim_preserve_generic_correlation(managed):
    parts = managed
    # Ordinary Session input needs capture/native-state ports, but its
    # reserve+claim path does not require first-input reconciliation evidence.
    services = agent_public.agent_services(parts[1], invocation_issuer=parts[13],
        input_capture_port=parts[6], native_input_state_port=parts[7])
    operation, request, correlation = _reserve_session(parts, services)
    state = parts[7].state
    assert operation.intent.kind == "managed-input"
    assert operation.intent.context_ref["nativeCorrelation"] == correlation
    assert operation.intent.context_ref["nativeSessionRef"] == state.session_ref
    assert "sessionlessInputBinding" not in operation.intent.context_ref
    _assert_single_claim(parts, services, operation, request, state.session_ref,
                         parts[7], parts[13])


def test_public_sessionless_reservation_and_claim_preserve_generic_correlation(first_input):
    parts = first_input
    observer = _FirstObserver()
    ports = (parts[3], parts[4], observer)
    services = agent_public.agent_services(parts[1],
        invocation_issuer=parts[8], input_capture_port=ports[0],
        native_input_state_port=ports[1], first_input_observation_port=ports[2])
    operation, request, correlation = _reserve_sessionless(parts, services)
    state = parts[4].state
    assert operation.intent.kind == "managed-input"
    assert operation.intent.context_ref["nativeCorrelation"] == correlation
    assert operation.intent.context_ref["sessionlessInputBinding"] == state.binding()
    assert "nativeSessionRef" not in operation.intent.context_ref
    _assert_single_claim(parts, services, operation, request, state.unit_ref,
                         parts[4], parts[8])


def test_wrong_store_issuer_is_refused_by_original_public_claim_and_reconcile_gates(first_input, tmp_path):
    parts = first_input
    observer = _FirstObserver()
    services = agent_public.agent_services(parts[1], invocation_issuer=parts[8],
        input_capture_port=parts[3], native_input_state_port=parts[4],
        first_input_observation_port=observer)
    operation, request, _ = _reserve_sessionless(parts, services)
    foreign = SqliteStorePort(tmp_path / "foreign-input-store.sqlite")
    try:
        foreign_issuer = type(parts[8])(foreign, parts[6], parts[7], clock=lambda: 50)
        with pytest.raises(GuaranteeUnavailableError):
            services.managed_inputs.claim_dispatch(request, foreign_issuer)
        with pytest.raises(GuaranteeUnavailableError):
            services.managed_inputs.reconcile_first_input(request, foreign_issuer)
        assert parts[0].read_operation(request) == operation
        assert parts[0].read_operation_step(request, "native-input") is None
        assert foreign.read_operation(request) is None
        assert foreign.read_operation_step(request, "native-input") is None
        assert observer.calls == 0
        assert parts[4].dispatch_calls == 0
    finally:
        foreign.close()

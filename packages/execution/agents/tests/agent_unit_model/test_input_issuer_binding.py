"""The original Environment issuer is fixed when managed input is composed.

These tests use real temporary core stores and controlled owner ports only;
they do not submit a native input or start a process.
"""
from pathlib import Path
import sys

import pytest

_ROOT = Path(__file__).resolve().parents[5]

# Register fixture dependencies explicitly for isolated pytest collection.
from agent_tools_fixtures.node_publication import setup as node_fixture  # noqa: F401
from agent_tools_fixtures.invocation_authority import Authority, CurrentState  # noqa: F401
from test_managed_input_reservations import managed as managed_fixture, reserve as reserve_managed
from test_sessionless_input import first_input as first_input_fixture, reserve as reserve_sessionless

from ordessa_infrastructure.identifiers import RequestKey
from ordessa_execution_api.environment import (
    AdmissionRefusedError, GuaranteeUnavailableError, IdentityMismatchError,
    UnknownResultError,
)
from ordessa_units.channels.reservations import (
    CapturedInputEvidence, CapturedInputRef, ManagedInputReservations,
)
from ordessa_units.admission.invocation import InvocationAuthorityRefused, InvocationIssuer
from ordessa_units.bindings.publication import NodePublication
from ordessa_units.public import unit_services


def _same_store_issuer(parts, *, authority=None):
    return InvocationIssuer(parts[0], authority or parts[11], parts[12], clock=lambda: 50)


@pytest.mark.parametrize("same_authority", [False, True])
def test_direct_binding_rejects_other_same_store_issuer_before_claim_then_original_claims(
        managed_fixture, same_authority):
    parts = managed_fixture
    store, native, inputs, request, bound = parts[0], parts[7], parts[8], parts[9], parts[13]
    operation = reserve_managed(parts)
    alternative_authority = parts[11] if same_authority else Authority()
    alternative = _same_store_issuer(parts, authority=alternative_authority)
    authorize_calls = []
    original_authorize = alternative_authority.authorize

    def count_authorize(*args, **kwargs):
        authorize_calls.append((args, kwargs))
        return original_authorize(*args, **kwargs)

    alternative_authority.authorize = count_authorize
    issued_before = len(bound._issued)
    native_reads_before = native.calls
    current_reads_before = parts[12].inspect_calls
    with pytest.raises(InvocationAuthorityRefused):
        inputs.claim_dispatch(request, alternative)
    assert authorize_calls == []
    assert len(bound._issued) == issued_before
    assert native.calls == native_reads_before
    assert parts[12].inspect_calls == current_reads_before
    assert store.read_operation_step(request, "native-input") is None
    assert native.dispatch_calls == 0

    context = inputs.claim_dispatch(request, bound)
    assert context.facts["operationRef"] == operation.intent.operation_ref
    assert store.read_operation_step(request, "native-input").outcome == "possibly-dispatched"
    assert native.dispatch_calls == 0
    with pytest.raises(UnknownResultError):
        inputs.claim_dispatch(request, bound)
    assert store.read_operation_step(request, "native-input").outcome == "possibly-dispatched"
    assert native.dispatch_calls == 0
    alternative.close()


def test_public_composition_keeps_original_issuer_and_rejects_replacement(managed_fixture):
    parts = managed_fixture
    store, env, node, capture_ref, capture, native, bound = (
        parts[0], parts[1], parts[4], parts[5], parts[6], parts[7], parts[13])
    services = unit_services(env, invocation_issuer=bound,
        input_capture_port=capture, native_input_state_port=native)
    assert services.managed_inputs._issuer is bound

    # Omitting the already-fixed optional argument is a read/reuse operation.
    assert unit_services(env) is services
    replacement = _same_store_issuer(parts)
    with pytest.raises(ValueError):
        unit_services(env, invocation_issuer=replacement)
    assert services.managed_inputs._issuer is bound

    request, correlation = parts[9], parts[10]
    operation = services.managed_inputs.reserve(request, node, capture_ref, correlation)
    before_step = store.read_operation_step(request, "native-input")
    authority_calls_before = parts[11].revalidate_calls
    native_reads_before = native.calls
    current_reads_before = parts[12].inspect_calls
    with pytest.raises(InvocationAuthorityRefused):
        services.managed_inputs.claim_dispatch(request, replacement)
    assert before_step is None
    assert store.read_operation_step(request, "native-input") is None
    assert parts[11].revalidate_calls == authority_calls_before
    assert native.calls == native_reads_before
    assert parts[12].inspect_calls == current_reads_before
    assert native.dispatch_calls == 0

    context = services.managed_inputs.claim_dispatch(request, bound)
    assert context.facts["operationRef"] == operation.intent.operation_ref
    assert store.read_operation_step(request, "native-input").outcome == "possibly-dispatched"
    assert native.dispatch_calls == 0
    replacement.close()


class CountingFirstInputObserver:
    def __init__(self, issuer):
        self.issuer = issuer
        self.calls = 0

    def observe(self, operation, query_context):
        self.calls += 1
        self.issuer.verifier().verify_and_consume(query_context, "query",
            operation.intent.steps[0].pinned_provider_ref,
            operation.intent.context_ref["sessionlessInputBinding"]["unitRef"], operation.digest)
        return None


def test_reconcile_wrong_same_store_issuer_is_refused_before_owner_or_query(first_input_fixture):
    parts = first_input_fixture
    store, native, inputs, request, bound = parts[0], parts[4], parts[5], None, parts[8]
    operation = reserve_sessionless(parts)
    request = operation.request
    context = inputs.claim_dispatch(request, bound)
    bound.verifier().verify_and_consume(context, "submitInput", native.state.provider_ref,
        native.state.unit_ref, operation.digest)
    store.record_operation_step(request, operation.digest, "native-input", operation.digest, 1,
                                "unknown", {})
    observer = CountingFirstInputObserver(bound)
    inputs._first_observation = observer
    alternative = InvocationIssuer(store, parts[6], parts[7], clock=lambda: 50)
    issued_before = len(bound._issued)
    authority_calls_before = parts[6].revalidate_calls
    current_reads_before = parts[7].inspect_calls
    native_reads_before = native.calls

    with pytest.raises(InvocationAuthorityRefused):
        inputs.reconcile_first_input(request, alternative)
    assert observer.calls == 0
    assert len(bound._issued) == issued_before
    assert parts[6].revalidate_calls == authority_calls_before
    assert parts[7].inspect_calls == current_reads_before
    assert native.calls == native_reads_before
    assert store.read_operation_step(request, "native-input").outcome == "unknown"
    assert native.dispatch_calls == 0

    with pytest.raises(UnknownResultError):
        inputs.reconcile_first_input(request, bound)
    assert observer.calls == 1
    assert store.read_operation_step(request, "native-input").outcome == "unknown"
    assert native.dispatch_calls == 0
    alternative.close()


def test_unbound_reservation_cannot_late_bind_issuer_for_claim(first_input_fixture):
    parts = first_input_fixture
    store, env, node, capture, native, _, _, _, bound = parts
    unbound = ManagedInputReservations(env, NodePublication(env), capture, native)
    request_id, draft_id = "unbound-late-claim", "unbound-draft"
    captured_ref = CapturedInputRef("env", "capture-unbound", 1, "sha256:" + "e" * 64)
    capture.values[captured_ref.capture_id] = CapturedInputEvidence(captured_ref, native.state.node_ref, draft_id, 1)
    operation = unbound.reserve(RequestKey("env", "principal", request_id), node, captured_ref,
        {"environmentNamespace": "env", "protocol": "controlled-native/1", "requestId": request_id})
    issued_before = len(bound._issued)
    native_reads_before = native.calls
    with pytest.raises(GuaranteeUnavailableError):
        unbound.claim_dispatch(operation.request, bound)
    assert len(bound._issued) == issued_before
    assert native.calls == native_reads_before
    assert store.read_operation_step(operation.request, "native-input") is None
    assert native.dispatch_calls == 0


def test_unbound_reservation_cannot_late_bind_issuer_for_reconcile(first_input_fixture):
    parts = first_input_fixture
    store, env, _, _, native, inputs, authority, current, bound = parts
    operation = reserve_sessionless(parts)
    request = operation.request
    context = inputs.claim_dispatch(request, bound)
    bound.verifier().verify_and_consume(context, "submitInput", native.state.provider_ref,
        native.state.unit_ref, operation.digest)
    store.record_operation_step(request, operation.digest, "native-input", operation.digest, 1,
                                "unknown", {})
    observer = CountingFirstInputObserver(bound)
    unbound = ManagedInputReservations(env, inputs._nodes, None, None, observer)
    authority_calls_before = authority.revalidate_calls
    current_reads_before = current.inspect_calls
    native_reads_before = native.calls
    issued_before = len(bound._issued)

    with pytest.raises(GuaranteeUnavailableError):
        unbound.reconcile_first_input(request, bound)
    assert observer.calls == 0
    assert len(bound._issued) == issued_before
    assert authority.revalidate_calls == authority_calls_before
    assert current.inspect_calls == current_reads_before
    assert native.calls == native_reads_before
    assert store.read_operation_step(request, "native-input").outcome == "unknown"
    assert native.dispatch_calls == 0


@pytest.mark.parametrize("failure", ["environment", "principal", "reserve-invoke"])
def test_claim_checks_request_authority_before_persistent_operation_read(
        managed_fixture, failure, monkeypatch):
    parts = managed_fixture
    store, env, policy, _, _, _, _, native, inputs, request, _, authority, current, issuer, _ = parts
    reserve_managed(parts)
    if failure == "environment":
        denied_request = RequestKey("other-environment", request.principal_scope, request.request_id)
        expected = IdentityMismatchError
    elif failure == "principal":
        denied_request = RequestKey(request.environment_namespace, "other-principal", request.request_id)
        expected = AdmissionRefusedError
    else:
        denied_request = request
        expected = AdmissionRefusedError
        monkeypatch.setattr(policy, "admit_invoke", lambda *args: False)

    operation_reads = []
    original_read_operation = store.read_operation

    def count_operation_reads(*args, **kwargs):
        operation_reads.append((args, kwargs))
        return original_read_operation(*args, **kwargs)

    monkeypatch.setattr(store, "read_operation", count_operation_reads)
    issuer_count_before = len(issuer._issued)
    authority_calls_before = authority.revalidate_calls
    current_reads_before = current.inspect_calls
    native_reads_before = native.calls
    with pytest.raises(expected):
        inputs.claim_dispatch(denied_request, issuer)

    assert operation_reads == []
    assert len(issuer._issued) == issuer_count_before
    assert authority.revalidate_calls == authority_calls_before
    assert current.inspect_calls == current_reads_before
    assert native.calls == native_reads_before
    assert store.read_operation_step(request, "native-input") is None
    assert native.dispatch_calls == 0

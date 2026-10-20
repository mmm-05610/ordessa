"""Focused receiving checks for original Work/Unit owner wiring.

The native-query case uses only the controlled local owner fixture and its
in-process provider. It makes no model or external provider call.
"""
from dataclasses import replace
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.common.models.identity import Scope
from ordessa_infrastructure.identifiers import RequestKey
from ordessa_server.composition.engineering_work_assembly import (
    admitted_dispatch_query_factory,
    original_dispatch_query_factory,
    original_submission_author_unit_resolver,
)
from ordessa_units.assembly import LocalUnitOwner
from ordessa_system_access_bindings.engineering import EngineeringCommandAccess
from test_selected_unit_shutdown import _build_selected_runtime

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "packages/execution/units/tests"))
from test_local_owner import live_owner


def _dispatch_binding(world, unit_ref, operation_ref, prompt_input_digest, *, scope=None):
    from ordessa_engineering.application.api import BlobRef, DispatchBinding
    from ordessa_engineering.domain.approvals.refs import ApprovalRef
    from ordessa_engineering.domain.common.models.identity import Scope as EngineeringScope
    from ordessa_engineering.domain.common.models.values import Digest
    from ordessa_engineering.domain.packages.refs import ImplementationPackageRef
    from ordessa_infrastructure.encoding import canonical_bytes

    unit_ref = json.loads(json.dumps(unit_ref, default=dict))
    input_digest = Digest("sha256", prompt_input_digest.removeprefix("sha256:"))
    query_digest = world.records.acp_turn_query_digest(
        unit_ref, operation_ref, prompt_input_digest)
    scope = scope or EngineeringScope("realm", "project")
    return DispatchBinding(
        scope=scope,
        run_id="run-native-query",
        step_id="dispatch-native-query",
        attempt=1,
        fence=1,
        package_ref=ImplementationPackageRef(
            scope.realm_id, scope.project_id, "selected-package", Digest("sha256", "a" * 64)),
        approval_ref=ApprovalRef(
            scope.realm_id, scope.project_id, "selected-approval", Digest("sha256", "b" * 64)),
        intent_digest=Digest("sha256", "c" * 64),
        control_version=1,
        action_instances=(("edit_repository", "edit-selected-source"),),
        unit_ref_bytes=canonical_bytes(unit_ref),
        execution_operation_ref=operation_ref,
        prompt_ref=BlobRef(input_digest, 1, "application/octet-stream", "query-prompt"),
        prompt_input_digest=input_digest,
        expected_query_digest=query_digest,
        required_results=("source-review",),
    )


@pytest.mark.parametrize("live_owner", [{"acp_turn_opt_in": True}], indirect=True)
def test_original_dispatch_query_factory_issues_real_cold_read_for_exact_binding(live_owner):
    from ordessa_infrastructure.identifiers import RequestKey

    world = live_owner
    authorization = world.owner.authorization()
    unit = world.public_manager.create(world.owner.spec, authorization)
    unit_ref = dict(unit.identity)
    instance = world.original_manager.find(unit_ref)
    lease = world.owner.authorize("interaction", unit, authorization)
    operation_ref = "native-query-original-operation"
    original = instance.prompt(
        unit_ref, lease, operation_ref=operation_ref, timeout=5,
        prompt=[{"type": "text", "text": "controlled recorded receipt"}],
    )
    assert original["state"] == "completed"
    assert unit.close(authorization)["state"] == "confirmed"

    binding = _dispatch_binding(world, unit_ref, operation_ref, original["inputDigest"])
    request = RequestKey(
        world.owner.admission.environment_namespace,
        world.owner.permission.principal_scope,
        "native-query-controlled-request",
    )
    supplied = []
    query = original_dispatch_query_factory(
        world.owner, records=world.records,
        request_factory=lambda actual_binding: supplied.append(actual_binding) or request,
    )
    invocation = query(binding)
    assert supplied == [binding]
    assert world.owner.records is world.records
    assert invocation.facts["inputDigest"] == world.records.acp_turn_query_digest(
        unit_ref, operation_ref, original["inputDigest"])
    query_digest = world.records.acp_turn_query_digest(
        unit_ref, operation_ref, original["inputDigest"])
    receipt = world.records.query_acp_turn(
        unit_ref, operation_ref, invocation,
        input_digest=query_digest,
        expected_prompt_input_digest=original["inputDigest"],
    )
    assert receipt == original
    assert world.environment.snapshot.active_uses == 0


@pytest.mark.parametrize("live_owner", [{"acp_turn_opt_in": True}], indirect=True)
def test_original_dispatch_query_factory_refuses_stale_expected_digest_before_owner_issue(live_owner):
    from ordessa_engineering.application.api import ApplicationError
    from ordessa_infrastructure.identifiers import RequestKey

    world = live_owner
    authorization = world.owner.authorization()
    unit = world.public_manager.create(world.owner.spec, authorization)
    unit_ref = dict(unit.identity)
    instance = world.original_manager.find(unit_ref)
    lease = world.owner.authorize("interaction", unit, authorization)
    operation_ref = "native-query-stale-digest"
    original = instance.prompt(
        unit_ref, lease, operation_ref=operation_ref, timeout=5,
        prompt=[{"type": "text", "text": "controlled recorded receipt"}],
    )
    assert original["state"] == "completed"
    assert unit.close(authorization)["state"] == "confirmed"
    binding = _dispatch_binding(world, unit_ref, operation_ref, original["inputDigest"])
    stale = replace(binding, expected_query_digest="sha256:" + "d" * 64)
    request = RequestKey("env", world.permission.principal_scope, "native-query-stale-request")
    query = original_dispatch_query_factory(
        world.owner, records=world.records, request_factory=lambda _binding: request)
    with pytest.raises(ApplicationError, match="WORK_NATIVE_BINDING_MISMATCH"):
        query(stale)
    assert world.store.read_operation(request) is None
    assert world.environment.snapshot.active_uses == 0


@pytest.mark.parametrize("live_owner", [{"acp_turn_opt_in": True}], indirect=True)
def test_original_dispatch_query_factory_refuses_foreign_incoming_request_before_reserve(live_owner):
    from ordessa_engineering.application.api import ApplicationError
    from ordessa_infrastructure.identifiers import RequestKey

    world = live_owner
    authorization = world.owner.authorization()
    unit = world.public_manager.create(world.owner.spec, authorization)
    unit_ref = dict(unit.identity)
    instance = world.original_manager.find(unit_ref)
    lease = world.owner.authorize("interaction", unit, authorization)
    operation_ref = "native-query-foreign-request"
    original = instance.prompt(
        unit_ref, lease, operation_ref=operation_ref, timeout=5,
        prompt=[{"type": "text", "text": "controlled recorded receipt"}],
    )
    assert original["state"] == "completed"
    assert unit.close(authorization)["state"] == "confirmed"
    binding = _dispatch_binding(world, unit_ref, operation_ref, original["inputDigest"])
    foreign = RequestKey("foreign-env", world.permission.principal_scope, "foreign-query-request")
    query = original_dispatch_query_factory(
        world.owner, records=world.records, request_factory=lambda _binding: foreign)
    with pytest.raises(ApplicationError, match="WORK_NATIVE_BINDING_INVALID"):
        query(binding)
    assert world.store.read_operation(foreign) is None
    assert world.environment.snapshot.active_uses == 0


@pytest.mark.parametrize("live_owner", [{
    "acp_turn_opt_in": True,
}], indirect=True)
def test_admitted_dispatch_query_uses_exact_current_request_and_original_unit(live_owner, monkeypatch):
    from ordessa_engineering.application.api import ApplicationError
    from ordessa_engineering.domain.common.models.identity import Scope as EngineeringScope

    world = live_owner
    unit = world.public_manager.create(world.owner.spec, world.owner.authorization())
    unit_ref = dict(unit.identity)
    instance = world.original_manager.find(unit_ref)
    lease = world.owner.authorize("interaction", unit, world.owner.authorization())
    operation_ref = "admitted-query-selected-operation"
    original = instance.prompt(
        unit_ref, lease, operation_ref=operation_ref, timeout=5,
        prompt=[{"type": "text", "text": "admitted exact request"}],
    )
    assert original["state"] == "completed"
    assert unit.close(world.owner.authorization())["state"] == "confirmed"
    selected_scope = EngineeringScope(world.scope.realm_id, world.scope.project_id)
    binding = _dispatch_binding(world, unit_ref, operation_ref,
        original["inputDigest"], scope=selected_scope)

    actual_calls = []
    original_authorize = type(world.owner).authorize_acp_turn_query

    def observe_authorize(authorization, request, actual_ref, actual_operation,
                          *, expected_prompt_input_digest):
        actual_calls.append((authorization, request, actual_ref, actual_operation))
        return original_authorize(world.owner, authorization, request, actual_ref,
            actual_operation,
            expected_prompt_input_digest=expected_prompt_input_digest)

    monkeypatch.setattr(type(world.owner), "authorize_acp_turn_query",
        lambda owner, *args, **kwargs: observe_authorize(*args, **kwargs)
            if owner is world.owner else original_authorize(owner, *args, **kwargs))
    access = EngineeringCommandAccess(world.owner.permission.access_authority)
    query = admitted_dispatch_query_factory(world.owner, access, records=world.records)
    with access.admit(world.principal, world.scope,
            "execution.units.interaction", request_id="incoming-request-82",
            trace_id="incoming-trace-82"):
        invocation = query(binding)
    assert len(actual_calls) == 1
    authorization, request, actual_ref, actual_operation = actual_calls[0]
    assert authorization is world.owner.authorization()
    assert request.environment_namespace == world.owner.admission.environment_namespace
    assert request.principal_scope == world.owner.permission.principal_scope
    assert request.request_id == "incoming-request-82"
    assert actual_ref == unit_ref
    assert actual_operation == operation_ref
    assert invocation.facts["inputDigest"] == world.records.acp_turn_query_digest(
        unit_ref, operation_ref, original["inputDigest"])
    foreign_scope_binding = _dispatch_binding(world, unit_ref, operation_ref,
        original["inputDigest"], scope=EngineeringScope(
            "foreign-realm", world.scope.project_id))
    with access.admit(world.principal, world.scope,
            "execution.units.interaction", request_id="incoming-request-83",
            trace_id="incoming-trace-83"):
        with pytest.raises(ApplicationError, match="WORK_NATIVE_BINDING_MISMATCH"):
            query(foreign_scope_binding)
    with pytest.raises(ApplicationError, match="ACCESS_AUTHORITY_UNAVAILABLE"):
        query(binding)
    assert len(actual_calls) == 1
    assert world.environment.snapshot.active_uses == 0


def test_native_query_producer_refuses_original_owner_without_acp_opt_in(tmp_path):
    runtime, _instance = _build_selected_runtime(tmp_path)
    try:
        owner = runtime.unit_execution_owner
        assert type(owner) is LocalUnitOwner
        assert owner.admission is runtime.unit_runtime.context
        with pytest.raises(ApplicationError, match="WORK_NATIVE_SOURCE_UNAVAILABLE"):
            original_dispatch_query_factory(
                owner, request_factory=lambda _binding: RequestKey(
                    owner.admission.environment_namespace,
                    owner.permission.principal_scope, "native-query"))
    finally:
        runtime.stop()


def test_submission_author_resolver_refuses_proposal_source_review(tmp_path):
    runtime, _instance = _build_selected_runtime(tmp_path)
    try:
        owner = runtime.unit_execution_owner
        assert type(owner) is LocalUnitOwner
        scope = Scope("realm", "project")
        factory = object()
        resolver = original_submission_author_unit_resolver(
            factory, owner, SimpleNamespace(kind="submission"),
            review_bindings=SimpleNamespace(factory=factory,
                resolve_review_submission=lambda *_args: None),
            unit_query_factory=lambda *_args, **_kwargs: None)
        context = SimpleNamespace(scope=scope)
        plan = SimpleNamespace(scope=scope,
            requirement=SimpleNamespace(scope=scope, purpose="source_review"))
        with pytest.raises(ApplicationError,
                match="UNIT_REVIEW_AUTHOR_BINDING_UNAVAILABLE"):
            resolver(context, plan)
    finally:
        runtime.stop()

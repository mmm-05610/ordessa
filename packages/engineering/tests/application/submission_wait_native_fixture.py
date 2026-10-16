"""Persist a test-only historical MethodRun/dispatch binding on original SQLite.

This helper records synthetic native identities and a completed dispatch row;
it does not authorize a real native action or patch package/dispatch resolvers.
The business-graph fixture supplies the actual typed Submission and Grant.
"""
from __future__ import annotations

from dataclasses import asdict
import hashlib

from ordessa_infrastructure.encoding import canonical_bytes

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.method_work import WORK_CONTRACT
from ordessa_engineering.application.contracts.operation_registry import registry_ref
from ordessa_engineering.application.orchestration.dispatch_method_run import (
    resolve_historical_method_run_package,
)
from ordessa_engineering.domain.changes.dispatch import DispatchBinding
from ordessa_engineering.domain.artifacts.method_binding import MethodRef
from ordessa_engineering.domain.changes.dispatch_codec import decode_dispatch, encode_dispatch
from ordessa_engineering.domain.common.models.refs import BlobRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.methods.compilation.encoding import program_plan_digest
from ordessa_engineering.methods.definitions.models.compiled import OperationNode, thaw_value


def persist_historical_dispatch(
    env,
    *,
    snapshot,
    package,
    grant,
    submission_execution_ref,
    unit_ref,
    prompt_ref,
    prompt_digest,
    query_digest,
):
    """Persist original run/material/dispatch rows correlated to the Submission.

    The supplied ``unit_ref``, prompt, and completed receipt are fixture facts,
    not evidence that a production execution owner authenticated or performed
    the action. The package slot, method snapshot, dispatch row, and Submission
    linkage are resolved through the normal original SQLite readers.
    """
    factory = env["factory"]
    scope = package.scope
    run_id = env.get("run_id", "submission-review-history")
    now = env.get("created_at", "2026-10-12T12:00:00.000000Z")
    if getattr(factory, "library", None) is None or snapshot is None:
        raise ApplicationError("TEST_FIXTURE_INPUT_INVALID")
    if (type(unit_ref) is not dict
            or set(unit_ref) != {"environmentNamespace", "unitId", "ownerProviderRef", "sourceRevision"}
            or unit_ref["environmentNamespace"] != submission_execution_ref.environment_namespace
            or unit_ref["unitId"] != submission_execution_ref.unit_id
            or unit_ref["sourceRevision"] != submission_execution_ref.source_revision
            or canonical_bytes(unit_ref["ownerProviderRef"])
            != submission_execution_ref.owner_provider_ref_bytes
            or prompt_digest != submission_execution_ref.prompt_input_digest
            or type(prompt_ref) is not BlobRef or type(query_digest) is not str):
        raise ApplicationError("TEST_FIXTURE_EXECUTION_BINDING_MISMATCH")

    method_ref = MethodRef(
        snapshot.ref.method_id, snapshot.ref.release_version,
        snapshot.ref.schema_version, Digest("sha256", snapshot.ref.snapshot_digest),
    )
    if package.payload.method_ref != method_ref or grant.ref.realm_id != scope.realm_id or grant.ref.project_id != scope.project_id:
        raise ApplicationError("TEST_FIXTURE_METHOD_BINDING_MISMATCH")
    steps = tuple(
        node for node in snapshot.program.workflow.steps
        if type(node) is OperationNode
        and node.operation in {"engineering.executions.dispatch", "engineering.implementation.dispatch"}
    )
    if not steps:
        raise ApplicationError("TEST_FIXTURE_DISPATCH_NODE_MISSING")
    configured = []
    for node in steps:
        config = {} if node.config is None else thaw_value(node.config)
        slot = config.get("package_slot") if type(config) is dict else None
        if type(slot) is str and slot in (snapshot.program.workflow.context_slots or ()):
            configured.append((node, slot))
    if len(configured) != 1:
        raise ApplicationError("TEST_FIXTURE_DISPATCH_NODE_AMBIGUOUS")
    node, package_slot = configured[0]
    method_value = asdict(method_ref)
    marker = {
        "work_contract": WORK_CONTRACT,
        "scope": asdict(scope),
        "method_ref": method_value,
        "compiled_plan_digest": program_plan_digest(snapshot.program),
    }
    inputs = {**marker, "slots": {package_slot: asdict(package.ref)}}
    if snapshot.program.workflow.loops:
        inputs["rounds"] = {
            loop.loop_id: 1 for loop in snapshot.program.workflow.loops
        }
    binding = DispatchBinding(
        scope=scope,
        run_id=run_id,
        step_id=node.id,
        attempt=1,
        fence=1,
        package_ref=package.ref,
        approval_ref=grant.ref,
        intent_digest=grant.intent.digest,
        control_version=0,
        action_instances=((
            next(action for action in grant.intent.actions
                 if action not in {"accept_artifact", "apply_change", "generate_package"}),
            f"{run_id}-action",
        ),),
        unit_ref_bytes=canonical_bytes(unit_ref),
        execution_operation_ref=submission_execution_ref.operation_ref,
        prompt_ref=prompt_ref,
        prompt_input_digest=prompt_digest,
        expected_query_digest=query_digest,
        required_results=("fixture-result",),
    )
    binding_bytes = encode_dispatch(binding)
    binding_digest = Digest("sha256", hashlib.sha256(binding_bytes).hexdigest())
    with factory.begin(scope) as uow:
        # Exact immutable package insertion is idempotent in the original repo.
        uow.implementation.create_package(package)
        method_material = uow.workflow.write_material(
            kind="method", stable_id=f"compiled-work:{run_id}", revision=1,
            body=marker, generated=False,
        )
        registry = env.get("registry")
        registry_value = registry() if callable(registry) else registry
        if registry_value is None:
            # The historical package resolver does not consult the active
            # registry; this shape remains a test-only stored run fact.
            registry_value = {"registry_id": "fixture-method-registry", "revision": 1,
                              "registry_digest": "sha256:" + "0" * 64, "operations": {}}
        uow.workflow.insert_run(
            run_id=run_id,
            method_ref=method_material,
            registry_ref=registry_ref(registry_value),
            inputs=inputs,
            now=now,
        )
        cursor = next(i for i, item in enumerate(snapshot.program.workflow.steps) if item.id == node.id)
        uow.workflow.update_run(run_id=run_id, status="RUNNING", cursor=cursor,
                                wait_reason=None, now=now)
        uow.dispatch.reserve(
            run_id, node.id, 1, scope, binding_bytes, binding_digest,
            submission_execution_ref.operation_ref,
        )
        uow.dispatch.transition(run_id, node.id, 1, scope, expected_version=0,
                                 fence=1, phase="possibly_written")
        uow.dispatch.transition(
            run_id, node.id, 1, scope, expected_version=1, fence=1,
            phase="completed", result_blob_ref=submission_execution_ref.captured_observation_ref,
        )
        uow.commit()

    # Exercise the exact normal historical resolver against what was written.
    with factory.begin(scope, "read") as uow:
        resolved = resolve_historical_method_run_package(uow, run_id, step_id=node.id)
        if resolved != package:
            raise ApplicationError("TEST_FIXTURE_HISTORICAL_PACKAGE_MISMATCH")
        row = uow.dispatch.by_operation(submission_execution_ref.operation_ref, scope)
        if row["dispatch_phase"] != "completed" or row["dispatch_fence"] != 1:
            raise ApplicationError("TEST_FIXTURE_DISPATCH_NOT_COMPLETED")
        if decode_dispatch(row["binding_bytes"]) != binding:
            raise ApplicationError("TEST_FIXTURE_DISPATCH_BINDING_MISMATCH")
    return {
        "run_id": run_id,
        "step_id": node.id,
        "attempt": 1,
        "binding": binding,
        "marker_ref": method_material,
        "synthetic_native_facts": True,
    }


__all__ = ["persist_historical_dispatch"]

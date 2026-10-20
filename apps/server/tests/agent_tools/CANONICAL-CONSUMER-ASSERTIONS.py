"""Deferred canonical Server-dispatch acceptance assertions.

This is an integration acceptance driver, not a pytest green-path fixture. It
requires the exact live owners and persisted values from a real formal Work
producer. It must remain NOT_EXECUTED until those inputs exist.
"""


async def assert_canonical_dispatch_semantics(
    *, wire_binding, caller, first_request, read_request, duplicate_request, retired_request,
    dispatch_binding, first_result, persisted_dispatch, send_count_before,
    native_send_counter,
    prepared_submission, expected_submission_ref, submission_count,
    blobs, actual_unit, authorization, selected_manager, selected_environment,
):
    """Exercise canonical dispatch/readback/refusal and original Unit release.

    Every argument is an actual object/value from the selected product and
    persisted Work attempt after the first canonical caller invocation. The
    duplicate/retired request envelopes use the same selected scope and fresh
    real request IDs. ``native_send_counter`` and ``submission_count`` are
    read-only observations owned by the integration caller, not mocked effects.
    """
    from ordessa_engineering.application.api import (
        BlobRef, DispatchBinding, EXECUTION_DISPATCH,
    )
    from ordessa_engineering.domain.changes.dispatch_codec import decode_dispatch
    from ordessa_engineering.domain.changes.submission import Submission
    from ordessa_infrastructure.encoding import canonical_bytes, decode_json
    from ordessa_engineering.domain.common.models.values import Digest
    from ordessa_system_access_bindings.engineering_wire import EngineeringWireBinding
    from ordessa_units.api.unit import Unit

    assert type(wire_binding) is EngineeringWireBinding
    assert wire_binding.execution_dispatch is not None
    assert any(item.capability_id == EXECUTION_DISPATCH
               for item in wire_binding.service.bound_operation_capabilities().capabilities)
    assert caller is not None
    assert type(dispatch_binding) is DispatchBinding
    assert type(prepared_submission) is Submission
    assert prepared_submission.ref == expected_submission_ref
    assert callable(native_send_counter) and callable(submission_count)
    assert first_request["scope"] == read_request["scope"] == duplicate_request["scope"] == retired_request["scope"]
    assert first_request["parameters"] == duplicate_request["parameters"]
    assert first_request["requestId"] != duplicate_request["requestId"]
    assert read_request["parameters"] == {
        "run_id": dispatch_binding.run_id,
        "step_id": dispatch_binding.step_id,
        "attempt": dispatch_binding.attempt,
    }
    assert len({first_request["requestId"], read_request["requestId"],
                duplicate_request["requestId"], retired_request["requestId"]}) == 4
    assert type(actual_unit) is Unit and authorization is not None
    assert callable(getattr(selected_manager, "get", None))
    assert callable(getattr(blobs, "read_verified", None))

    selected_unit_ref = decode_json(dispatch_binding.unit_ref_bytes)
    assert canonical_bytes(actual_unit.identity) == dispatch_binding.unit_ref_bytes
    assert canonical_bytes(selected_manager.get(selected_unit_ref).identity) == dispatch_binding.unit_ref_bytes
    assert prepared_submission.scope == dispatch_binding.scope
    assert prepared_submission.package_ref == dispatch_binding.package_ref
    assert prepared_submission.authorization_refs == (dispatch_binding.approval_ref,)
    execution_ref = prepared_submission.execution_ref
    assert execution_ref.operation_ref == dispatch_binding.execution_operation_ref
    assert execution_ref.environment_namespace == selected_unit_ref["environmentNamespace"]
    assert execution_ref.unit_id == selected_unit_ref["unitId"]
    assert decode_json(execution_ref.owner_provider_ref_bytes) == selected_unit_ref["ownerProviderRef"]
    assert execution_ref.source_revision == selected_unit_ref["sourceRevision"]
    assert execution_ref.prompt_input_digest == dispatch_binding.prompt_input_digest

    assert type(send_count_before) is int
    after_first = native_send_counter()
    assert type(after_first) is int and after_first == send_count_before + 1
    first = first_result
    assert first["record_type"] == "owner_operation_result"
    assert first["operation"] == EXECUTION_DISPATCH
    assert first["outcome"] == "completed"
    assert first["dispatch_phase"] == "completed"
    assert first["engineering_completed"] is False
    assert first["accepted"] is False
    assert canonical_bytes(first["value"]["binding"]) == canonical_bytes(dispatch_binding.projection())
    assert first["value"]["binding"]["execution_operation_ref"] == dispatch_binding.execution_operation_ref
    observation = first["value"]["observation_ref"]
    assert observation is not None
    observation_ref = BlobRef(
        digest=Digest(**observation["digest"]),
        byte_length=observation["byte_length"], media_type=observation["media_type"],
        storage_object_id=observation["storage_object_id"],
    )
    verified_observation = blobs.read_verified(observation_ref)
    assert type(verified_observation) is bytes

    row_binding = decode_dispatch(persisted_dispatch["binding_bytes"])
    assert row_binding == dispatch_binding
    assert (persisted_dispatch["run_id"], persisted_dispatch["step_id"],
            persisted_dispatch["attempt"]) == (
                dispatch_binding.run_id, dispatch_binding.step_id, dispatch_binding.attempt)
    assert persisted_dispatch["dispatch_phase"] == "completed"
    assert decode_json(persisted_dispatch["result_blob_json"].encode("utf-8")) == observation
    assert prepared_submission.execution_ref.captured_observation_ref == observation_ref

    before_read = native_send_counter()
    readback = await wire_binding.invoke(
        "engineering.implementation.get_dispatch", read_request, caller)
    assert native_send_counter() == before_read
    assert readback["record_type"] == "implementation_dispatch"
    assert readback["query"] == "engineering.implementation.get_dispatch"
    read_data = readback["data"]
    assert read_data["phase"] == "completed"
    assert read_data["accepted"] is False
    assert read_data["engineering_completed"] is False
    assert canonical_bytes(read_data["binding"]) == canonical_bytes(dispatch_binding.projection())
    assert read_data["binding"]["execution_operation_ref"] == dispatch_binding.execution_operation_ref
    assert read_data["result_blob_ref"] == observation

    before_duplicate = native_send_counter()
    duplicate = await wire_binding.invoke(EXECUTION_DISPATCH, duplicate_request, caller)
    assert native_send_counter() == before_duplicate
    assert duplicate["record_type"] == "owner_operation_result"
    assert duplicate["operation"] == EXECUTION_DISPATCH
    assert canonical_bytes(duplicate["value"]["binding"]) == canonical_bytes(dispatch_binding.projection())
    assert duplicate["value"]["binding"]["execution_operation_ref"] == dispatch_binding.execution_operation_ref
    assert duplicate["dispatch_phase"] == "completed"
    assert duplicate["accepted"] is False

    # A Submission is only prepared by the calling workflow here. The retired
    # direct recording operation must still refuse and leave the table empty.
    assert submission_count() == 0
    from server_plugin_api.wire_errors import WireError
    try:
        await wire_binding.invoke("engineering.submissions.record", retired_request, caller)
    except WireError as error:
        assert error.family == "CAPABILITY_UNSUPPORTED"
        assert error.details.get("internalCode") == "OPERATION_UNAVAILABLE"
    else:
        raise AssertionError("retired Submission recording operation was accepted")
    assert submission_count() == 0

    active_uses_before_close = selected_environment.snapshot.active_uses
    assert active_uses_before_close > 0
    close_result = actual_unit.close(authorization)
    assert close_result["state"] == "confirmed"
    assert selected_environment.snapshot.active_uses == 0
    assert native_send_counter() == after_first
    return first, duplicate, close_result

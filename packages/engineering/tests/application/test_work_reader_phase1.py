"""Actual SQLite reader coverage for candidate schema-v2 Work inputs.

The fixture uses the original Engineering library, method snapshot store,
Proposal, and artifact revision repository. It does not qualify a production
run or review-admission authority.
"""
from dataclasses import asdict
from urllib.parse import urljoin

import pytest

from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
from ordessa_engineering.adapters.method_work import (
    SQLitePersistedMethodWorkSource,
    selected_wait_input_event,
)
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.adapters.persistence.sqlite.work_review_bindings import SQLiteWorkReviewBindings
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.orchestration.method_content import document_spec
from ordessa_engineering.application.orchestration.method_runs import observed_loop_round
from ordessa_engineering.application.usecases.material_closure import verify_material
from ordessa_engineering.application.usecases.publish_snapshot import freeze_method
from ordessa_engineering.domain.artifacts.method_binding import ExactMethodResourceRef, MethodRef
from ordessa_engineering.domain.artifacts.models import Artifact, ArtifactRevision, MethodContent, MethodPayload
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.methods import compile_method, load_method
from ordessa_engineering.methods.definitions.models import MethodSource, thaw_value

from test_persisted_method_work import (
    CANDIDATE,
    HostFixtureCatalog,
    _host_fixture_capabilities,
    persisted_source,
)


def _freeze_candidate(e):
    loaded = load_method(MethodSource(CANDIDATE), reader=FileResourceReader())
    assert loaded.ok and loaded.value is not None, loaded.error
    capabilities = _host_fixture_capabilities()
    compiled = compile_method(loaded.value, capabilities, "fixture:phase1-round-reader")
    assert compiled.ok and compiled.value is not None, compiled.error
    frozen = freeze_method(compiled.value, e["store"], e["store"],
        capability_catalog=HostFixtureCatalog(capabilities))
    assert frozen.ok and frozen.value is not None, frozen.error
    ref = frozen.value.ref
    method_ref = MethodRef(ref.method_id, ref.release_version, ref.schema_version,
                           Digest("sha256", ref.snapshot_digest))
    return method_ref, e["controls"].read_snapshot(method_ref)


def _append_v2_input(e, snapshot, method_ref, value, revision_id, parents=()):
    spec = document_spec(snapshot, "work-inputs")
    resource = next(item for item in snapshot.resources
                    if item.resource_id == spec.schema_ref.resource_id)
    exact = ExactMethodResourceRef(method_ref, resource.logical_path,
        Digest("sha256", resource.digest), resource.resource_id)
    schema = thaw_value(spec.value_schema)
    schema_id = urljoin("https://ordessa.invalid/method/" + exact.logical_path,
                        schema.get("$id", ""))
    payload = MethodPayload("application/json", schema_id,
                            MethodContent.from_value(exact, value))
    revision = ArtifactRevision(e["input_revision"].scope, "phase1-round-inputs",
        revision_id, e["input_revision"].created_at, e["input_revision"].created_by,
        payload, parent_revision_refs=tuple(parents), schema_version=2,
        method_refs=(method_ref,))
    with e["factory"].begin(revision.scope) as uow:
        try:
            artifact = uow.engineering.get_artifact(revision.artifact_id)
            expected_version = artifact.version
        except ApplicationError as exc:
            if exc.code != "NOT_FOUND":
                raise
            uow.engineering.create(Artifact(revision.scope, revision.artifact_id,
                                            "plan", revision.created_at))
            expected_version = 0
        verify_material(revision, uow.engineering.validated_budget())
        uow.engineering.append_revision(revision, expected_version=expected_version)
        uow.commit()
    return revision


def test_sqlite_work_reader_selects_current_round_and_guards_append_prefix(persisted_source):
    e = persisted_source
    method_ref, snapshot = _freeze_candidate(e)
    reader = SQLiteWorkReviewBindings(e["factory"], e["controls"],
        scope=e["input_revision"].scope, blobs=SQLiteBlobStore(e["library"]))
    policy = reader._policy(snapshot)
    source = SQLitePersistedMethodWorkSource(e["factory"], e["controls"])
    spec = document_spec(snapshot, "work-inputs")
    round_waits = tuple(wait_id for wait_id, declaration in policy["waits"].items()
                        if declaration.get("event_map") == "events_by_round")
    field_options = thaw_value(spec.value_schema)["properties"]["events_by_round"][
        "additionalProperties"]["properties"]
    loop_ids = {loop.loop_id for loop in snapshot.program.workflow.loops or ()}
    rounds = {loop_id: 2 for loop_id in loop_ids}
    work_row = {"inputs": {"rounds": rounds}}
    usable_waits = []
    for candidate_wait in round_waits:
        try:
            observation = observed_loop_round(snapshot.program, work_row, candidate_wait)
        except ApplicationError:
            continue
        event_fields = tuple(field for field, shape in
            field_options[candidate_wait]["properties"].items()
            if shape.get("$ref") == "#/$defs/event_value")
        if observation is not None and len(event_fields) >= 2:
            usable_waits.append((candidate_wait, event_fields))
    assert usable_waits, "candidate has no unambiguous loop wait with appendable event fields"
    wait_id, fields = usable_waits[0]
    first_field, second_field = fields[:2]

    value = {
        "document_type": "work-inputs", "schema_version": 2,
        "run_id": "work-source-run", "proposal_ref": asdict(e["proposal_ref"]),
        "events": {},
        "events_by_round": {
            "1": {wait_id: {first_field: "old-round-value"}},
            "2": {wait_id: {first_field: "current-round-value"}},
        },
    }
    original = _append_v2_input(e, snapshot, method_ref, value, "round-input-r1")
    slots = {"proposal_ref": asdict(e["proposal_ref"]),
             "work_inputs": asdict(original.ref)}
    row = {"run_id": "work-source-run", "inputs": {"slots": slots, "rounds": rounds}}
    with e["factory"].begin(e["input_revision"].scope, "read") as uow:
        _, _, loaded_value, proposal_ref = reader._work_values(
            uow, snapshot, row, original.ref)
    assert proposal_ref == e["proposal_ref"]
    assert observed_loop_round(snapshot.program, work_row, wait_id)[1] == 2
    selected = selected_wait_input_event(policy, loaded_value, wait_id,
                                         work_row, snapshot.program)
    assert selected[first_field] == "current-round-value"
    assert selected[first_field] != loaded_value["events_by_round"]["1"][wait_id][first_field]

    extended_value = {
        **value,
        "events_by_round": {
            "1": {wait_id: {first_field: "old-round-value"}},
            "2": {wait_id: {first_field: "current-round-value",
                            second_field: "append-only-value"}},
        },
    }
    extended = _append_v2_input(e, snapshot, method_ref, extended_value,
        "round-input-r2", parents=(original.ref,))
    with e["factory"].begin(e["input_revision"].scope, "read") as uow:
        source._input_progression_in_uow(
            uow, snapshot, policy, original.ref, extended.ref,
            run_id="work-source-run")
        extended_row = {"run_id": "work-source-run", "inputs": {"slots": {
            **slots, "work_inputs": asdict(extended.ref)}, "rounds": rounds}}
        _, _, extended_value, _ = reader._work_values(
            uow, snapshot, extended_row, extended.ref)
    current_event = selected_wait_input_event(policy, extended_value, wait_id,
        extended_row, snapshot.program)
    assert current_event[second_field] == "append-only-value"

    rewritten_value = {
        **value,
        "events_by_round": {
            "1": {wait_id: {first_field: "rewritten-old-round"}},
            "2": {wait_id: {first_field: "current-round-value"}},
        },
    }
    rewritten = _append_v2_input(e, snapshot, method_ref, rewritten_value,
        "round-input-rewritten", parents=(original.ref,))
    with e["factory"].begin(e["input_revision"].scope, "read") as uow:
        with pytest.raises(ApplicationError, match="WORK_INPUT_EVENT_CHANGED"):
            source._input_progression_in_uow(
                uow, snapshot, policy, original.ref, rewritten.ref,
                run_id="work-source-run")

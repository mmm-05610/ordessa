"""SQLite-backed persisted Work source checks with a candidate-only method.

The candidate's fixture catalog is used only to freeze the source bytes for
these original-UoW adapter tests. This is not a production registry,
publication, reviewer, Grant, native execution, or model-call qualification.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from urllib.parse import urljoin

import pytest

from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
from ordessa_engineering.adapters.persistence.sqlite.engineering_library import EngineeringLibrary
from ordessa_engineering.adapters.persistence.sqlite.method_control import SQLiteMethodControl
from ordessa_engineering.adapters.persistence.sqlite.snapshot_store import SQLiteSnapshotStore
from ordessa_engineering.adapters.persistence.sqlite.unit_of_work import SQLiteUoWFactory
from ordessa_engineering.adapters.method_work import SQLitePersistedMethodWorkSource
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.orchestration.method_bridge import command_capabilities
from ordessa_engineering.application.orchestration.check_capabilities import (
    invariant_review_check_capabilities, mechanical_review_check_capabilities,
)
from ordessa_engineering.application.orchestration.decision_checks import generic_decision_check_capability
from ordessa_engineering.application.orchestration.owner_capabilities import owner_capabilities
from ordessa_engineering.application.orchestration.method_content import document_spec
from ordessa_engineering.application.usecases.material_closure import verify_material
from ordessa_engineering.application.usecases.publish_snapshot import freeze_method
from ordessa_engineering.application.usecases.support.methods import MethodUseCases
from ordessa_engineering.domain.artifacts.method_binding import ExactMethodResourceRef, MethodRef
from ordessa_engineering.domain.artifacts.models import Artifact, ArtifactRevision, MethodContent, MethodPayload
from ordessa_engineering.domain.artifacts.refs import ArtifactRevisionRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.common.models.identity import Scope
from ordessa_engineering.methods import compile_method, load_method
from ordessa_engineering.methods.definitions.models import CompilationCapabilities, MethodSource, thaw_value

from test_method_control_admission import TestManagement
from test_proposal_usecases import (
    ACTOR, CREATED_AT, LIBRARY_ID, SCOPE, SyntheticAccess, _artifact_graph,
    _create as create_proposal, _proposal_ref,
)
from test_review_usecases import _context


ROOT = Path(__file__).resolve().parents[4]
CANDIDATE = ROOT / "methods/incremental-engineering/candidates/2.6.0"


class HostFixtureCatalog:
    def __init__(self, capabilities):
        self.capabilities = capabilities

    def read_current(self):
        return self.capabilities


def _host_fixture_capabilities():
    dispatch = tuple(item for item in owner_capabilities()
                     if item.capability_id == "engineering.executions.dispatch")
    values = (
        *command_capabilities().capabilities,
        *dispatch,
        *mechanical_review_check_capabilities().capabilities,
        *invariant_review_check_capabilities().capabilities,
        generic_decision_check_capability(),
    )
    # Only the real current descriptors are reused. The trust label here is a
    # local test harness value required by freeze_method, not a registry claim.
    return CompilationCapabilities(values, "fixture:current-owner-descriptors", "host")


def _write_minimal_work_method(root):
    """Write a review-free method for testing generic persisted-source mechanics.

    This fixture intentionally does not claim the 2.6 candidate's five review
    phases or full proposal-template capture. That candidate is checked
    separately for all wait selectors below.
    """
    documents = CANDIDATE / "documents" / "work-inputs"
    target = root / "documents" / "work-inputs"
    target.mkdir(parents=True)
    schema = (documents / "schema.json").read_bytes()
    template = (documents / "template.md").read_bytes()
    (target / "schema.json").write_bytes(schema)
    (target / "template.md").write_bytes(template)
    workflow = {
        "schema_version": 1,
        "workflow_id": "persisted-work-source-test",
        "entry": "await_proposal",
        "resume_contract": "ordessa.engineering.current-work/1",
        "context_slots": ["method_ref", "proposal_ref", "work_inputs"],
        "steps": [
            {"id": "await_proposal", "kind": "wait",
             "event": "engineering.work.current_condition", "bind": {}, "next": "finished"},
            {"id": "finished", "kind": "stop", "outcome": "finished"},
        ],
        "stop_outcomes": ["finished"],
        "wait_kinds": [],
    }
    workflow_bytes = json.dumps(workflow, separators=(",", ":")).encode()
    (root / "workflow.json").write_bytes(workflow_bytes)
    resources = [
        {"id": "workflow.main", "kind": "workflow", "path": "workflow.json",
         "media_type": "application/yaml", "sha256": hashlib.sha256(workflow_bytes).hexdigest()},
        {"id": "document.work_inputs.schema", "kind": "document_schema",
         "path": "documents/work-inputs/schema.json", "media_type": "application/schema+json",
         "sha256": hashlib.sha256(schema).hexdigest()},
        {"id": "document.work_inputs.template", "kind": "document_template",
         "path": "documents/work-inputs/template.md", "media_type": "text/markdown",
         "sha256": hashlib.sha256(template).hexdigest()},
    ]
    manifest = {
        "schema_version": 1, "method_id": "test.persisted-work-source", "release_version": "1.0.0",
        "compiler_contract": "ordessa.methods/v1", "entry": {"resource": "workflow.main"},
        "documents": [{"document_type": "work-inputs", "schema": {"resource": "document.work_inputs.schema"},
                       "template": {"resource": "document.work_inputs.template"},
                       "validation_target": "method_content"}],
        "metadata": {"work_source": {
            "contract_version": "ordessa.persisted-work-source/1",
            "input_document_slot": "work_inputs", "input_document_type": "work-inputs",
            "waits": {"await_proposal": {"family": "object_exists", "refs": ["proposal_ref"],
                                            "event_slots": {}}},
        }},
        "resources": resources, "requires": [],
    }
    root.mkdir(parents=True, exist_ok=True)
    (root / "method.yaml").write_text(json.dumps(manifest, separators=(",", ":")), encoding="utf-8")


def _revision_for_input(factory, snapshot, method_ref, proposal_ref, *, revision_id,
                        events=None, parent_refs=()):
    spec = document_spec(snapshot, "work-inputs")
    resource = next(item for item in snapshot.resources
                    if item.resource_id == spec.schema_ref.resource_id)
    exact = ExactMethodResourceRef(
        method_ref, resource.logical_path, Digest("sha256", resource.digest), resource.resource_id)
    schema = thaw_value(spec.value_schema)
    schema_id = urljoin("https://ordessa.invalid/method/" + exact.logical_path, schema.get("$id", ""))
    value = {
        "document_type": "work-inputs", "schema_version": 1,
        "run_id": "work-source-run", "proposal_ref": asdict(proposal_ref),
        "events": {} if events is None else events,
    }
    payload = MethodPayload("application/json", schema_id, MethodContent.from_value(exact, value))
    revision = ArtifactRevision(
        SCOPE, "work-source-inputs", revision_id, CREATED_AT, ACTOR, payload,
        parent_revision_refs=parent_refs, schema_version=2, method_refs=(method_ref,))
    with factory.begin(SCOPE) as uow:
        try:
            artifact = uow.engineering.get_artifact("work-source-inputs")
            expected_version = artifact.version
        except ApplicationError as exc:
            if exc.code != "NOT_FOUND":
                raise
            uow.engineering.create(Artifact(SCOPE, "work-source-inputs", "plan", CREATED_AT))
            expected_version = 0
        verify_material(revision, uow.engineering.validated_budget())
        uow.engineering.append_revision(revision, expected_version=expected_version)
        uow.commit()
    return value, revision


@pytest.fixture
def persisted_source(tmp_path):
    path = (tmp_path / "engineering.sqlite").resolve()
    library = EngineeringLibrary.create(path, library_id=LIBRARY_ID, schema_version=14)
    factory = SQLiteUoWFactory(library)
    access = SyntheticAccess()
    store = SQLiteSnapshotStore(library)
    capabilities = _host_fixture_capabilities()
    method_source = tmp_path / "review-free-work-method"
    _write_minimal_work_method(method_source)
    loaded = load_method(MethodSource(method_source), reader=FileResourceReader())
    assert loaded.ok and loaded.value is not None, loaded.error
    compiled = compile_method(loaded.value, capabilities, "fixture:work-source")
    assert compiled.ok and compiled.value is not None, compiled.error
    frozen = freeze_method(compiled.value, store, store,
                           capability_catalog=HostFixtureCatalog(capabilities))
    assert frozen.ok and frozen.value is not None, frozen.error
    released = frozen.value.ref
    method_ref = MethodRef(released.method_id, released.release_version,
                           released.schema_version, Digest("sha256", released.snapshot_digest))
    management = MethodUseCases(factory, access, store, TestManagement())
    management.adopt(method_ref, _context(SCOPE, "select-candidate"), expected_version=0)
    controls = SQLiteMethodControl(factory, store)
    snapshot = controls.read_snapshot(method_ref)

    base_ref, proposed_ref, claim = _artifact_graph(factory)
    with factory.begin(SCOPE, "read") as uow:
        assert uow.engineering.get_artifact("artifact-1").scope == SCOPE
        assert uow.proposals.select_artifact(SCOPE, "artifact-1") is not None
    created = create_proposal(factory, access, method_ref, base_ref, proposed_ref,
                              claim, "work-source-proposal", template=False)
    assert created.status == "completed", created.result
    proposal_ref = _proposal_ref(created.result["proposal_ref"])
    input_value, input_revision = _revision_for_input(
        factory, snapshot, method_ref, proposal_ref, revision_id="inputs-r1")
    input_ref = input_revision.ref
    with factory.begin(SCOPE, "read") as uow:
        change = uow.proposals.get_change(proposal_ref.change_id)
        assert change.selected_proposal_id is None

    source = SQLitePersistedMethodWorkSource(factory, controls)
    try:
        yield {
            "path": path, "library": library, "factory": factory, "access": access,
            "store": store, "controls": controls, "snapshot": snapshot,
            "method_ref": method_ref, "proposal_ref": proposal_ref,
            "input_ref": input_ref, "input_value": input_value,
            "input_revision": input_revision, "source": source,
        }
    finally:
        library.close()


def _selection(e, *, input_ref=None, proposal_ref=None):
    return {
        "proposal_ref": asdict(proposal_ref or e["proposal_ref"]),
        "initial_slot_refs": {"work_inputs": asdict(input_ref or e["input_ref"])},
    }


def test_start_reads_exact_candidate_policy_and_original_proposal_without_global_selection(persisted_source):
    e = persisted_source
    with e["source"].guard_start(
            _context(SCOPE, "source-start"), e["snapshot"],
            run_id="work-source-run", selection=_selection(e)) as seed:
        assert seed.slots["proposal_ref"] == asdict(e["proposal_ref"])
        assert seed.slots["method_ref"] == asdict(e["method_ref"])
        assert seed.slots["work_inputs"] == asdict(e["input_ref"])
        assert {version.kind for version in seed.read_set.versions} >= {
            "proposal_control", "change", "artifact"}


def test_start_rejects_scope_and_schema_invalid_truth_claims(persisted_source, tmp_path):
    e = persisted_source
    wrong_scope = Scope("foreign-realm", SCOPE.project_id)
    wrong_proposal = type(e["proposal_ref"])(
        wrong_scope.realm_id, wrong_scope.project_id,
        e["proposal_ref"].change_id, e["proposal_ref"].proposal_id,
        e["proposal_ref"].digest)
    with pytest.raises(ApplicationError, match="SCOPE_MISMATCH"):
        with e["source"].guard_start(
                _context(SCOPE, "foreign-start"), e["snapshot"],
                run_id="work-source-run", selection=_selection(e, proposal_ref=wrong_proposal)):
            pass

    with pytest.raises(ApplicationError, match="METHOD_CONTENT_INVALID"):
        _revision_for_input(
            e["factory"], e["snapshot"], e["method_ref"], e["proposal_ref"],
            revision_id="inputs-invalid", events={"await_proposal": {"ready": True}})


def test_bind_inputs_selects_only_direct_child_revision(persisted_source):
    e = persisted_source
    _, next_revision = _revision_for_input(
        e["factory"], e["snapshot"], e["method_ref"], e["proposal_ref"],
        revision_id="inputs-r2", parent_refs=(e["input_ref"],))
    _, orphan_revision = _revision_for_input(
        e["factory"], e["snapshot"], e["method_ref"], e["proposal_ref"],
        revision_id="inputs-orphan")
    view = {
        "run_id": "work-source-run",
        "row": {
            "inputs": {"slots": {
                "proposal_ref": asdict(e["proposal_ref"]),
                "work_inputs": asdict(e["input_ref"]),
            }},
            "cursor": 0,
            "wait_reason": "await_proposal",
        },
    }
    with e["source"].guard_inputs(
            _context(SCOPE, "bind-inputs"), e["snapshot"], view,
            next_revision.ref) as seed:
        assert seed.slots == {"work_inputs": asdict(next_revision.ref)}
        assert any(version.kind == "artifact" for version in seed.read_set.versions)

    with pytest.raises(ApplicationError, match="WORK_INPUT_REVISION_NOT_APPENDED"):
        with e["source"].guard_inputs(
                _context(SCOPE, "bind-old-input"), e["snapshot"], view,
                orphan_revision.ref):
            pass


def test_condition_resolves_persisted_proposal_in_original_scope(persisted_source):
    e = persisted_source
    node = next(step for step in e["snapshot"].program.workflow.steps
                if step.id == "await_proposal")
    view = {
        "run_id": "work-source-run",
        "row_digest": Digest("sha256", "a" * 64),
        "next_step_ordinal": 0,
        "row": {"wait_reason": "await_proposal", "inputs": {"slots": {
            "proposal_ref": asdict(e["proposal_ref"]),
            "work_inputs": asdict(e["input_ref"]),
        }}},
    }
    with e["source"].guard_condition(
            _context(SCOPE, "persisted-condition"), e["snapshot"], node, view) as selection:
        assert selection.condition.family == "object_exists"
        assert selection.condition.run_id == "work-source-run"
        assert selection.event_values == {}


def test_start_reopens_original_library_and_resolves_same_exact_method_and_material(persisted_source):
    e = persisted_source
    e["library"].close()
    reopened = EngineeringLibrary.open(e["path"], library_id=LIBRARY_ID)
    e["library"] = reopened
    e["factory"] = SQLiteUoWFactory(reopened)
    e["store"] = SQLiteSnapshotStore(reopened)
    e["controls"] = SQLiteMethodControl(e["factory"], e["store"])
    e["snapshot"] = e["controls"].read_snapshot(e["method_ref"])
    e["source"] = SQLitePersistedMethodWorkSource(e["factory"], e["controls"])
    with e["source"].guard_start(
            _context(SCOPE, "reopened-start"), e["snapshot"],
            run_id="work-source-run", selection=_selection(e)) as seed:
        assert seed.slots["method_ref"] == asdict(e["method_ref"])
        assert seed.slots["proposal_ref"] == asdict(e["proposal_ref"])
        assert seed.slots["work_inputs"] == asdict(e["input_ref"])


def test_input_read_set_race_is_rechecked_by_original_uow(persisted_source):
    e = persisted_source
    second_library = EngineeringLibrary.open(e["path"], library_id=LIBRARY_ID)
    second_factory = SQLiteUoWFactory(second_library)
    original_guard = e["factory"].guard_read_set
    raced = False

    @contextmanager
    def race_after_source_read(reads):
        nonlocal raced
        if not raced:
            raced = True
            _revision_for_input(
                second_factory, e["snapshot"], e["method_ref"], e["proposal_ref"],
                revision_id="inputs-race", parent_refs=(e["input_ref"],))
        with original_guard(reads):
            yield

    e["factory"].guard_read_set = race_after_source_read
    try:
        with e["source"].guard_start(
                _context(SCOPE, "source-race"), e["snapshot"],
                run_id="work-source-run", selection=_selection(e)) as seed:
            assert seed.read_set.versions
            with pytest.raises(ApplicationError, match="READ_SET_CHANGED"):
                with e["factory"].begin(SCOPE, "read"):
                    pass
    finally:
        e["factory"].guard_read_set = original_guard
        second_library.close()


def test_candidate_work_source_has_exact_selectors_for_all_waits():
    loaded = load_method(MethodSource(CANDIDATE), reader=FileResourceReader())
    assert loaded.ok and loaded.value is not None, loaded.error
    import yaml
    raw = yaml.safe_load((CANDIDATE / "method.yaml").read_text(encoding="utf-8"))
    policy = raw["metadata"]["work_source"]
    wait_ids = {step["id"] for step in raw_workflow_steps(CANDIDATE)
                if step.get("kind") == "wait"}
    assert set(policy["waits"]) == wait_ids
    assert policy["waits"]["await_intent_ref"]["intent_result_slots"] == {
        "id": "intent_id", "digest": "intent_digest"}
    assert policy["waits"]["await_execution_capture"]["native_report_slot"] == "submission_record"


def raw_workflow_steps(root):
    import yaml
    method = yaml.safe_load((root / "method.yaml").read_text(encoding="utf-8"))
    entry_resource = next(item for item in method["resources"]
                          if item["id"] == method["entry"]["resource"])
    workflow = yaml.safe_load((root / entry_resource["path"]).read_text(encoding="utf-8"))
    return workflow["steps"]

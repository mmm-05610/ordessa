"""Method-declared dispatch task rendering over one original WorkRun.

The method/package/Work rows and immutable resources are real SQLite-backed
objects. WorkSource, ACP, and package material are controlled local fixture
peers; this does not qualify Grant admission, native execution, or a model call.
"""
from contextlib import contextmanager
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import runpy
from urllib.parse import urljoin

import pytest

from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
from ordessa_engineering.application.orchestration.dispatch_inputs import (
    MethodDispatchInputs, render_dispatch_task,
)
from ordessa_engineering.adapters.persistence.sqlite.blob_store import SQLiteBlobStore
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.method_work import WorkSeed
from ordessa_engineering.application.orchestration.method_bridge import command_capabilities
from ordessa_engineering.application.orchestration.owner_capabilities import owner_capabilities
from ordessa_engineering.application.usecases.material_closure import verify_material
from ordessa_engineering.application.usecases.publish_snapshot import freeze_method
from ordessa_engineering.domain.artifacts.method_binding import ExactMethodResourceRef, MethodRef
from ordessa_engineering.domain.artifacts.models import (
    Artifact, ArtifactRevision, MethodContent, MethodPayload,
)
from ordessa_engineering.domain.artifacts.refs import ArtifactRevisionRef
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.methods import compile_method, load_method
from ordessa_engineering.methods.definitions.models import MethodSource
from ordessa_engineering.methods.definitions.models.capabilities import CompilationCapabilities

from test_method_work import call, env
from test_review_usecases import _context


def _resource(resource_id, kind, path, media_type, raw):
    return {"id": resource_id, "kind": kind, "path": path,
            "media_type": media_type,
            "sha256": hashlib.sha256(raw).hexdigest()}


def _method_source(root):
    descriptor = next(item for item in owner_capabilities()
                      if item.capability_id == "engineering.executions.dispatch")
    capabilities = CompilationCapabilities(
        (*command_capabilities().capabilities, descriptor), trust_class="host")
    workflow = {
        "schema_version": 1,
        "workflow_id": "method-dispatch-task-fixture",
        "entry": "await_dispatch",
        "resume_contract": "ordessa.engineering.current-work/1",
        "context_slots": ["package_ref", "dispatch_input", "work_inputs"],
        "wait_kinds": ["owner_reconciliation"],
        "stop_outcomes": ["accepted", "rejected"],
        "steps": [
            {"id": "await_dispatch", "kind": "wait",
             "event": "engineering.work.current_condition", "bind": {},
             "next": "dispatch"},
            {"id": "dispatch", "kind": "operation",
             "operation": "engineering.executions.dispatch",
             "inputs": {"dispatch": "dispatch_input"},
             "outcomes": {"completed": {"stop": "accepted"},
                          "failed": {"stop": "rejected"},
                          "unknown": {"stop": "rejected"}},
             "config": {"package_slot": "package_ref",
                 "task_prompt": {
                     "template_resource": "template.implementation_task",
                     "bindings": {
                         "instructions": "instructions_ref",
                         "package_ref": "package_ref",
                         "design_targets": "design_targets",
                         "run_id": "run_id", "step_id": "step_id",
                         "attempt": "attempt",
                     },
                     "actions": ["edit_repository", "run_checks"],
                     "timeout": 30,
                 }}},
        ],
    }
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "urn:fixture:dispatch-work-inputs",
        "type": "object", "additionalProperties": False,
        "required": ["document_type", "schema_version", "run_id"],
        "properties": {
            "document_type": {"const": "dispatch-work-inputs"},
            "schema_version": {"const": 1},
            "run_id": {"type": "string", "minLength": 1},
        },
    }
    template = (
        "${instructions}\nPackage: ${package_ref}\n"
        "Design: ${design_targets}\nRun: ${run_id}/${step_id}/${attempt}\n"
    ).encode("utf-8")
    resources = {
        "workflow.main": ("workflow", "workflow.yaml", "application/yaml",
                          json.dumps(workflow, separators=(",", ":")).encode()),
        "document.work-inputs.schema": ("document_schema", "work-inputs.schema.json",
                                        "application/schema+json",
                                        json.dumps(schema, separators=(",", ":")).encode()),
        "template.implementation_task": ("document_template", "task.md", "text/markdown", template),
    }
    for _resource_id, (kind, path, _media, raw) in resources.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    document = {"document_type": "dispatch-work-inputs",
                "schema": {"resource": "document.work-inputs.schema"},
                "validation_target": "method_content"}
    manifest = {
        "schema_version": 1, "method_id": "test.method-dispatch-task",
        "release_version": "1.0.0", "compiler_contract": "ordessa.methods/v1",
        "entry": {"resource": "workflow.main"},
        "documents": [document],
        "metadata": {"work_source": {
            "contract_version": "ordessa.persisted-work-source/1",
            "input_document_slot": "work_inputs",
            "input_document_type": "dispatch-work-inputs",
            "waits": {"await_dispatch": {"family": "owner_reconciliation",
                                           "refs": [], "event_slots": {}}},
        }},
        "resources": [_resource(resource_id, kind, path, media_type, raw)
            for resource_id, (kind, path, media_type, raw) in resources.items()],
        "requires": [{key: getattr(descriptor, key) for key in
                      ("capability_id", "kind", "interface_version", "contract_digest")}],
    }
    (root / "method.yaml").write_text(json.dumps(manifest, separators=(",", ":")),
                                      encoding="utf-8")
    loaded = load_method(MethodSource(root), reader=FileResourceReader())
    assert loaded.ok and loaded.value is not None, loaded.error
    compiled = compile_method(loaded.value, capabilities, "fixture:dispatch-task")
    assert compiled.ok and compiled.value is not None, compiled.error
    return compiled.value, capabilities, schema


@pytest.fixture
def dispatch_task_world(env, tmp_path):
    from test_proposal_usecases import ACTOR, CREATED_AT
    from ordessa_engineering.domain.packages.models import ImplementationPackage

    e = env
    root = tmp_path / "method-dispatch-task"
    root.mkdir()
    compiled, capabilities, schema = _method_source(root)
    published = freeze_method(compiled, e["store"], e["store"],
        capability_catalog=type("Catalog", (), {"read_current": lambda _self: capabilities})())
    assert published.ok and published.value is not None, published.error
    snap_ref = published.value.ref
    method_ref = MethodRef(snap_ref.method_id, snap_ref.release_version,
        snap_ref.schema_version, Digest("sha256", snap_ref.snapshot_digest))
    e["management"].adopt(method_ref, _context(e["scope"], "adopt-task-method"),
                           expected_version=1)
    snapshot = e["store"].get(snap_ref)

    fixture = runpy.run_path(str(Path(__file__).parents[1] /
                                 "domain/test_implementation_package_binding.py"))
    records = fixture["_records"]
    record_globals = records.__globals__
    old_scope, old_method = record_globals["SCOPE"], record_globals["METHOD"]
    record_globals["SCOPE"], record_globals["METHOD"] = e["scope"], method_ref
    try:
        _intent, _grant, package, *_ = records(package_changes={
            "allowed_actions": ("edit_repository", "run_checks")})
    finally:
        record_globals["SCOPE"], record_globals["METHOD"] = old_scope, old_method
    blobs = SQLiteBlobStore(e["lib"])
    instruction_raw = b"Apply only the frozen package changes."
    instruction_ref = blobs.put_verified(instruction_raw,
        Digest("sha256", hashlib.sha256(instruction_raw).hexdigest()), "text/plain")
    package = replace(package,
        payload=replace(package.payload, instructions_ref=instruction_ref))
    assert type(package) is ImplementationPackage
    with e["factory"].begin(e["scope"]) as uow:
        package_ref = uow.implementation.create_package(package)
        uow.commit()

    document_resource = next(item for item in snapshot.resources
        if item.resource_id == "document.work-inputs.schema")
    exact = ExactMethodResourceRef(method_ref, document_resource.logical_path,
        Digest("sha256", document_resource.digest), document_resource.resource_id)
    schema_id = urljoin("https://ordessa.invalid/method/" + exact.logical_path,
                        schema["$id"])
    work_value = {"document_type": "dispatch-work-inputs", "schema_version": 1,
                  "run_id": "dispatch-task-run"}
    revision = ArtifactRevision(e["scope"], "dispatch-task-input", "rev-1",
        CREATED_AT, ACTOR,
        MethodPayload("application/json", schema_id,
                      MethodContent.from_value(exact, work_value)),
        schema_version=2, method_refs=(method_ref,))
    with e["factory"].begin(e["scope"]) as uow:
        uow.engineering.create(Artifact(e["scope"], "dispatch-task-input", "plan", CREATED_AT))
        verify_material(revision, uow.engineering.validated_budget())
        uow.engineering.append_revision(revision, expected_version=0)
        uow.commit()
    work_ref = ArtifactRevisionRef(e["scope"].realm_id, e["scope"].project_id,
        revision.artifact_id, revision.revision_id, revision.digest)

    @contextmanager
    def guard_start(context, snapshot_arg, *, run_id, selection):
        assert selection is None
        assert run_id == "dispatch-task-run"
        yield WorkSeed({"package_ref": asdict(package_ref),
                        "work_inputs": asdict(work_ref)}, e["source"].start_reads)

    e["source"].guard_start = guard_start
    call(e, "engineering.work.start", {"run_id": "dispatch-task-run"}, "start-task-run")
    bindings = e["bindings"]
    renderer = MethodDispatchInputs(bindings, blobs, e["access"])
    context = _context(e["scope"], "render-task")
    pending_task = renderer.read_task(context, run_id="dispatch-task-run",
                                      step_id="dispatch", attempt=1)
    return {"env": e, "renderer": renderer, "package": package,
            "method_ref": method_ref, "work_ref": work_ref,
            "task": pending_task,
            "snapshot": snapshot, "node": snapshot.program.workflow.steps[1],
            "blobs": blobs, "snapshot_store": e["store"]}


def test_method_declared_prompt_renders_before_dispatch_input_exists(dispatch_task_world):
    world = dispatch_task_world
    task = world["task"]
    assert task["run_id"] == "dispatch-task-run"
    assert task["step_id"] == "dispatch"
    assert task["attempt"] == 1
    assert task["actions"] == ["edit_repository", "run_checks"]
    assert task["timeout"] == 30
    assert task["work_inputs_ref"] == asdict(world["work_ref"])
    assert task["package_ref"] == asdict(world["package"].ref)
    assert task["method_ref"]["method_id"] == world["method_ref"].method_id
    assert "Apply only the frozen package changes." in task["task_text"]
    assert "dispatch-task-run/dispatch/1" in task["task_text"]
    with world["env"]["factory"].begin(world["env"]["scope"], "read") as uow:
        row = uow.workflow.run_row("dispatch-task-run")
        assert "dispatch_input" not in row["inputs"]["slots"]


def test_renderer_rejects_method_action_not_in_frozen_package(dispatch_task_world):
    from dataclasses import replace
    from ordessa_engineering.methods.definitions.models.compiled import freeze_value

    world = dispatch_task_world
    config = {
        "package_slot": "package_ref",
        "task_prompt": {
            "template_resource": "template.implementation_task",
            "bindings": {"instructions": "instructions_ref"},
            "actions": ["edit_repository", "run_checks", "deploy"],
            "timeout": 30,
        },
    }
    node = replace(world["node"], config=freeze_value(config))
    with pytest.raises(ApplicationError, match="DISPATCH_TASK_ACTIONS_UNAVAILABLE"):
        render_dispatch_task(world["snapshot"], world["package"], node,
            run_id="dispatch-task-run", step_id="dispatch", attempt=1,
            blobs=world["blobs"], resource_reader=world["snapshot_store"])


def test_renderer_rejects_non_dispatch_action_even_if_package_lists_it(dispatch_task_world):
    world = dispatch_task_world
    config = {
        "package_slot": "package_ref",
        "task_prompt": {
            "template_resource": "template.implementation_task",
            "bindings": {"instructions": "instructions_ref"},
            "actions": ["accept_artifact"],
            "timeout": 30,
        },
    }
    from ordessa_engineering.methods.definitions.models.compiled import freeze_value
    node = replace(world["node"], config=freeze_value(config))
    package = replace(world["package"], payload=replace(
        world["package"].payload,
        allowed_actions=(*world["package"].payload.allowed_actions, "accept_artifact"),
    ))
    with pytest.raises(ApplicationError, match="DISPATCH_TASK_ACTIONS_UNAVAILABLE"):
        render_dispatch_task(world["snapshot"], package, node,
            run_id="dispatch-task-run", step_id="dispatch", attempt=1,
            blobs=world["blobs"], resource_reader=world["snapshot_store"])


def test_renderer_rejects_missing_or_mismatched_placeholder(dispatch_task_world):
    from dataclasses import replace
    from ordessa_engineering.methods.definitions.models.compiled import freeze_value

    world = dispatch_task_world
    config = {
        "package_slot": "package_ref",
        "task_prompt": {
            "template_resource": "template.implementation_task",
            "bindings": {"wrong": "instructions_ref"},
            "actions": ["edit_repository", "run_checks"],
            "timeout": 30,
        },
    }
    node = replace(world["node"], config=freeze_value(config))
    with pytest.raises(ApplicationError, match="DISPATCH_TASK_PROMPT_UNAVAILABLE"):
        render_dispatch_task(world["snapshot"], world["package"], node,
            run_id="dispatch-task-run", step_id="dispatch", attempt=1,
            blobs=world["blobs"], resource_reader=world["snapshot_store"])


def test_read_task_rejects_wrong_attempt_and_disabled_method(dispatch_task_world):
    world = dispatch_task_world
    renderer, e = world["renderer"], world["env"]
    context = _context(e["scope"], "dispatch-task-wrong-attempt")
    with pytest.raises(ApplicationError, match="WORK_DISPATCH_ATTEMPT_CHANGED"):
        renderer.read_task(context, run_id="dispatch-task-run", step_id="dispatch", attempt=2)
    e["management"].control(world["method_ref"], _context(e["scope"], "disable-task-method"),
        expected_version=0, enabled=False, reason="controlled renderer fixture")
    with pytest.raises(ApplicationError, match="METHOD_DISABLED"):
        renderer.read_task(_context(e["scope"], "dispatch-task-disabled"),
            run_id="dispatch-task-run", step_id="dispatch", attempt=1)

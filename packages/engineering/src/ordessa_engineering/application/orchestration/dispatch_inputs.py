"""Render one method-declared, bounded dispatch task over original state.

This is a read-only task projection. It does not grant actions, authorize a
native Unit call, or advance a MethodRun.
"""
from dataclasses import asdict
import hashlib
import string

from ordessa_infrastructure.encoding import canonical_bytes

from ...application.contracts.commands import CommandContext
from ...application.contracts.errors import ApplicationError
from ...application.contracts.execution_dispatch import EXECUTION_DISPATCH
from ...application.contracts.run_waits import run_wait_row_digest
from ...domain.artifacts.ref_codec import decode_artifact_ref
from ...domain.artifacts.models import MethodPayload
from ...domain.approvals.scope import ACTIONS
from ...domain.common.models.refs import BlobRef
from ...domain.common.models.values import Digest
from ...domain.packages.codec import decode_package_ref
from ...domain.packages.models import (ImplementationPackage, ImplementationPackagePayload,
                                      PreparedPackagePayload, package_payload_projection)
from ...methods.definitions.models.compiled import OperationNode, WaitNode, thaw_value
from ...methods.loading.parsing import parse_document
from ..contracts.operation_registry import registry_ref
from ..orchestration.method_content import document_type_for_payload, validate_document_content
from ..orchestration.method_runs import MethodRunBindings, _check_rounds


_TEMPLATE_BINDINGS = frozenset({
    "run_id", "step_id", "attempt",
    "package_id", "implementation_intent_id", "package_ref", "method_ref",
    "change_set", "design_targets", "resolved_file_manifest",
    "proposal_coverage", "baseline_snapshots", "allowed_actions",
    "execution_profile_ref", "instructions_ref", "skill_snapshot_refs",
})
_FORBIDDEN_DISPATCH_ACTIONS = frozenset({
    "accept_artifact", "apply_change", "generate_package",
})
_DISPATCH_ACTIONS = ACTIONS - _FORBIDDEN_DISPATCH_ACTIONS
_MAX_TASK_BYTES = 256 * 1024


def _read_blob(reader, ref):
    read = getattr(reader, "read_blob", None)
    if callable(read):
        return read(ref)
    read = getattr(reader, "read_verified", None)
    if callable(read):
        return read(ref)
    raise ApplicationError("DISPATCH_TASK_INPUT_AUTHORITY_UNAVAILABLE")


class _UoWResourceReader:
    """Adapt frozen snapshot resource refs to the original same-UoW blob port."""

    def __init__(self, implementation):
        self.implementation = implementation

    def read_blob(self, ref):
        if type(getattr(ref, "digest", None)) is str:
            ref = BlobRef(Digest("sha256", ref.digest), ref.byte_length,
                          ref.media_type, ref.storage_object_id)
        return self.implementation.read_blob(ref)


def render_dispatch_task(snapshot, package, node, *, run_id, step_id, attempt,
                         blobs, resource_reader):
    """Pure bounded renderer over exact method and package values.

    ``resource_reader`` is the original snapshot/UoW reader at the caller's
    current read cut. The returned text is task data, not a permission.
    """
    try:
        if (type(package) is not ImplementationPackage or type(node) is not OperationNode
                or node.id != step_id or node.operation != EXECUTION_DISPATCH
                or type(run_id) is not str or type(step_id) is not str
                or type(attempt) is not int or attempt < 1):
            raise ValueError
        from ...domain.artifacts.method_binding import MethodRef
        from ...domain.common.models.values import Digest
        ref = snapshot.ref
        snapshot_method = MethodRef(ref.method_id, ref.release_version,
            ref.schema_version, Digest("sha256", ref.snapshot_digest))
        if package.payload.method_ref != snapshot_method:
            raise ValueError
        _config, prompt = MethodDispatchInputs._task_config(node)
        actions, timeout = prompt["actions"], prompt["timeout"]
        if (not actions or any(type(action) is not str or action not in _DISPATCH_ACTIONS for action in actions)
                or len(set(actions)) != len(actions)
                or not set(actions) <= set(package.payload.allowed_actions)
                or type(timeout) not in (int, float) or not 0 < timeout <= 60):
            raise ApplicationError("DISPATCH_TASK_ACTIONS_UNAVAILABLE")
        manifest_raw = _read_blob(resource_reader, snapshot.manifest_ref)
        manifest = parse_document(manifest_raw, snapshot.manifest_ref.media_type, "method.yaml")
        resources = manifest.get("resources") if type(manifest) is dict else None
        declared = [item for item in resources or ()
                    if type(item) is dict and item.get("id") == prompt["template_resource"]]
        stored = [item for item in snapshot.resources
                  if item.resource_id == prompt["template_resource"]]
        if len(declared) != 1 or len(stored) != 1:
            raise ValueError
        resource, indexed = declared[0], stored[0]
        blob = indexed.blob_ref
        if (resource.get("path") != indexed.logical_path
                or resource.get("sha256") != blob.digest
                or resource.get("media_type") != blob.media_type
                or resource.get("kind") != "document_template"
                or blob.byte_length > _MAX_TASK_BYTES):
            raise ValueError
        template_raw = _read_blob(resource_reader, blob)
        if (type(template_raw) is not bytes or len(template_raw) != blob.byte_length
                or len(template_raw) > _MAX_TASK_BYTES
                or hashlib.sha256(template_raw).hexdigest() != blob.digest):
            raise ValueError
        template = template_raw.decode("utf-8", errors="strict")
        names = set()
        for match in string.Template.pattern.finditer(template):
            if match.group("invalid") is not None:
                raise ValueError
            name = match.group("named") or match.group("braced")
            if name is not None:
                names.add(name)
        if names != set(prompt["bindings"]):
            raise ValueError
        package_ref = package.ref
        method_ref = package.payload.method_ref

        def render(source):
            if source == "run_id":
                value = run_id
            elif source == "step_id":
                value = step_id
            elif source == "attempt":
                value = str(attempt)
            elif source == "package_id":
                value = package.package_id
            elif source == "implementation_intent_id":
                value = package.payload.implementation_intent_id
            elif source == "package_ref":
                value = asdict(package_ref)
            elif source == "method_ref":
                value = asdict(method_ref)
            elif source == "instructions_ref":
                instruction_ref = package.payload.instructions_ref
                if instruction_ref.byte_length > _MAX_TASK_BYTES:
                    raise ValueError
                raw = _read_blob(blobs, instruction_ref)
                if (type(raw) is not bytes or len(raw) != instruction_ref.byte_length
                        or hashlib.sha256(raw).hexdigest() != instruction_ref.digest.hex):
                    raise ValueError
                return raw.decode("utf-8", errors="strict")
            else:
                key = source
                value = package_payload_projection(package.payload, identity=True).get(key)
            if value is None:
                raise ValueError
            return value if type(value) is str else canonical_bytes(value).decode("utf-8")

        task_text = string.Template(template).substitute({
            placeholder: render(source) for placeholder, source in prompt["bindings"].items()
        })
        if len(task_text.encode("utf-8")) > _MAX_TASK_BYTES:
            raise ValueError
        return {"task_text": task_text, "actions": list(actions), "timeout": timeout}
    except ApplicationError:
        raise
    except Exception as exc:
        raise ApplicationError("DISPATCH_TASK_PROMPT_UNAVAILABLE") from exc


class MethodDispatchInputs:
    """Read and render the exact current MethodRun dispatch task."""

    def __init__(self, bindings, blobs, access):
        if (type(bindings) is not MethodRunBindings
                or getattr(bindings, "factory", None) is None
                or getattr(getattr(bindings, "methods", None), "factory", None) is not bindings.factory
                or not callable(getattr(bindings, "registry_loader", None))
                or not callable(getattr(blobs, "read_verified", None))
                or getattr(blobs, "authority_id", None) != bindings.factory.authority_id
                or not callable(getattr(access, "require", None))):
            raise ApplicationError("DISPATCH_TASK_INPUT_AUTHORITY_UNAVAILABLE")
        self.bindings, self.blobs, self.access = bindings, blobs, access

    @staticmethod
    def _fail():
        raise ApplicationError("DISPATCH_TASK_INPUT_UNAVAILABLE")

    def _method_source_policy(self, snapshot, resource_reader):
        try:
            raw = _read_blob(resource_reader, snapshot.manifest_ref)
            value = parse_document(raw, snapshot.manifest_ref.media_type, "method.yaml")
            metadata = value.get("metadata") if type(value) is dict else None
            source = metadata.get("work_source") if type(metadata) is dict else None
            if (type(source) is not dict
                    or source.get("contract_version") != "ordessa.persisted-work-source/1"
                    or type(source.get("waits")) is not dict
                    or type(source.get("input_document_slot")) is not str
                    or not source["input_document_slot"]
                    or type(source.get("input_document_type")) is not str
                    or not source["input_document_type"]):
                self._fail()
            return source
        except ApplicationError:
            raise
        except Exception as exc:
            raise ApplicationError("DISPATCH_TASK_INPUT_UNAVAILABLE") from exc

    @staticmethod
    def _task_config(node):
        try:
            config = {} if node.config is None else thaw_value(node.config)
            if (type(config) is not dict or set(config) != {"package_slot", "task_prompt"}
                    or type(config["package_slot"]) is not str or not config["package_slot"]):
                raise ValueError
            prompt = config["task_prompt"]
            if (type(prompt) is not dict or set(prompt) != {
                    "template_resource", "bindings", "actions", "timeout"}
                    or type(prompt["template_resource"]) is not str
                    or not prompt["template_resource"] or type(prompt["bindings"]) is not dict
                    or not prompt["bindings"] or type(prompt["actions"]) is not list
                    or not prompt["actions"] or type(prompt["timeout"]) not in (int, float)
                    or not 0 < prompt["timeout"] <= 60):
                raise ValueError
            for placeholder, source in prompt["bindings"].items():
                if (type(placeholder) is not str or not placeholder
                        or type(source) is not str or source not in _TEMPLATE_BINDINGS):
                    raise ValueError
            return config, prompt
        except Exception as exc:
            raise ApplicationError("DISPATCH_TASK_PROMPT_UNAVAILABLE") from exc

    def _work_input(self, uow, snapshot, row, run_id, source_policy):
        slot = source_policy["input_document_slot"]
        try:
            raw_ref = row["inputs"]["slots"][slot]
            ref = decode_artifact_ref(raw_ref)
            artifact = uow.engineering.get_artifact(ref.artifact_id)
            if artifact.scope != uow.scope:
                raise ApplicationError("SCOPE_MISMATCH")
            revision = uow.engineering.resolve_revision(ref)
            if (type(revision.payload) is not MethodPayload
                    or document_type_for_payload(snapshot, revision.payload)
                       != source_policy["input_document_type"]):
                self._fail()
            result = validate_document_content(snapshot, source_policy["input_document_type"],
                                               {"value": revision.payload.content.value})
            if not result.ok or revision.payload.content.value.get("run_id") != run_id:
                self._fail()
            return ref
        except ApplicationError:
            raise
        except Exception as exc:
            raise ApplicationError("DISPATCH_TASK_INPUT_UNAVAILABLE") from exc

    def read_task(self, context, *, run_id, step_id, attempt):
        if (type(context) is not CommandContext or type(run_id) is not str or not run_id
                or type(step_id) is not str or not step_id
                or type(attempt) is not int or not 1 <= attempt <= 4096):
            raise ApplicationError("INVALID_ARGUMENT")
        self.access.require(context, EXECUTION_DISPATCH)
        factory = self.bindings.factory
        with factory.begin(context.scope, "read") as uow:
            row = uow.workflow.run_row(run_id)
            method = self.bindings._inputs(context, row)
            marker = uow.workflow.read(row["method_ref"])
            if marker != {key: value for key, value in row["inputs"].items()
                          if key not in ("slots", "rounds")}:
                raise ApplicationError("WORK_BINDING_INVALID")
            if row["registry_ref"] != registry_ref(self.bindings.registry_loader()):
                raise ApplicationError("METHOD_CAPABILITY_CHANGED")
        with self.bindings.methods.guard_method(context, method) as snapshot:
            program = self.bindings._bound_program(snapshot, method, row)
            _check_rounds(program, row["inputs"])
            if snapshot.ref.method_id != method.method_id:
                raise ApplicationError("WORK_BINDING_INVALID")
            cursor = row["cursor"]
            if type(cursor) is not int or not 0 <= cursor < len(program.workflow.steps):
                raise ApplicationError("WORK_CURSOR_INVALID")
            current = program.workflow.steps[cursor]
            if row["status"] == "RUNNING" and type(current) is OperationNode:
                node = current
            elif (row["status"] == "WAITING_FOR_CONDITION" and type(current) is WaitNode
                    and row["wait_reason"] == current.id):
                following = [item for item in program.workflow.steps if item.id == current.next]
                if len(following) != 1 or type(following[0]) is not OperationNode:
                    raise ApplicationError("DISPATCH_WORK_STEP_UNAVAILABLE")
                node = following[0]
            else:
                raise ApplicationError("DISPATCH_WORK_STEP_UNAVAILABLE")
            if node.operation != EXECUTION_DISPATCH or node.id != step_id:
                raise ApplicationError("DISPATCH_WORK_STEP_UNAVAILABLE")
            with factory.begin(context.scope, "read") as uow:
                current_row = uow.workflow.run_row(run_id)
                if current_row != row:
                    raise ApplicationError("RUN_WAIT_CHANGED")
                current_control = uow.methods.control(method)
                if not current_control.enabled:
                    raise ApplicationError("METHOD_DISABLED")
                expected_attempt = 1 + sum(1 for prior in uow.workflow.step_rows(run_id)
                    if prior["step_id"] == node.id and prior["receipt_ref"] is not None)
                if attempt != expected_attempt:
                    raise ApplicationError("WORK_DISPATCH_ATTEMPT_CHANGED")
                task_config, _task_prompt = self._task_config(node)
                slots = row["inputs"]["slots"]
                try:
                    package_ref = decode_package_ref(slots[task_config["package_slot"]])
                except Exception as exc:
                    raise ApplicationError("DISPATCH_METHOD_INPUT_BINDING_UNAVAILABLE") from exc
                package = uow.implementation.resolve_package(package_ref)
                if type(getattr(package, 'payload', None)) is PreparedPackagePayload:
                    raise ApplicationError("IMPLEMENTATION_ENVELOPE_UNAVAILABLE")
                if type(getattr(package, 'payload', None)) is not ImplementationPackagePayload:
                    raise ApplicationError("IMPLEMENTATION_ENVELOPE_UNAVAILABLE")
                if (type(package) is not ImplementationPackage
                        or package.scope != context.scope or package.payload.method_ref != method):
                    raise ApplicationError("DISPATCH_WORK_BINDING_INVALID")
                resource_reader = _UoWResourceReader(uow.implementation)
                source_policy = self._method_source_policy(snapshot, resource_reader)
                if source_policy["input_document_slot"] not in (program.workflow.context_slots or ()):
                    raise ApplicationError("WORK_CONDITION_INPUT_MISSING")
                work_inputs_ref = self._work_input(uow, snapshot, row, run_id, source_policy)
                rendered = render_dispatch_task(snapshot, package, node,
                    run_id=run_id, step_id=node.id, attempt=attempt,
                    blobs=uow.implementation, resource_reader=resource_reader)
                return {
                    **rendered,
                    "run_id": run_id,
                    "step_id": node.id,
                    "attempt": attempt,
                    "package_ref": asdict(package_ref),
                    "method_ref": asdict(method),
                    "row_digest": asdict(run_wait_row_digest(row)),
                    "work_inputs_ref": asdict(work_inputs_ref),
                }


__all__ = ["MethodDispatchInputs", "render_dispatch_task"]

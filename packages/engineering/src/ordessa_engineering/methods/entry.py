"""Safe method validation/compilation entry points (pure method kernel orchestration).

These verify a caller-constructible projection against immutable captured bytes and
then delegate to the pure method kernels. They hold no publication or store authority.
"""
from __future__ import annotations

from copy import deepcopy

from .compilation.compiler import _compile_captured_method
from .definitions.contracts.validation import ValidationReport
from .definitions.errors import Diagnostic, MethodError, MethodFailure, MethodResult
from .definitions.models import (CompiledMethod, CompilationCapabilities, LoadedMethod,
    MethodDefinition, ActionDefinition, ActionInput, StepInput, ActionStep,
    ActionOutput, AdmissionRequirement, PreparationDocument, ResourceRef)
from .loading.captured import verify_loaded_method
from .validation.compatibility import validate_compatibility
from .validation.structure import validate_resource_structure
from .validation.schema import validate_document_schemas
from .definitions.models.identity import method_digest
from .definitions.models.identity import MethodRef


def validate_method(loaded: LoadedMethod, capabilities: CompilationCapabilities) -> ValidationReport:
    """Validate structure/references and injected capability compatibility.

    A fixture catalog may support design-time validation, but its warning is
    retained and never upgraded to a production-activation claim.
    """
    try:
        verified = verify_loaded_method(loaded)
        if verified.identity.schema_version == 2:
            return ValidationReport(False, "declaration-only", (Diagnostic(
                "METHOD_EXECUTION_UNSUPPORTED", "error",
                "schema-2 action declarations are not connected to an execution validator",
                path=verified.source_bundle.manifest_capture.logical_path,
            ),), registry_snapshot_ref=capabilities.registry_snapshot_ref)
        return validate_compatibility(verified, deepcopy(capabilities))
    except MethodFailure as exc:
        error = exc.error
        return ValidationReport(False, "compatibility", (Diagnostic(
            error.code, "error", error.message, error.resource_id,
            error.path, error.pointer,
        ),), registry_snapshot_ref=capabilities.registry_snapshot_ref)
    except (AttributeError, TypeError, ValueError, KeyError):
        return ValidationReport(False, "compatibility", (Diagnostic(
            "METHOD_VALIDATION_FAILED", "error", "method validation failed safely",
        ),), registry_snapshot_ref=capabilities.registry_snapshot_ref)


def compile_method(loaded: LoadedMethod, capabilities: CompilationCapabilities,
                   compiler_version: str) -> MethodResult[CompiledMethod]:
    """Rebuild caller-constructible caches from immutable bytes before compilation."""
    if not isinstance(compiler_version, str) or not compiler_version.strip():
        return MethodResult.failure(MethodError("COMPILER_VERSION_INVALID", "compiler version must be a non-empty string"))
    try:
        rebuilt = verify_loaded_method(loaded)
    except MethodFailure as exc:
        return MethodResult.failure(exc.error)
    except (AttributeError, TypeError, ValueError, KeyError, RecursionError):
        return MethodResult.failure(MethodError("LOADED_PROJECTION_INVALID", "loaded method projection could not be verified against captured bytes"))
    if rebuilt.identity.schema_version == 2:
        return MethodResult.failure(MethodError(
            "METHOD_EXECUTION_UNSUPPORTED",
            "schema-2 action declarations have no execution compiler yet",
            path=rebuilt.source_bundle.manifest_capture.logical_path,
        ))
    captured_capabilities = deepcopy(capabilities)
    return _compile_captured_method(rebuilt, captured_capabilities, compiler_version)


def _typed_action(value: dict, resource_refs: dict[str, ResourceRef], *, resource_id: str,
                  path: str) -> ActionDefinition:
    diagnostics = validate_resource_structure(value, "action", path, resource_id)
    if diagnostics:
        raise MethodFailure(MethodError(diagnostics[0].code, diagnostics[0].message,
            resource_id=resource_id, path=path, pointer=diagnostics[0].pointer))
    inputs = tuple(ActionInput(item["name"], item["value_kind"]) for item in value["inputs"])
    input_names = {item.name for item in inputs}
    if len(input_names) != len(inputs):
        raise MethodFailure(MethodError("ACTION_BINDING_INVALID", "action input names must be unique", resource_id, path))
    action_resource_ids = set(value["resources"])
    if not action_resource_ids <= set(resource_refs):
        raise MethodFailure(MethodError("ACTION_BINDING_INVALID",
            "action resources must be declared by the method", resource_id, path))
    steps: list[ActionStep] = []
    produced: dict[str, set[str]] = {}
    step_ids: set[str] = set()
    for step in value["steps"]:
        sid = step["step_id"]
        if sid in step_ids:
            raise MethodFailure(MethodError("ACTION_BINDING_INVALID", "step ids must be unique", resource_id, path))
        bound: list[StepInput] = []
        names: set[str] = set()
        for item in step["inputs"]:
            if item["name"] in names:
                raise MethodFailure(MethodError("ACTION_BINDING_INVALID", "step input slots must be unique", resource_id, path))
            names.add(item["name"])
            source_kind, source_name = item["source_kind"], item["source_name"]
            step_id = item.get("step_id")
            if source_kind == "action_input" and source_name not in input_names:
                raise MethodFailure(MethodError("ACTION_BINDING_INVALID", "step input names an undeclared action input", resource_id, path))
            if source_kind == "step_output" and (step_id not in produced or source_name not in produced[step_id]):
                raise MethodFailure(MethodError("ACTION_BINDING_INVALID", "step output must bind an earlier declared output", resource_id, path))
            if source_kind == "resource" and source_name not in action_resource_ids:
                raise MethodFailure(MethodError("ACTION_BINDING_INVALID", "step resource is not declared by its action", resource_id, path))
            bound.append(StepInput(item["name"], source_kind, source_name, step_id))
        outputs = tuple(step["outputs"])
        if len(set(outputs)) != len(outputs):
            raise MethodFailure(MethodError("ACTION_BINDING_INVALID", "step outputs must be unique", resource_id, path))
        step_ids.add(sid)
        produced[sid] = set(outputs)
        gate_requirements = tuple(AdmissionRequirement(item["kind"], tuple(item["inputs"]))
                                  for item in step.get("admission", []))
        available_slots = {item.name for item in bound}
        if any(not set(item.inputs) <= available_slots for item in gate_requirements):
            raise MethodFailure(MethodError("ACTION_ADMISSION_INVALID", "step admission must bind only that step's declared input slots", resource_id, path))
        steps.append(ActionStep(sid, step["kind"], step["name"], tuple(bound), outputs, gate_requirements))
    outputs: list[ActionOutput] = []
    output_names: set[str] = set()
    for item in value["outputs"]:
        if item["name"] in output_names or item["step_id"] not in produced or item["output"] not in produced[item["step_id"]]:
            raise MethodFailure(MethodError("ACTION_BINDING_INVALID", "action outputs must uniquely bind declared step outputs", resource_id, path))
        output_names.add(item["name"])
        outputs.append(ActionOutput(item["name"], item["value_kind"], item["step_id"], item["output"]))
    admissions = tuple(AdmissionRequirement(item["kind"], tuple(item["inputs"])) for item in value["admission"])
    if any(not set(item.inputs) <= input_names for item in admissions):
        raise MethodFailure(MethodError("ACTION_ADMISSION_INVALID", "action admission may bind declared action inputs only", resource_id, path))
    preparation_documents = tuple(PreparationDocument(item["role"], item["template_resource_id"])
                                  for item in value.get("preparation_documents", ()))
    if any(item.template_resource_id not in action_resource_ids
           or resource_refs[item.template_resource_id].kind != "template"
           for item in preparation_documents):
        raise MethodFailure(MethodError("ACTION_PREPARATION_DOCUMENT_INVALID",
            "preparation document references must name action-bound template resources", resource_id, path))
    return ActionDefinition(1, value["action_id"], inputs, tuple(steps), tuple(outputs), admissions,
                            tuple(resource_refs[item] for item in value["resources"]),
                            preparation_documents)


def read_method_definition(loaded: LoadedMethod) -> MethodResult[MethodDefinition]:
    """Rebuild a schema-2 typed declaration from its exact immutable source capture.

    This is a declaration reader only: it grants no execution, admission, or
    routing authority and deliberately does not invoke the schema-1 compiler.
    """
    try:
        rebuilt = verify_loaded_method(loaded)
        manifest = rebuilt.manifest
        if rebuilt.identity.schema_version != 2:
            raise MethodFailure(MethodError("METHOD_SCHEMA_UNSUPPORTED", "typed action declarations require schema 2",
                path=rebuilt.source_bundle.manifest_capture.logical_path))
        declarations = {item["id"]: item for item in manifest["resources"]}
        captures = {item.resource_id: item for item in rebuilt.parsed_source.resources}
        refs = {rid: ResourceRef(rid, declarations[rid]["sha256"], declarations[rid]["kind"])
                for rid in declarations}
        category_fields = {"actions": "action", "criteria": "criteria", "prompts": "prompt",
                           "templates": "template", "schemas": "schema", "routing": "routing"}
        for field, kind in category_fields.items():
            if any(ref not in refs or refs[ref].kind != kind for ref in manifest[field]):
                raise MethodFailure(MethodError("METHOD_RESOURCE_REFERENCE_INVALID",
                    f"{field} must reference declared {kind} resources",
                    path=rebuilt.source_bundle.manifest_capture.logical_path, pointer=f"/{field}"))
        referenced = {ref for field in category_fields for ref in manifest[field]}
        if referenced != set(refs):
            raise MethodFailure(MethodError("METHOD_RESOURCE_REFERENCE_INVALID",
                "schema-2 resources must be assigned to exactly one declaration category",
                path=rebuilt.source_bundle.manifest_capture.logical_path, pointer="/resources"))
        actions = []
        action_ids: set[str] = set()
        for rid in manifest["actions"]:
            value = captures[rid].content.value
            action = _typed_action(value, refs, resource_id=rid,
                                   path=captures[rid].content.captured.logical_path)
            if action.action_id in action_ids:
                raise MethodFailure(MethodError("DUPLICATE_ACTION_ID", "action ids must be unique within their method", rid,
                    captures[rid].content.captured.logical_path))
            action_ids.add(action.action_id)
            actions.append(action)
        if sum(bool(action.preparation_documents) for action in actions) > 1:
            raise MethodFailure(MethodError("METHOD_PREPARATION_DOCUMENT_AMBIGUOUS",
                "a method may declare preparation document roles on at most one action",
                path=rebuilt.source_bundle.manifest_capture.logical_path, pointer="/actions"))
        routed_actions: set[str] = set()
        for rid in manifest["routing"]:
            value = captures[rid].content.value
            diagnostics = validate_resource_structure(value, "routing", captures[rid].content.captured.logical_path, rid)
            if diagnostics:
                item = diagnostics[0]
                raise MethodFailure(MethodError(item.code, item.message, rid, item.path, item.pointer))
            action_by_id = {action.action_id: action for action in actions}
            for route in value["routes"]:
                action = action_by_id.get(route["action_id"])
                profile_ref = route["profile_ref"]
                if action is None:
                    raise MethodFailure(MethodError("METHOD_ROUTING_INVALID", "routing references an undeclared action", rid,
                        captures[rid].content.captured.logical_path))
                if route["action_id"] in routed_actions:
                    raise MethodFailure(MethodError("METHOD_ROUTING_INVALID", "each action has exactly one candidate route", rid,
                        captures[rid].content.captured.logical_path))
                routed_actions.add(route["action_id"])
                if profile_ref.get("kind") == "caller_input":
                    declared = {item.name: item.value_kind for item in action.inputs}
                    if declared.get(profile_ref["input"]) != "profile_ref":
                        raise MethodFailure(MethodError("METHOD_ROUTING_INVALID", "caller-supplied routing input must name an action profile_ref input", rid,
                            captures[rid].content.captured.logical_path))
        required_routes = {
            action.action_id for action in actions
            if any(item.value_kind == "profile_ref" for item in action.inputs)
        }
        if routed_actions != required_routes:
            raise MethodFailure(MethodError("METHOD_ROUTING_INVALID",
                "each action with a profile_ref input must have exactly one route and other actions must not be routed",
                path=rebuilt.source_bundle.manifest_capture.logical_path, pointer="/routing"))
        schema_ids = set(manifest["schemas"])
        schema_errors = [item for item in validate_document_schemas(rebuilt)
                         if item.resource_id in schema_ids and item.severity == "error"]
        if schema_errors:
            item = schema_errors[0]
            raise MethodFailure(MethodError(item.code, item.message, item.resource_id,
                                            item.path, item.pointer))
        return MethodResult.success(MethodDefinition(
            2, manifest["method_id"], manifest["release_version"],
            MethodRef(
                manifest["method_id"], manifest["release_version"], 2,
                method_digest("method-snapshot", {
                    "schema_version": 2,
                    "method_id": manifest["method_id"],
                    "release_version": manifest["release_version"],
                    "manifest_sha256": rebuilt.manifest_digest,
                    "resource_digests": [
                        {"id": item["id"], "sha256": item["sha256"]}
                        for item in sorted(manifest["resources"], key=lambda row: row["id"])
                    ],
                }),
            ), tuple(actions),
            tuple(refs[item] for item in manifest["criteria"]),
            tuple(refs[item] for item in manifest["prompts"]),
            tuple(refs[item] for item in manifest["templates"]),
            tuple(refs[item] for item in manifest["schemas"]),
            tuple(refs[item] for item in manifest["routing"]), tuple(refs[key] for key in sorted(refs)),
        ))
    except MethodFailure as exc:
        return MethodResult.failure(exc.error)
    except (AttributeError, TypeError, ValueError, KeyError, RecursionError):
        return MethodResult.failure(MethodError("METHOD_DEFINITION_INVALID", "typed method declaration could not be validated safely"))


__all__ = ["validate_method", "compile_method", "read_method_definition"]

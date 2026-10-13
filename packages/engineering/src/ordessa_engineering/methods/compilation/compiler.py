"""Deterministic compiler from validated source values to neutral JSON data."""
from __future__ import annotations
from .encoding import (compiled_program_from_canonical, program_to_canonical, stored_program_from_canonical)

from copy import deepcopy
from typing import Any

from ..definitions.errors import MethodError, MethodFailure, MethodResult
from ..definitions.models import (
    CompiledMethod,
    CompilationCapabilities, LoadedMethod, SourceResourceView,
)
from ..definitions.models.compiled import (
    CompiledProgram, HistoricalBoundProgram, StoredProgram, ProgramBindings, ResourceRef,
)
from ..validation.validate import validate_captured_method
from ..definitions.models.identity import method_digest


from .documents import compile_documents, compile_schema_resources
from .skills import compile_skills
from .capabilities import compile_capabilities
from .workflow import _resource_ref, _bind_refs, _first_use_order
from .decisions import _decision_order


def compile_program_from_source(loaded: LoadedMethod, compiler_version: str) -> dict[str, Any]:
    resources = loaded.resources
    workflow_resources = [item for item in resources.values() if item.declaration.get("kind") == "workflow"]
    if len(workflow_resources) != 1 or not isinstance(workflow_resources[0].value, dict):
        raise MethodFailure(MethodError("WORKFLOW_RESOURCE_INVALID", "exactly one parsed workflow resource is required"))

    if workflow_resources[0].declaration["id"] != loaded.manifest["entry"]["resource"]:
        raise MethodFailure(MethodError("MANIFEST_ENTRY_INVALID", "workflow does not match the declared entry"))

    documents = compile_documents(loaded)

    standards = [
        _bind_refs(resources[resource_id].value, resources)
        for resource_id in _first_use_order(loaded, "standard")
    ]
    decision_templates = [
        _bind_refs(resources[resource_id].value, resources)
        for resource_id in _decision_order(loaded)
    ]
    skill_resources = compile_skills(loaded)
    required_capabilities = compile_capabilities(loaded)
    # A validated catalog may contain unrelated host capabilities. Only method
    # requirements become part of this immutable program.
    return {
        "schema_version": 2,
        "compiler_version": compiler_version,
        "workflow": _bind_refs(workflow_resources[0].value, resources),
        "documents": documents,
        "schema_resources": compile_schema_resources(loaded),
        "standards": standards,
        "decision_templates": decision_templates,
        "skill_resources": skill_resources,
        "capability_bindings": required_capabilities,
    }


def bind_program(encoding: StoredProgram, loaded: LoadedMethod) -> CompiledProgram | HistoricalBoundProgram:
    """Materialize exact identities from explicit, verified source captures."""
    standards = []
    decisions = []
    for resource_id in _first_use_order(loaded, "standard"):
        resource = loaded.resources[resource_id]
        standards.append((resource.value["standard_id"], ResourceRef(**_resource_ref(resource))))
    for resource_id in _decision_order(loaded):
        resource = loaded.resources[resource_id]
        decisions.append((resource.value["question_set_id"], ResourceRef(**_resource_ref(resource))))
    bindings = ProgramBindings(tuple(standards), tuple(decisions))
    if encoding.schema_version == 1:
        return HistoricalBoundProgram(encoding, bindings)
    return compiled_program_from_canonical(program_to_canonical(encoding), bindings)


def _compile_captured_method(loaded: LoadedMethod, capabilities: CompilationCapabilities,
                   compiler_version: str) -> MethodResult[CompiledMethod]:
    if not isinstance(compiler_version, str) or not compiler_version.strip():
        return MethodResult.failure(MethodError("COMPILER_VERSION_INVALID", "compiler version must be a non-empty string"))
    try:
        capabilities = deepcopy(capabilities)
    except MethodFailure as exc:
        return MethodResult.failure(exc.error)
    except (AttributeError, TypeError, ValueError, KeyError):
        return MethodResult.failure(MethodError("LOADED_PROJECTION_INVALID", "loaded method projection could not be verified against captured bytes"))
    try:
        report = validate_captured_method(loaded, capabilities)
    except (AttributeError, KeyError, TypeError, ValueError):
        return MethodResult.failure(MethodError("METHOD_VALIDATION_FAILED", "method validation failed safely"))
    if not report.valid:
        first = next(item for item in report.diagnostics if item.severity == "error")
        return MethodResult.failure(MethodError(first.code, first.message, first.resource_id, first.path, first.pointer))
    try:
        program = compile_program_from_source(loaded, compiler_version)
        plan_digest = method_digest("compiled-method-program", program)
        workflow = program["workflow"]
        standards = program["standards"]
        decisions = program["decision_templates"]
        documents = program["documents"]
        skills = program["skill_resources"]
        compiled = CompiledMethod(loaded.source_bundle, loaded.parsed_source, bind_program(stored_program_from_canonical(program), loaded), report.diagnostics)
        if (loaded.bundle_lock is not None and loaded.compiled_golden is not None
                and loaded.compiled_golden.get("compiler_version") == compiler_version):
            expected = loaded.bundle_lock.get("compiled_plan_digest", {}).get("hex")
            if expected and expected != plan_digest:
                return MethodResult.failure(MethodError(
                    "COMPILED_GOLDEN_MISMATCH", "compiled program differs from the pinned design golden",
                    path=loaded.bundle_lock.get("compiled_plan_path"),
                ))
            if loaded.compiled_golden is not None and loaded.compiled_golden != program:
                return MethodResult.failure(MethodError(
                    "COMPILED_GOLDEN_MISMATCH", "compiled program differs from the pinned design golden",
                    path=loaded.bundle_lock.get("compiled_plan_path"),
                ))
        return MethodResult.success(compiled)
    except MethodFailure as exc:
        return MethodResult.failure(exc.error)
    except (AttributeError, KeyError, TypeError, ValueError):
        return MethodResult.failure(MethodError("METHOD_COMPILE_FAILED", "method compilation failed safely"))

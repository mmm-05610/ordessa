"""Bundle and injected host-catalog compatibility validation."""
from __future__ import annotations

from collections.abc import Mapping

from ..definitions.contracts.validation import ValidationReport
from ..definitions.models.identity import method_digest
from ..definitions.errors import Diagnostic
from ..definitions.models import CapabilityDescriptor, CompilationCapabilities, LoadedMethod, LoadLimits
from .structure import validate_manifest_sections, validate_resource_structure
from .workflow import validate_workflow
from .schema import (
    validate_document_schemas, validate_question_sets, validate_resources,
    validate_standard_resources,
)
from .policies import validate_policies


def _capability_map(capabilities: CompilationCapabilities) -> tuple[dict[str, CapabilityDescriptor], list[Diagnostic]]:
    result: dict[str, CapabilityDescriptor] = {}
    diagnostics: list[Diagnostic] = []
    for descriptor in capabilities.capabilities:
        if descriptor.capability_id in result:
            diagnostics.append(Diagnostic(
                "DUPLICATE_HOST_CAPABILITY", "error",
                "host catalog contains a duplicate capability ID",
                pointer=f"/capabilities/{descriptor.capability_id}",
            ))
            continue
        if descriptor.kind not in {"operation", "check"}:
            diagnostics.append(Diagnostic(
                "CAPABILITY_KIND_INVALID", "error", "capability kind must be operation or check",
                pointer=f"/capabilities/{descriptor.capability_id}/kind",
            ))
        if not descriptor.capability_id or not descriptor.interface_version:
            diagnostics.append(Diagnostic(
                "CAPABILITY_DESCRIPTOR_INVALID", "error", "capability ID and interface version are required",
            ))
        if not isinstance(descriptor.contract, Mapping):
            diagnostics.append(Diagnostic(
                "CAPABILITY_CONTRACT_INVALID", "error", "capability contract must be a JSON object",
                pointer=f"/capabilities/{descriptor.capability_id}/contract",
            ))
            result[descriptor.capability_id] = descriptor
            continue
        try:
            actual = method_digest("capability-contract", descriptor.contract)
        except (TypeError, ValueError):
            actual = ""
        if actual != descriptor.contract_digest:
            diagnostics.append(Diagnostic(
                "CAPABILITY_CONTRACT_DIGEST_MISMATCH", "error",
                "host capability descriptor contract digest is invalid",
                pointer=f"/capabilities/{descriptor.capability_id}/contract_digest",
            ))
        result[descriptor.capability_id] = descriptor
    return result, diagnostics


def validate_compatibility(loaded: LoadedMethod, capabilities: CompilationCapabilities,
                           limits: LoadLimits | None = None) -> ValidationReport:
    limits = limits or loaded.load_limits
    diagnostics = validate_manifest_sections(loaded.manifest, loaded.resources)
    for resource_id, resource in loaded.resources.items():
        diagnostics.extend(validate_resource_structure(resource.value, resource.declaration["kind"], resource.captured.logical_path, resource_id))
    if diagnostics:
        return ValidationReport(False, "structural", tuple(diagnostics), registry_snapshot_ref=capabilities.registry_snapshot_ref)
    catalog, catalog_errors = _capability_map(capabilities)
    diagnostics.extend(catalog_errors)

    requirements = loaded.manifest.get("requires", [])
    required_ids: set[str] = set()
    for index, requirement in enumerate(requirements if isinstance(requirements, list) else []):
        if not isinstance(requirement, dict):
            continue
        capability_id = requirement.get("capability_id")
        if not isinstance(capability_id, str):
            continue
        required_ids.add(capability_id)
        descriptor = catalog.get(capability_id)
        pointer = f"/requires/{index}"
        if descriptor is None:
            diagnostics.append(Diagnostic(
                "UNKNOWN_CAPABILITY", "error", f"required capability is unavailable: {capability_id}",
                path="method.yaml", pointer=pointer,
            ))
            continue
        for key, actual in (("kind", descriptor.kind), ("interface_version", descriptor.interface_version),
                            ("contract_digest", descriptor.contract_digest)):
            if requirement.get(key) != actual:
                diagnostics.append(Diagnostic(
                    "CAPABILITY_REQUIREMENT_MISMATCH", "error",
                    f"required capability {key} differs from the injected host descriptor",
                    path="method.yaml", pointer=f"{pointer}/{key}",
                ))

    # Resource declarations that reference a capability are checked against the
    # injected catalog too; the design-fixture catalog is never loaded as trust.
    for resource_id, resource in loaded.resources.items():
        value = resource.value
        if resource.declaration.get("kind") == "standard" and isinstance(value, dict):
            for criterion_index, criterion in enumerate(value.get("criteria", []) if isinstance(value.get("criteria"), list) else []):
                checks = criterion.get("checks", []) if isinstance(criterion, dict) else []
                for check_index, check in enumerate(checks if isinstance(checks, list) else []):
                    capability_id = check.get("capability_id") if isinstance(check, dict) else None
                    if not isinstance(capability_id, str) or capability_id not in catalog:
                        diagnostics.append(Diagnostic(
                            "UNKNOWN_CAPABILITY", "error", f"standard check capability unavailable: {capability_id}",
                            resource_id, resource.captured.logical_path,
                            f"/criteria/{criterion_index}/checks/{check_index}/capability_id",
                        ))
                    else:
                        pointer = f"/criteria/{criterion_index}/checks/{check_index}"
                        descriptor = catalog[capability_id]
                        if capability_id not in required_ids:
                            diagnostics.append(Diagnostic(
                                "CAPABILITY_NOT_DECLARED", "error", "standard check capability must be declared in method.yaml requires",
                                resource_id, resource.captured.logical_path,
                                f"{pointer}/capability_id",
                            ))
                        if descriptor.kind != "check":
                            diagnostics.append(Diagnostic(
                                "CAPABILITY_KIND_MISMATCH", "error", "standard check points to a non-check capability",
                                resource_id, resource.captured.logical_path,
                                f"{pointer}/capability_id",
                            ))
                        version = check.get("interface_version")
                        if not isinstance(version, str) or not version:
                            diagnostics.append(Diagnostic(
                                "CHECK_INTERFACE_VERSION_INVALID", "error", "standard check requires a non-empty interface version",
                                resource_id, resource.captured.logical_path,
                                f"{pointer}/interface_version",
                            ))
                        elif version != descriptor.interface_version:
                            diagnostics.append(Diagnostic(
                                "CHECK_INTERFACE_VERSION_MISMATCH", "error", "standard check interface version differs from the injected capability",
                                resource_id, resource.captured.logical_path,
                                f"{pointer}/interface_version",
                            ))

    diagnostics.extend(validate_resources(loaded))
    diagnostics.extend(validate_document_schemas(loaded))
    diagnostics.extend(validate_standard_resources(loaded))
    diagnostics.extend(validate_policies(loaded))
    diagnostics.extend(validate_question_sets(loaded, limits))
    diagnostics.extend(validate_workflow(loaded, catalog, limits))
    if capabilities.trust_class not in {"host", "fixture"}:
        diagnostics.append(Diagnostic("TRUST_CLASS_INVALID", "error", "unknown capability catalog trust class"))
    elif capabilities.trust_class == "fixture":
        diagnostics.append(Diagnostic(
            "FIXTURE_CAPABILITIES_ONLY", "warning",
            "fixture capability bindings are not production host trust",
        ))
    errors = any(item.severity == "error" for item in diagnostics)
    return ValidationReport(
        valid=not errors,
        phase="compatibility",
        diagnostics=tuple(diagnostics),
        registry_snapshot_ref=capabilities.registry_snapshot_ref,
    )

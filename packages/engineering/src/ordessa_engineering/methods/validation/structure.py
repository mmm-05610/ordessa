"""Local format checks; no loading dependency or source access."""
from typing import Any
import re
from jsonschema import Draft202012Validator
from ..definitions.errors import Diagnostic, MethodError, MethodFailure
from ..definitions.schemas import (MANIFEST_FIELDS_V1, MANIFEST_REQUIRED_FIELDS_V1, MANIFEST_SCHEMA_VERSION_V1, COMPILER_CONTRACT_V1, RESOURCE_FIELDS_V1, RESOURCE_KINDS_V1, RESOURCE_DIGEST_PATTERN_V1, MANIFEST_SECTIONS_SCHEMA_V1, RESOURCE_STRUCTURES_V1, METHOD_SCHEMA_VERSION_V2, METHOD_DEFINITION_SCHEMA_V2, RESOURCE_KINDS_V2, RESOURCE_STRUCTURES_V2)
_RESOURCE_DIGEST_V1 = re.compile(RESOURCE_DIGEST_PATTERN_V1)

def valid_resource_digest(value: Any) -> bool:
    """V1 source declaration digest syntax (not content verification)."""
    return isinstance(value, str) and _RESOURCE_DIGEST_V1.fullmatch(value) is not None


def validate_manifest_structure(value: Any, *, manifest_path: str = "method.yaml") -> dict[str, Any]:
    """Check the existing V1 envelope, returning the same unmodified mapping.

    Nested declarations are checked at their original loading stages so an
    invalid later declaration cannot move ahead of earlier read/path failures.
    """
    if not isinstance(value, dict):
        raise MethodFailure(MethodError("MANIFEST_INVALID", "method manifest must be an object", path=manifest_path))
    if type(value.get("schema_version")) is int and value.get("schema_version") == METHOD_SCHEMA_VERSION_V2:
        errors = sorted(Draft202012Validator(METHOD_DEFINITION_SCHEMA_V2).iter_errors(value),
                        key=lambda error: tuple(str(part) for part in error.absolute_path))
        if errors:
            first = errors[0]
            pointer = "/" + "/".join(str(part).replace("~", "~0").replace("/", "~1")
                                      for part in first.absolute_path)
            raise MethodFailure(MethodError("METHOD_DEFINITION_INVALID",
                "schema-2 method declaration violates its closed structure",
                path=manifest_path, pointer=pointer))
        return value
    if value.get("schema_version") == METHOD_SCHEMA_VERSION_V2:
        raise MethodFailure(MethodError("METHOD_SCHEMA_UNSUPPORTED", "unsupported method schema version", path=manifest_path))
    extra = set(value) - MANIFEST_FIELDS_V1
    missing = MANIFEST_REQUIRED_FIELDS_V1 - set(value)
    if extra or missing:
        raise MethodFailure(MethodError("MANIFEST_FIELDS_INVALID", f"unknown fields={sorted(extra)} missing={sorted(missing)}", path=manifest_path))
    if value.get("schema_version") != MANIFEST_SCHEMA_VERSION_V1 or type(value.get("schema_version")) is not int:
        raise MethodFailure(MethodError("METHOD_SCHEMA_UNSUPPORTED", "unsupported method manifest schema", path=manifest_path))
    for field in ("method_id", "release_version", "compiler_contract"):
        if not isinstance(value.get(field), str) or not value[field]:
            raise MethodFailure(MethodError("MANIFEST_FIELD_INVALID", f"{field} must be a non-empty string", path=manifest_path, pointer=f"/{field}"))
    if value["compiler_contract"] != COMPILER_CONTRACT_V1:
        raise MethodFailure(MethodError("COMPILER_CONTRACT_UNSUPPORTED", "method bundle compiler contract is unsupported", path=manifest_path, pointer="/compiler_contract"))
    return value


def validate_resource_fields(declaration: Any, *, manifest_path: str, pointer: str,
                             schema_version: int = MANIFEST_SCHEMA_VERSION_V1) -> None:
    if not isinstance(declaration, dict):
        raise MethodFailure(MethodError("RESOURCE_DECLARATION_INVALID", "resource declaration must be an object", path=manifest_path, pointer=pointer))
    if set(declaration) != RESOURCE_FIELDS_V1:
        raise MethodFailure(MethodError("RESOURCE_DECLARATION_FIELDS_INVALID", "resource declaration fields must be exactly id, kind, path, media_type, and sha256", path=manifest_path, pointer=pointer))


def validate_resource_values(declaration: dict[str, Any], *, manifest_path: str, pointer: str,
                             schema_version: int = MANIFEST_SCHEMA_VERSION_V1) -> None:
    """Called after path/ID checks to preserve loading error precedence."""
    resource_id = declaration.get("id")
    kind = declaration.get("kind")
    media_type = declaration.get("media_type")
    if not isinstance(kind, str) or not isinstance(media_type, str) or not media_type:
        raise MethodFailure(MethodError("RESOURCE_DECLARATION_INVALID", "resource kind and media type are required", resource_id=resource_id, path=manifest_path, pointer=pointer))
    supported_kinds = RESOURCE_KINDS_V2 if schema_version == METHOD_SCHEMA_VERSION_V2 else RESOURCE_KINDS_V1
    if kind not in supported_kinds:
        raise MethodFailure(MethodError("RESOURCE_KIND_UNSUPPORTED", "resource kind is not supported", resource_id=resource_id, path=manifest_path, pointer=f"{pointer}/kind"))
    if not valid_resource_digest(declaration.get("sha256")):
        raise MethodFailure(MethodError("RESOURCE_DIGEST_INVALID", "resource digest must be lowercase SHA-256", resource_id=resource_id, path=manifest_path, pointer=f"{pointer}/sha256"))


def validate_entry_structure(entry: Any, *, manifest_path: str) -> None:
    if (not isinstance(entry, dict) or set(entry) != {"resource"}
            or not isinstance(entry.get("resource"), str)):
        raise MethodFailure(MethodError("MANIFEST_ENTRY_INVALID", "manifest entry must name exactly one workflow resource", path=manifest_path, pointer="/entry"))


def validate_requires_structure(requires: Any, *, manifest_path: str) -> None:
    if not isinstance(requires, list):
        raise MethodFailure(MethodError("REQUIRES_INVALID", "requires must be a list", path=manifest_path, pointer="/requires"))


def validate_requirement_structure(requirement: Any, *, manifest_path: str, pointer: str) -> None:
    if not isinstance(requirement, dict):
        raise MethodFailure(MethodError("REQUIRES_INVALID", "capability requirement must be an object", path=manifest_path, pointer=pointer))


def _structure_errors(value: Any, schema: dict, *, path: str, resource_id: str | None = None) -> list[Diagnostic]:
    result = []
    for error in sorted(Draft202012Validator(schema).iter_errors(value), key=lambda e: str(list(e.absolute_path))):
        pointer = "/" + "/".join(str(part).replace("~", "~0").replace("/", "~1") for part in error.absolute_path)
        code = "METHOD_STRUCTURE_INVALID"
        parts = list(error.absolute_path)
        if ("checks" in parts and (parts[-1:] == ["interface_version"]
                or (error.validator == "required" and isinstance(error.instance, dict)
                    and "interface_version" not in error.instance))):
            code = "CHECK_INTERFACE_VERSION_INVALID"
            if error.validator == "required":
                pointer += "/interface_version"
        # Do not echo resource data, secret keys or schema values into diagnostics.
        result.append(Diagnostic(code, "error", "method declaration violates the supported structure",
                                 resource_id, path, pointer))
    return result


def validate_manifest_sections(manifest: Any, resources: Any) -> list[Diagnostic]:
    """Validate current declarations; resource relationships are checked elsewhere."""
    return _structure_errors(manifest, MANIFEST_SECTIONS_SCHEMA_V1, path="method.yaml")


def validate_resource_structure(value: Any, kind: str, path: str, resource_id: str) -> list[Diagnostic]:
    schema = RESOURCE_STRUCTURES_V2.get(kind) or RESOURCE_STRUCTURES_V1.get(kind)
    return _structure_errors(value, schema, path=path, resource_id=resource_id) if schema else []

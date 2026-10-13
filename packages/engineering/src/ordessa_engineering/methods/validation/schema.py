"""Static JSON Schema checks; no schema resolver may access the network."""
from __future__ import annotations

from typing import Any
from urllib.parse import unquote, urlsplit

from jsonschema import Draft202012Validator, SchemaError

from ..definitions.errors import Diagnostic
from ..definitions.models import LoadedMethod
from ..definitions.schemas import DRAFT_2020_12
from .references import validate_schema_refs


_SCHEMA_MAP_KEYWORDS = frozenset({"$defs", "properties", "patternProperties", "dependentSchemas"})
_SCHEMA_SINGLE_KEYWORDS = frozenset({
    "additionalProperties", "unevaluatedProperties", "propertyNames",
    "contains", "not", "if", "then", "else", "contentSchema", "items",
    "unevaluatedItems",
})
_SCHEMA_ARRAY_KEYWORDS = frozenset({"allOf", "anyOf", "oneOf", "prefixItems"})


def _schema_nodes(schema: object, pointer: str = ""):
    """Yield actual subschemas, skipping arbitrary example/default payloads."""
    if not isinstance(schema, dict):
        return
    yield schema, pointer
    for keyword in _SCHEMA_MAP_KEYWORDS:
        children = schema.get(keyword)
        if isinstance(children, dict):
            for name, child in children.items():
                if isinstance(child, dict):
                    escaped = str(name).replace("~", "~0").replace("/", "~1")
                    yield from _schema_nodes(child, f"{pointer}/{keyword}/{escaped}")
    for keyword in _SCHEMA_SINGLE_KEYWORDS:
        child = schema.get(keyword)
        if isinstance(child, dict):
            yield from _schema_nodes(child, f"{pointer}/{keyword}")
    for keyword in _SCHEMA_ARRAY_KEYWORDS:
        children = schema.get(keyword)
        if isinstance(children, list):
            for index, child in enumerate(children):
                if isinstance(child, dict):
                    yield from _schema_nodes(child, f"{pointer}/{keyword}/{index}")


def _is_reserved_core_id(identifier: str) -> bool:
    if identifier.lower().startswith("urn:ordessa:schema:"):
        return True
    try:
        parts = urlsplit(identifier)
    except ValueError:
        return False
    try:
        hostname = (parts.hostname or "").lower()
        port = parts.port
    except ValueError:
        # An invalid explicit port does not make a core host namespace safe
        # to claim; continue with the parsed host and path checks below.
        hostname = (parts.hostname or "").lower()
        port = -1
    if parts.scheme.lower() != "https" or hostname != "ordessa.invalid":
        return False
    path = unquote(parts.path)
    reserved_path = path.startswith(("/interfaces/", "/design/interfaces/"))
    return reserved_path and (port in (None, 443) or port == -1)


def validate_document_schemas(loaded: LoadedMethod) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    for resource_id, resource in loaded.resources.items():
        if resource.declaration.get("kind") != "document_schema":
            continue
        schema = resource.value
        if not isinstance(schema, dict):
            diagnostics.append(Diagnostic("SCHEMA_INVALID", "error", "document schema must be an object", resource_id, resource.captured.logical_path))
            continue
        for schema_node, pointer in _schema_nodes(schema):
            dialect = schema_node.get("$schema")
            if dialect is not None and dialect != DRAFT_2020_12:
                diagnostics.append(Diagnostic(
                    "SCHEMA_DRAFT_UNSUPPORTED", "error",
                    "document schemas use JSON Schema Draft 2020-12",
                    resource_id, resource.captured.logical_path,
                    f"{pointer}/$schema",
                ))
            identifier = schema_node.get("$id")
            if isinstance(identifier, str) and _is_reserved_core_id(identifier):
                diagnostics.append(Diagnostic(
                    "SCHEMA_ID_RESERVED", "error",
                    "document schema IDs cannot occupy Ordessa core interface namespaces",
                    resource_id, resource.captured.logical_path,
                    f"{pointer}/$id",
                ))
        bundled_schemas = {
            other_id: (other.captured.logical_path, other.value)
            for other_id, other in loaded.resources.items()
            if other.declaration.get("kind") == "document_schema"
        }
        for error in validate_schema_refs(
            schema, resource_id=resource_id,
            path=resource.captured.logical_path, schemas=bundled_schemas,
        ):
            diagnostics.append(Diagnostic(error.code, "error", error.message, error.resource_id, error.path, error.pointer))
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            path = "/" + "/".join(str(part) for part in exc.absolute_path)
            diagnostics.append(Diagnostic("SCHEMA_INVALID", "error", "document schema is invalid", resource_id, resource.captured.logical_path, path))

    document_types: set[str] = set()
    for index, document in enumerate(loaded.manifest.get("documents", [])):
        pointer = f"/documents/{index}"
        document_type = document["document_type"]
        if document_type in document_types:
            diagnostics.append(Diagnostic("DUPLICATE_DOCUMENT_TYPE", "error", "document_type is duplicated", path="method.yaml", pointer=f"{pointer}/document_type"))
        document_types.add(document_type)
        for field, expected_kind in (("schema", "document_schema"), ("template", "document_template")):
            if field not in document:
                continue
            resource_id = document[field]["resource"]
            resource = loaded.resources.get(resource_id)
            if resource is None or resource.declaration.get("kind") != expected_kind:
                diagnostics.append(Diagnostic("DOCUMENT_SCHEMA_REF_INVALID" if field == "schema" else "DOCUMENT_TEMPLATE_REF_INVALID", "error", f"document {field} must reference a {expected_kind} resource", resource_id, path="method.yaml", pointer=f"{pointer}/{field}"))
    for role, reference in loaded.manifest.get("skills", {}).items():
        resource_id = reference["resource"]
        resource = loaded.resources.get(resource_id)
        if resource is None or resource.declaration.get("kind") != "skill":
            diagnostics.append(Diagnostic("SKILL_REF_INVALID", "error", "role must reference a skill resource", resource_id, path="method.yaml", pointer=f"/skills/{role}"))

    return diagnostics


def validate_resources(loaded: LoadedMethod) -> list[Diagnostic]:
    from ..validation.references import validate_resource_references

    diagnostics: list[Diagnostic] = []
    declarations = {key: dict(value.declaration) for key, value in loaded.resources.items()}
    for resource_id, resource in loaded.resources.items():
        if resource.value is None:
            continue
        for error in validate_resource_references(resource.value, declarations, path=resource.captured.logical_path):
            diagnostics.append(Diagnostic(error.code, "error", error.message, resource_id, error.path, error.pointer))
    for error in validate_resource_references(loaded.manifest, declarations, path="method.yaml"):
        diagnostics.append(Diagnostic(error.code, "error", error.message, error.resource_id, error.path, error.pointer))
    return diagnostics


def validate_standard_resources(loaded: LoadedMethod) -> list[Diagnostic]:
    """Check local identity uniqueness; shapes are defined in definitions."""
    diagnostics: list[Diagnostic] = []
    standard_ids: set[str] = set()
    for resource_id, resource in loaded.resources.items():
        if resource.declaration.get("kind") != "standard":
            continue
        standard = resource.value
        if standard["standard_id"] in standard_ids:
            diagnostics.append(Diagnostic("DUPLICATE_STANDARD_ID", "error", "standard identity is duplicated", resource_id, resource.captured.logical_path))
        standard_ids.add(standard["standard_id"])
        ids: set[str] = set()
        for index, criterion in enumerate(standard["criteria"]):
            if criterion["criterion_id"] in ids:
                diagnostics.append(Diagnostic("DUPLICATE_CRITERION", "error", "criterion ID is duplicated", resource_id, resource.captured.logical_path, f"/criteria/{index}"))
            ids.add(criterion["criterion_id"])
        for index, criterion in enumerate(standard["criteria"]):
            for check_index, check in enumerate(criterion["checks"]):
                bindings = check["bindings"]
                if "question_set" not in bindings:
                    continue
                pointer = f"/criteria/{index}/checks/{check_index}/bindings"
                ref = bindings["question_set"]
                resource_ref = ref.get("resource") if isinstance(ref, dict) else None
                question_resource = loaded.resources.get(resource_ref) if isinstance(resource_ref, str) else None
                if question_resource is None or question_resource.declaration.get("kind") != "question_set":
                    diagnostics.append(Diagnostic("QUESTION_SET_REF_INVALID", "error", "check binding must reference a question_set", resource_id, resource.captured.logical_path, pointer))
                    continue
                question_set = question_resource.value
                question_ids = bindings.get("question_ids")
                available = {question["question_id"] for question in question_set["questions"]}
                if question_ids is not None and (not isinstance(question_ids, list) or not question_ids or any(not isinstance(item, str) or item not in available for item in question_ids) or len(question_ids) != len(set(question_ids))):
                    diagnostics.append(Diagnostic("QUESTION_BINDING_INVALID", "error", "bound question IDs must exist and be unique", resource_id, resource.captured.logical_path, pointer))
                if "iteration" in bindings and bindings["iteration"] != question_set["iteration"]:
                    diagnostics.append(Diagnostic("QUESTION_ITERATION_MISMATCH", "error", "check iteration must match its question set", resource_id, resource.captured.logical_path, pointer))
                selected = question_ids if isinstance(question_ids, list) else available
                for question in question_set["questions"]:
                    if question["question_id"] not in selected:
                        continue
                    answer = question["answer_definition"]["from_criterion"]
                    if (answer["resource"], answer["criterion_id"]) != (resource_id, criterion["criterion_id"]):
                        diagnostics.append(Diagnostic("QUESTION_CRITERION_BINDING_MISMATCH", "error", "decision check must bind questions using its own criterion vocabulary", resource_id, resource.captured.logical_path, pointer))
    return diagnostics


def validate_question_sets(loaded: LoadedMethod, limits) -> list[Diagnostic]:
    diagnostics: list[Diagnostic] = []
    criteria: dict[tuple[str, str], dict[str, Any]] = {}
    for resource_id, resource in loaded.resources.items():
        if resource.declaration.get("kind") == "standard" and isinstance(resource.value, dict):
            for criterion in resource.value.get("criteria", []):
                if isinstance(criterion, dict) and isinstance(criterion.get("criterion_id"), str):
                    criteria[(resource_id, criterion["criterion_id"])] = criterion
    threshold_keys = {"threshold", "decision_policy", "minimum_selected_probability", "minimum_top_level_probability", "minimum_expected_index", "maximum_p_true"}

    def inspect_thresholds(value: Any, resource_id: str, path: str, pointer: str = "") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in threshold_keys:
                    diagnostics.append(Diagnostic("THRESHOLD_IN_QUESTION_SET", "error", "decision thresholds belong to standards, not question sets", resource_id, path, f"{pointer}/{key}"))
                inspect_thresholds(child, resource_id, path, f"{pointer}/{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                inspect_thresholds(child, resource_id, path, f"{pointer}/{index}")

    for resource_id, resource in loaded.resources.items():
        if resource.declaration.get("kind") != "question_set":
            continue
        question_set = resource.value
        path = resource.captured.logical_path
        questions = question_set["questions"]
        if len(questions) > limits.question_count:
            diagnostics.append(Diagnostic("QUESTION_COUNT_EXCEEDED", "error", "question set exceeds its static question limit", resource_id, path, "/questions"))
        inspect_thresholds(question_set, resource_id, path)
        ids: set[str] = set()
        for index, question in enumerate(questions):
            pointer = f"/questions/{index}"
            if question["question_id"] in ids:
                diagnostics.append(Diagnostic("DUPLICATE_QUESTION_ID", "error", "question IDs must be unique in a set", resource_id, path, f"{pointer}/question_id"))
            ids.add(question["question_id"])
            for criterion_ref in question.get("criterion_refs", []):
                if not isinstance(criterion_ref, dict) or (criterion_ref.get("resource"), criterion_ref.get("criterion_id")) not in criteria:
                    diagnostics.append(Diagnostic("UNKNOWN_CRITERION", "error", "question references an unknown criterion", resource_id, path, f"{pointer}/criterion_refs"))
            refs = {(ref["resource"], ref["criterion_id"]) for ref in question["criterion_refs"]}
            source = question["answer_definition"]["from_criterion"]
            if (source["resource"], source["criterion_id"]) not in refs:
                diagnostics.append(Diagnostic("ANSWER_CRITERION_NOT_DECLARED", "error", "answer source must be among the question criterion references", resource_id, path, f"{pointer}/answer_definition"))
            answer_from = question.get("answer_definition", {}).get("from_criterion") if isinstance(question.get("answer_definition"), dict) else None
            if isinstance(answer_from, dict):
                criterion = criteria.get((answer_from.get("resource"), answer_from.get("criterion_id")))
                if criterion is None:
                    diagnostics.append(Diagnostic("UNKNOWN_CRITERION", "error", "answer definition references an unknown criterion", resource_id, path, f"{pointer}/answer_definition/from_criterion"))
                else:
                    vocabulary = criterion.get("answer_vocabulary", {})
                    if not isinstance(vocabulary, dict) or vocabulary.get("kind") != question.get("kind"):
                        diagnostics.append(Diagnostic("QUESTION_VOCABULARY_MISMATCH", "error", "question and criterion answer types differ", resource_id, path, f"{pointer}/kind"))
    return diagnostics


# Pure content checking, using application-supplied program projection.
from copy import deepcopy
from collections.abc import Mapping
from urllib.parse import urljoin
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012
from referencing.exceptions import Unresolvable
from jsonschema.exceptions import SchemaError
from ..definitions.errors import MethodError, MethodFailure, MethodResult
from ..definitions.models import MethodSnapshot
from .values import validate_json_value

def _no_retrieval(uri):
    raise ValueError("external schema retrieval is unavailable")


def validate_document_content_data(snapshot: MethodSnapshot, document_type: str, method_content: Mapping, program: dict) -> MethodResult[None]:
    """The argument is a neutral wrapper; only its value is schema-validated."""
    try:
        matches = [item for item in program["documents"] if item["document_type"] == document_type]
        if len(matches) != 1:
            raise MethodFailure(MethodError("DOCUMENT_TYPE_UNAVAILABLE", "document type has no unique method binding"))
        if matches[0]["validation_target"] != "method_content":
            raise MethodFailure(MethodError("VALIDATION_TARGET_UNSUPPORTED", "only method_content.value is supported"))
        if not isinstance(method_content, Mapping) or "value" not in method_content:
            raise MethodFailure(MethodError("METHOD_CONTENT_INVALID", "method content must carry a value"))
        value = method_content["value"]
        validate_json_value(value, path="method_content.value")
        registry = Registry(retrieve=_no_retrieval)
        locations = {item.resource_id: item.logical_path for item in snapshot.resources}
        selected = None
        for item in program["schema_resources"]:
            location = "https://ordessa.invalid/method/" + locations[item["schema_resource"]["resource_id"]]
            schema = deepcopy(item["value_schema"])
            schema["$id"] = urljoin(location, schema.get("$id", location))
            resource = Resource.from_contents(schema, default_specification=DRAFT202012)
            registry = registry.with_resource(location, resource).with_resource(schema["$id"], resource)
            if item["schema_resource"] == next(doc["schema_resource"] for doc in program["documents"] if doc["document_type"] == document_type):
                selected = schema
        if not Draft202012Validator(selected, registry=registry.crawl()).is_valid(value):
            raise MethodFailure(MethodError("METHOD_CONTENT_INVALID", "method_content.value violates its document schema"))
        return MethodResult.success(None)
    except MethodFailure as exc:
        return MethodResult.failure(exc.error)
    except (ValueError, TypeError, KeyError, AttributeError, RecursionError, LookupError, Unresolvable, SchemaError):
        return MethodResult.failure(MethodError("METHOD_SCHEMA_INVALID", "document content could not be validated safely"))

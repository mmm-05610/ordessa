"""V1 declaration data only; no parsing or validator execution."""
from ..defaults import CRITERION_DEFAULTS_V1, DOCUMENT_VALIDATION_TARGET_DEFAULT_V1

MANIFEST_SCHEMA_VERSION_V1 = 1
COMPILER_CONTRACT_V1 = "ordessa.methods/v1"
DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
MANIFEST_FIELDS_V1 = frozenset({
    "schema_version", "method_id", "release_version", "display_name",
    "compiler_contract", "entry", "documents", "skills", "resources",
    "requires", "supporting_fixture_path", "metadata",
})
MANIFEST_REQUIRED_FIELDS_V1 = frozenset({
    "schema_version", "method_id", "release_version", "compiler_contract",
    "entry", "resources", "requires",
})
RESOURCE_FIELDS_V1 = frozenset({"id", "kind", "path", "media_type", "sha256"})
RESOURCE_KINDS_V1 = frozenset({
    "workflow", "document_schema", "document_template", "standard", "question_set", "skill",
})
RESOURCE_DIGEST_PATTERN_V1 = r"^[0-9a-f]{64}$"

# Structure is defined here; cross-resource resolution and safety semantics
# remain validation algorithms. JSON Schema documents in an external method
# are data and are intentionally not constrained to these declaration fields.
def _object(properties: dict, required: tuple = ()) -> dict:
    return {"type": "object", "properties": properties,
            "required": list(required), "additionalProperties": False}


_TEXT = {"type": "string", "minLength": 1}
_TEXTS = {"type": "array", "items": _TEXT, "uniqueItems": True}
_MAP = {"type": "object"}
RESOURCE_REF_SCHEMA_V1 = _object({"resource": _TEXT}, ("resource",))
CRITERION_REF_SCHEMA_V1 = _object({"resource": _TEXT, "criterion_id": _TEXT}, ("resource", "criterion_id"))
_STR_MAP = {"type": "object", "additionalProperties": _TEXT}
CHECK_STATUSES_V1 = ("satisfied", "violated", "insufficient", "unknown")
DISPOSITIONS_V1 = ("pass", "block", "manual", "insufficient")
QUESTION_KINDS_V1 = ("choice", "score", "noul")
QUESTION_ITERATIONS_V1 = ("once", "each_evidence_required_claim")
_DISPOSITION = {"enum": list(DISPOSITIONS_V1)}
_DECIMAL = {"type": "string", "pattern": r"^(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z"}
DOCUMENT_SCHEMA_V1 = _object({
    "document_type": _TEXT, "schema": RESOURCE_REF_SCHEMA_V1,
    "template": RESOURCE_REF_SCHEMA_V1, "validation_target": {"const": DOCUMENT_VALIDATION_TARGET_DEFAULT_V1},
}, ("document_type", "schema"))
MANIFEST_SECTIONS_SCHEMA_V1 = _object({
    "schema_version": {"type": "integer", "const": 1},
    "method_id": _TEXT, "release_version": _TEXT,
    "compiler_contract": {"const": COMPILER_CONTRACT_V1}, "display_name": _TEXT,
    "entry": RESOURCE_REF_SCHEMA_V1,
    "documents": {"type": "array", "items": DOCUMENT_SCHEMA_V1},
    "skills": {"type": "object", "propertyNames": _TEXT,
               "additionalProperties": RESOURCE_REF_SCHEMA_V1},
    "resources": {"type": "array", "minItems": 1, "items": _object({
        "id": _TEXT, "kind": {"enum": sorted(RESOURCE_KINDS_V1)}, "path": _TEXT,
        "media_type": _TEXT, "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    }, tuple(sorted(RESOURCE_FIELDS_V1)))},
    "requires": {"type": "array", "items": _object({
        "capability_id": _TEXT, "kind": {"enum": ["operation", "check"]},
        "interface_version": _TEXT, "contract_digest": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    }, ("capability_id", "kind", "interface_version", "contract_digest"))},
    "supporting_fixture_path": _TEXT, "metadata": _MAP,
}, tuple(sorted(MANIFEST_REQUIRED_FIELDS_V1)))
_TRANSITION = {"oneOf": [_object({key: _TEXT}, (key,)) for key in ("next", "wait", "stop")]}
_NODE_SCHEMAS = [
    _object({"id": _TEXT, "kind": {"const": "operation"}, "operation": _TEXT,
             "inputs": _STR_MAP, "config": _MAP,
             "result_routing": _object({"path": _TEXT, "outcomes": {"type":"object", "minProperties":1,
                 "additionalProperties":_TRANSITION}}, ("path", "outcomes")),
             "outcomes": {"type": "object", "minProperties": 1, "additionalProperties": _TRANSITION}},
            ("id", "kind", "operation", "outcomes")),
    _object({"id": _TEXT, "kind": {"const": "wait"}, "event": _TEXT,
             "bind": _STR_MAP, "match": _STR_MAP, "next": _TEXT}, ("id", "kind", "event", "next")),
    _object({"id": _TEXT, "kind": {"const": "stop"}, "outcome": _TEXT}, ("id", "kind", "outcome")),
]
WORKFLOW_SCHEMA_V1 = _object({
    "schema_version": {"type": "integer", "const": 1}, "workflow_id": _TEXT,
    "semantics": _TEXT, "entry": _TEXT, "context_slots": _TEXTS, "resume_contract": _TEXT,
    "steps": {"type": "array", "minItems": 1, "items": {"oneOf": _NODE_SCHEMAS}},
    "stop_outcomes": _TEXTS, "wait_kinds": _TEXTS, "cancellation": _TEXT,
    "revision_restart": _TEXT, "automatic_side_effect_retry": {"const": "forbidden_when_outcome_unknown"},
    "outputs": _STR_MAP,
    "loops": {"type":"array", "minItems":1, "maxItems":64,
        "items":_object({"loop_id":_TEXT, "from_step":_TEXT, "to_step":_TEXT,
            "max_rounds":{"type":"integer","minimum":1,"maximum":4096},
            "on_exhausted":_TEXT}, ("loop_id","from_step","to_step","max_rounds","on_exhausted"))},
}, ("schema_version", "entry", "steps", "stop_outcomes", "wait_kinds"))
_VOCABULARY = {"oneOf": [
    _object({"kind": {"const": "choice"}, "options": {"type": "array", "minItems": 1,
        "items": _object({"option_id": _TEXT, "description": _TEXT}, ("option_id", "description"))}}, ("kind", "options")),
    _object({"kind": {"const": "score"}, "levels": {"type": "array", "minItems": 1,
        "items": _object({"level_id": _TEXT, "index": {"type": "integer", "minimum": 0}, "description": _TEXT},
                         ("level_id", "index", "description"))}}, ("kind", "levels")),
    _object({"kind": {"const": "noul"}, "true_description": _TEXT, "false_description": _TEXT},
            ("kind", "true_description", "false_description")),
]}
DECISION_POLICY_SCHEMA_V1 = _object({
    "calibration_profile_id": _TEXT, "activation": {"const": "matching_validated_evaluation_required"},
    "selected_option": _TEXT, "option_statuses": {"type": "object", "additionalProperties": {
        "enum": ["threshold_dependent", "satisfied", "violated", "insufficient", "unknown"]}},
    **{key: _DECIMAL for key in ("minimum_selected_probability", "minimum_top_level_probability", "maximum_p_true", "minimum_expected_index")},
    "below_threshold": _DISPOSITION, "above_threshold": _DISPOSITION,
    "missing_evaluation": _DISPOSITION, "truncation": {"const": "unknown"},
}, ("calibration_profile_id", "activation", "missing_evaluation", "truncation"))
CRITERION_SCHEMA_V1 = _object({
    "criterion_id": _TEXT, "statement": _TEXT, "applies_to": _TEXTS,
    "required_inputs": _TEXTS, "required": {"type": "boolean"}, "blocking": {"type": "boolean"},
    "reviewer_capability": _TEXT,
    "checks": {"type": "array", "minItems": 1, "items": _object({
        "capability_id": _TEXT, "interface_version": _TEXT, "bindings": _MAP,
    }, ("capability_id", "interface_version", "bindings"))},
    "policy": _object({key: _DISPOSITION for key in CHECK_STATUSES_V1}, CHECK_STATUSES_V1),
    "answer_vocabulary": _VOCABULARY, "decision_policy": DECISION_POLICY_SCHEMA_V1,
}, ("criterion_id", "statement", "checks", "policy"))
STANDARD_SCHEMA_V1 = _object({
    "schema_version": {"type": "integer", "const": 1}, "standard_id": _TEXT,
    "revision": _TEXT, "purpose": _TEXT,
    "criteria": {"type": "array", "minItems": 1, "items": CRITERION_SCHEMA_V1},
    "reduction": _object({"required_criteria": {"const": "all_applicable"},
        "empty_applicable_set": {"const": "error"}, "priority": {"type": "array", "minItems": 3,
            "maxItems": 3, "uniqueItems": True, "items": {"enum": ["block", "manual", "pass"]}}},
        ("required_criteria", "empty_applicable_set", "priority")),
}, ("schema_version", "standard_id", "revision", "criteria", "reduction"))
QUESTION_SET_SCHEMA_V1 = _object({
    "schema_version": {"type": "integer", "const": 1}, "question_set_id": _TEXT,
    "question_set_version": _TEXT, "input_mapping_version": _TEXT, "input_contract": _TEXT,
    "required_input_slots": _TEXTS, "iteration": {"enum": list(QUESTION_ITERATIONS_V1)},
    "result_contract": {"const": "DecisionResult.v1"}, "truncation_policy": {"const": "reject"},
    "evidence_order": _TEXT, "missing_required_evidence": {"const": "do_not_invoke"},
    "questions": {"type": "array", "minItems": 1, "items": _object({
        "question_id": _TEXT, "question_revision": _TEXT, "kind": {"enum": list(QUESTION_KINDS_V1)},
        "criterion_refs": {"type": "array", "minItems": 1, "items": CRITERION_REF_SCHEMA_V1},
        "instructions": _TEXT, "answer_definition": _object({
            "from_criterion": CRITERION_REF_SCHEMA_V1, "field": {"const": "answer_vocabulary"}},
            ("from_criterion", "field")),
    }, ("question_id", "question_revision", "kind", "criterion_refs", "instructions", "answer_definition"))},
}, ("schema_version", "question_set_id", "question_set_version", "input_mapping_version", "input_contract",
    "required_input_slots", "iteration", "questions", "result_contract", "truncation_policy", "missing_required_evidence"))
RESOURCE_STRUCTURES_V1 = {"workflow": WORKFLOW_SCHEMA_V1, "standard": STANDARD_SCHEMA_V1,
                          "question_set": QUESTION_SET_SCHEMA_V1}

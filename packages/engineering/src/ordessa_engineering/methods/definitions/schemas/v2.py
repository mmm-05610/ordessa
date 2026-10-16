"""Closed external declaration schemas for schema-2 methods/actions-v1."""

METHOD_SCHEMA_VERSION_V2 = 2
METHOD_CONTRACT_V2 = "ordessa.methods/actions-v1"
ACTION_SCHEMA_VERSION_V1 = 1
RESOURCE_KINDS_V2 = frozenset({"action", "criteria", "prompt", "template", "schema", "routing"})

_ID = {"type": "string", "minLength": 1, "maxLength": 128,
       "pattern": r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$"}
_REFS = {"type": "array", "uniqueItems": True, "items": _ID}
_RESOURCE = {
    "type": "object", "additionalProperties": False,
    "required": ["id", "kind", "path", "media_type", "sha256"],
    "properties": {
        "id": _ID, "kind": {"enum": sorted(RESOURCE_KINDS_V2)},
        "path": {"type": "string", "minLength": 1},
        "media_type": {"type": "string", "minLength": 1, "maxLength": 256},
        "sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
    },
}
METHOD_DEFINITION_SCHEMA_V2 = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object", "additionalProperties": False,
    "required": ["schema_version", "contract", "method_id", "release_version",
                 "actions", "criteria", "prompts", "templates", "schemas",
                 "routing", "resources"],
    "properties": {
        "schema_version": {"const": METHOD_SCHEMA_VERSION_V2},
        "contract": {"const": METHOD_CONTRACT_V2},
        "method_id": _ID, "release_version": _ID,
        "actions": {"type": "array", "minItems": 1, "uniqueItems": True, "items": _ID},
        "criteria": _REFS, "prompts": _REFS, "templates": _REFS,
        "schemas": _REFS, "routing": _REFS,
        "resources": {"type": "array", "minItems": 1, "items": _RESOURCE},
    },
}

_INPUT_KIND = {"enum": ["source_ref", "review_contract", "registered_change",
                         "package_ref", "profile_ref", "method_ref", "text", "json_object"]}
_ACTION_INPUT = {
    "type": "object", "additionalProperties": False,
    "required": ["name", "value_kind"],
    "properties": {"name": _ID, "value_kind": _INPUT_KIND},
}
_STEP_INPUT = {
    "oneOf": [
        {"type": "object", "additionalProperties": False,
         "required": ["name", "source_kind", "source_name"],
         "properties": {"name": _ID, "source_kind": {"const": "action_input"},
                        "source_name": _ID}},
        {"type": "object", "additionalProperties": False,
         "required": ["name", "source_kind", "source_name", "step_id"],
         "properties": {"name": _ID, "source_kind": {"const": "step_output"},
                        "source_name": _ID, "step_id": _ID}},
        {"type": "object", "additionalProperties": False,
         "required": ["name", "source_kind", "source_name"],
         "properties": {"name": _ID, "source_kind": {"const": "resource"},
                        "source_name": _ID}},
    ]
}
_ADMISSION = {
    "type": "object", "additionalProperties": False,
    "required": ["kind", "inputs"],
    "properties": {
        "kind": {"enum": ["same_scope", "exact_inputs", "method_pin",
                           "review_complete", "review_passed", "baseline_available",
                           "reviewer_independent"]},
        "inputs": {"type": "array", "minItems": 1, "uniqueItems": True, "items": _ID},
    },
}
_ACTION_STEP = {
    "type": "object", "additionalProperties": False,
    "required": ["step_id", "kind", "name", "inputs", "outputs"],
    "properties": {
        "step_id": _ID, "kind": {"enum": ["invoke", "record", "emit"]},
        "name": _ID, "inputs": {"type": "array", "items": _STEP_INPUT},
        "outputs": {"type": "array", "uniqueItems": True, "items": _ID},
        "admission": {"type": "array", "items": _ADMISSION},
    },
}
_ACTION_OUTPUT = {
    "type": "object", "additionalProperties": False,
    "required": ["name", "value_kind", "step_id", "output"],
    "properties": {"name": _ID, "value_kind": _INPUT_KIND,
                   "step_id": _ID, "output": _ID},
}
_RESOURCE_ID_REF = {"type": "array", "uniqueItems": True, "items": _ID}
_PREPARATION_DOCUMENT = {
    "type": "object", "additionalProperties": False,
    "required": ["role", "template_resource_id"],
    "properties": {"role": _ID, "template_resource_id": _ID},
}
ACTION_DEFINITION_SCHEMA_V1 = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object", "additionalProperties": False,
    "required": ["schema_version", "action_id", "inputs", "steps", "outputs",
                 "admission", "resources"],
    "properties": {
        "schema_version": {"const": ACTION_SCHEMA_VERSION_V1},
        "action_id": _ID,
        "inputs": {"type": "array", "uniqueItems": True, "items": _ACTION_INPUT},
        "steps": {"type": "array", "minItems": 1, "maxItems": 64,
                   "items": _ACTION_STEP},
        "outputs": {"type": "array", "uniqueItems": True, "items": _ACTION_OUTPUT},
        "admission": {"type": "array", "items": _ADMISSION},
        "resources": _RESOURCE_ID_REF,
        "preparation_documents": {"type": "array", "minItems": 1,
                                   "maxItems": 32, "items": _PREPARATION_DOCUMENT},
    },
}

ROUTING_SCHEMA_V1 = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object", "additionalProperties": False,
    "required": ["schema_version", "routes"],
    "properties": {
        "schema_version": {"const": 1},
        "routes": {"type": "array", "minItems": 1, "items": {
            "type": "object", "additionalProperties": False,
            "required": ["action_id", "profile_ref"],
            "properties": {
                "action_id": _ID,
                "profile_ref": {"oneOf": [
                    {"type": "object", "additionalProperties": False,
                     "required": ["environmentNamespace", "profileId", "manifestRevision", "contentDigest"],
                     "properties": {"environmentNamespace": _ID, "profileId": _ID,
                                    "manifestRevision": {"type": "integer", "minimum": 1},
                                    "contentDigest": {"type": "string", "pattern": "^sha256:[0-9a-f]{64}$"}}},
                    {"type": "object", "additionalProperties": False,
                     "required": ["kind", "input"],
                     "properties": {"kind": {"const": "caller_input"}, "input": _ID}},
                ]},
            },
        }},
    },
}

RESOURCE_STRUCTURES_V2 = {
    "action": ACTION_DEFINITION_SCHEMA_V1,
    "routing": ROUTING_SCHEMA_V1,
}

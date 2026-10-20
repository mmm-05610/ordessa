"""Public contract admission tests using synthetic strict owner schemas.

These bindings exercise the interface seam only. They are not schemas for the
22 production handlers and do not prove handler, identity-provider or grant
integration. Resource reads deliberately use the installed package API.
"""
from copy import deepcopy
from importlib.resources import files
import json
import socket

import pytest

from ordessa_interfaces.system_access.contracts.failures import Failure
from ordessa_interfaces.system_access.contracts.refs import Digest, ExactRef, OperationRef
from ordessa_interfaces.system_access.contracts.validation import ContractError, ContractRegistry


PACKAGE = "ordessa_interfaces.system_access.contracts"
CATALOG = json.loads(files(PACKAGE).joinpath("schemas/operation-catalog.json").read_text())
METHODS = tuple(CATALOG["methods"])
OPERATIONS = tuple(item["operation"] for item in METHODS)
BINDINGS = tuple((item["owner"], item[key]) for item in METHODS
                 for key in ("input_schema_ref", "output_schema_ref"))
SELECTED = next(item for item in METHODS if item["operation"] == "engineering.artifacts.create")
SCHEMA_VERSION = "https://json-schema.org/draft/2020-12/schema"


def synthetic_schema(identity):
    """A closed fixture shape, not a copied or relaxed production schema."""
    return {
        "$schema": SCHEMA_VERSION, "$id": identity, "type": "object",
        "properties": {
            "title": {"type": "string", "minLength": 1},
            "target_ref": {
                "type": "object", "properties": {
                    "realm_id": {"type": "string", "minLength": 1},
                    "project_id": {"type": "string", "minLength": 1},
                    "id": {"type": "string", "minLength": 1},
                    "revision": {"type": "string", "minLength": 1},
                    "digest": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                },
                "required": ["realm_id", "project_id", "id", "revision", "digest"],
                "additionalProperties": False,
            },
        },
        "required": ["title", "target_ref"], "additionalProperties": False,
    }


def bind_all(registry, *, missing=None, replacement=None):
    for owner, identity in BINDINGS:
        if identity != missing:
            registry.bind(owner, replacement if replacement and replacement["$id"] == identity
                          else synthetic_schema(identity))


@pytest.fixture
def registry():
    value = ContractRegistry()
    bind_all(value)
    value.freeze(OPERATIONS)
    return value


@pytest.fixture
def command():
    return {
        "api_version": "1", "request_id": "persisted-intent-1",
        "operation": SELECTED["operation"],
        "scope": {"realm_id": "realm-a", "project_id": "project-a"},
        "preconditions": [{"resource": {"kind": "artifact", "id": "artifact-1"},
                           "expected_version": 0}],
        "parameters": {"title": "synthetic seam", "target_ref": {
            "realm_id": "realm-a", "project_id": "project-a", "id": "artifact-1",
            "revision": "1", "digest": "a" * 64}},
    }


@pytest.mark.parametrize("owner,missing", BINDINGS,
                         ids=[identity for _, identity in BINDINGS])
def test_every_owner_input_and_output_binding_is_required(owner, missing):
    value = ContractRegistry()
    bind_all(value, missing=missing)
    with pytest.raises(ContractError):
        value.freeze(OPERATIONS)


def test_schema_resources_and_validation_are_cwd_independent(tmp_path, monkeypatch, command):
    monkeypatch.chdir(tmp_path)
    value = ContractRegistry()
    assert len(METHODS) == 22
    assert len(set(identity for _, identity in BINDINGS)) == 44
    assert set(value.candidates) == set(OPERATIONS)
    bind_all(value)
    value.freeze(OPERATIONS)
    value.validate_command(command)


@pytest.mark.parametrize("fragment", ["#/$defs/Absent", "#absent_anchor"])
def test_freeze_rejects_missing_fragment_in_registered_resource(fragment):
    value = ContractRegistry()
    schema = synthetic_schema(SELECTED["input_schema_ref"])
    schema["properties"]["title"] = {"$ref": SELECTED["output_schema_ref"] + fragment}
    bind_all(value, replacement=schema)
    with pytest.raises(ContractError):
        value.freeze((SELECTED["operation"],))


def test_valid_local_fragment_in_urn_owner_schema_freezes_and_validates(command):
    value = ContractRegistry()
    schema = synthetic_schema(SELECTED["input_schema_ref"])
    schema["$defs"] = {"Title": {"type": "string", "minLength": 1}}
    schema["properties"]["title"] = {"$ref": "#/$defs/Title"}
    bind_all(value, replacement=schema)
    value.freeze((SELECTED["operation"],))
    value.validate_command(command)
    invalid = deepcopy(command)
    invalid["parameters"]["title"] = ""
    with pytest.raises(ContractError):
        value.validate_command(invalid)


def test_nested_schema_identity_changes_local_reference_base(command):
    value = ContractRegistry()
    schema = synthetic_schema(SELECTED["input_schema_ref"])
    schema["properties"]["title"] = {
        "$id": "https://fixture.invalid/nested-title",
        "$defs": {"Title": {"type": "string", "minLength": 1}},
        "$ref": "#/$defs/Title",
    }
    bind_all(value, replacement=schema)
    value.freeze((SELECTED["operation"],))
    value.validate_command(command)


@pytest.mark.parametrize("ref_keyword", ["$ref", "$dynamicRef"])
def test_unbound_remote_reference_cannot_freeze_or_fetch_network(monkeypatch, command, ref_keyword):
    attempts = []

    def forbidden_connect(*args, **kwargs):
        attempts.append((args, kwargs))
        raise AssertionError("Contract resolver attempted network IO")

    monkeypatch.setattr(socket.socket, "connect", forbidden_connect)
    value = ContractRegistry()
    schema = synthetic_schema(SELECTED["input_schema_ref"])
    schema["properties"]["title"] = {ref_keyword: "https://unbound.invalid/private-schema#/$defs/Title"}
    bind_all(value, replacement=schema)
    with pytest.raises(ContractError):
        value.freeze((SELECTED["operation"],))
    # Direct schema validation must also fail closed even before freeze.
    with pytest.raises(ContractError):
        value.validate("command-envelope.schema.json", command)
    assert attempts == []


def test_unavailable_operation_is_not_enabled_by_discovery(command):
    value = ContractRegistry()
    assert command["operation"] in value.candidates
    with pytest.raises(ContractError):
        value.validate_command(command)


def test_failed_refreeze_does_not_retain_old_admission(registry, command):
    registry.validate_command(command)
    with pytest.raises(ContractError):
        registry.freeze(("engineering.execute_python",))
    with pytest.raises(ContractError) as error:
        registry.validate_command(command)
    assert error.value.code == "OPERATION_UNAVAILABLE"


def test_owner_cannot_bind_another_owners_or_replace_a_schema():
    value = ContractRegistry()
    schema = synthetic_schema(SELECTED["input_schema_ref"])
    with pytest.raises(ContractError):
        value.bind("unregistered-owner", schema)
    value.bind(SELECTED["owner"], schema)
    with pytest.raises(ContractError):
        value.bind(SELECTED["owner"], schema)


@pytest.mark.parametrize("change", [
    {"operation": "engineering.execute_python"}, {"api_version": "2"},
    {"principal_id": "human:forged"}, {"authority_id": "client-chosen-owner"},
    {"unexpected": True}, {"request_context": {"principal_id": "human:forged"}},
])
def test_unknown_operation_version_and_client_authority_fields_are_rejected(registry, command, change):
    command.update(change)
    with pytest.raises(ContractError):
        registry.validate_command(command)


@pytest.mark.parametrize("field,value", [("extra", True), ("principal_id", "human:forged")])
def test_owner_parameters_are_strict_and_cannot_self_report_principal(registry, command, field, value):
    command["parameters"][field] = value
    with pytest.raises(ContractError):
        registry.validate_command(command)


@pytest.mark.parametrize("field", ["realm_id", "project_id"])
def test_exact_target_cannot_cross_command_scope(registry, command, field):
    command["parameters"]["target_ref"][field] = "another-scope"
    with pytest.raises(ContractError) as error:
        registry.validate_command(command)
    assert error.value.code == "REF_SCOPE_MISMATCH"


@pytest.mark.parametrize("version", [0, 1])
def test_duplicate_precondition_is_rejected_even_with_a_different_version(registry, command, version):
    duplicate = deepcopy(command["preconditions"][0])
    duplicate["expected_version"] = version
    command["preconditions"].append(duplicate)
    with pytest.raises(ContractError) as error:
        registry.validate_command(command)
    assert error.value.code == "DUPLICATE_PRECONDITION"


def wire_attempt(command, transport_id):
    return {"jsonrpc": "2.0", "id": transport_id, "method": command["operation"],
            "params": {"contract": "ordessa.command/1", "requestId": command["request_id"],
                       "scope": command["scope"], "preconditions": command["preconditions"],
                       "parameters": command["parameters"]}}


def test_jsonrpc_attempt_id_does_not_replace_stable_business_request_key(registry, command):
    first = wire_attempt(command, "attempt-1")
    second = wire_attempt(command, "attempt-2")
    registry.validate("jsonrpc-envelope.schema.json", first)
    registry.validate("jsonrpc-envelope.schema.json", second)
    assert first["params"]["requestId"] == second["params"]["requestId"] == command["request_id"]
    del second["params"]["requestId"]
    with pytest.raises(ContractError):
        registry.validate("jsonrpc-envelope.schema.json", second)


@pytest.mark.parametrize("code", ["OUTCOME_UNKNOWN", "EFFECT_UNKNOWN", "OUTCOME_INDETERMINATE",
                                  "RETRY_REQUIRES_RECONCILIATION"])
@pytest.mark.parametrize("retry", ["never", "same_key_after_delay", "refresh_then_new_key"])
def test_unknown_effect_failure_never_grants_a_retry_key(code, retry):
    with pytest.raises(ValueError):
        Failure(code=code, message="Inspect the original operation", retry=retry,
                correlation_id="attempt-1")


def test_unknown_failure_explicitly_requires_reconciliation():
    value = Failure(code="OUTCOME_UNKNOWN", message="Inspect the original operation",
                    retry="reconcile_first", correlation_id="attempt-1")
    assert value.retry == "reconcile_first"


def test_unregistered_failure_code_cannot_escape_unknown_retry_policy():
    with pytest.raises(ValueError):
        Failure(code="CUSTOM_UNKNOWN_EFFECT", message="Invented unknown effect",
                retry="refresh_then_new_key", correlation_id="attempt-1")


@pytest.mark.parametrize("bad_digest", ["sha256:" + "a" * 64, "A" * 64, "a" * 63])
def test_neutral_exact_ref_digest_does_not_accept_profile_prefix_or_native_commit(bad_digest):
    with pytest.raises(ValueError):
        ExactRef("fixture", "record-1", "1", bad_digest)


def test_neutral_values_are_identity_only_and_preserve_authority():
    value = ExactRef("fixture", "record-1", "1", "a" * 64)
    assert value.digest == Digest("sha256", "a" * 64).hex
    assert OperationRef("owner-a", "same-id") != OperationRef("owner-b", "same-id")

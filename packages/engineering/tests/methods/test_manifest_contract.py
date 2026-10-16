"""Regressions for contract extraction without changing loader semantics."""
from copy import deepcopy
import hashlib
from pathlib import Path

import pytest
import yaml

from ordessa_engineering.methods.definitions.errors import MethodError, MethodFailure
from ordessa_engineering.methods.definitions.models import MethodSource
from ordessa_engineering.methods.validation.structure import validate_manifest_structure
from ordessa_engineering.methods.loading.loader import load_method


BODY = b"schema_version: 1\nentry: done\nsteps: []\n"


def _manifest():
    return {
        "schema_version": 1,
        "method_id": "test.contract",
        "release_version": "1.0.0",
        "compiler_contract": "ordessa.methods/v1",
        "entry": {"resource": "workflow.main"},
        "resources": [{
            "id": "workflow.main", "kind": "workflow", "path": "workflow.yaml",
            "media_type": "application/yaml", "sha256": hashlib.sha256(BODY).hexdigest(),
        }],
        "requires": [],
    }


class _Reader:
    def __init__(self, manifest):
        self.files = {"method.yaml": yaml.safe_dump(manifest, sort_keys=False).encode(),
                      "workflow.yaml": BODY}
        self.calls = []

    def read(self, source, relative_path, max_bytes):
        self.calls.append(relative_path)
        if relative_path not in self.files:
            raise MethodFailure(MethodError("RESOURCE_NOT_FOUND", "not present", path=relative_path))
        assert len(self.files[relative_path]) <= max_bytes
        return self.files[relative_path]


@pytest.mark.parametrize("field,value,code,pointer", [
    ("unexpected", True, "MANIFEST_FIELDS_INVALID", None),
    ("schema_version", True, "METHOD_SCHEMA_UNSUPPORTED", None),
    ("compiler_contract", 1, "MANIFEST_FIELD_INVALID", "/compiler_contract"),
    ("compiler_contract", "unsupported", "COMPILER_CONTRACT_UNSUPPORTED", "/compiler_contract"),
])
def test_manifest_errors_precede_resource_reads(field, value, code, pointer):
    manifest = _manifest()
    manifest[field] = value
    reader = _Reader(manifest)
    result = load_method(MethodSource(Path("unused")), reader)
    assert not result.ok
    assert (result.error.code, result.error.path, result.error.pointer) == (code, "method.yaml", pointer)
    assert reader.calls == ["method.yaml"]


def test_missing_and_unknown_fields_keep_deterministic_diagnostic():
    manifest = _manifest()
    del manifest["requires"]
    manifest["prompt"] = {}
    with pytest.raises(MethodFailure) as caught:
        validate_manifest_structure(manifest)
    assert caught.value.error.code == "MANIFEST_FIELDS_INVALID"
    assert caught.value.error.message == "unknown fields=['prompt'] missing=['requires']"


def test_manifest_contract_preserves_object_and_uninterpreted_optional_content():
    manifest = _manifest()
    manifest["documents"] = [{"unknown_nested_field": "still retained at this stage"}]
    manifest["skills"] = {"main_agent": {"resource": "skill.example", "future_field": True}}
    manifest["metadata"] = {"note": "description only"}
    before = deepcopy(manifest)
    assert validate_manifest_structure(manifest) is manifest
    assert manifest == before
    assert "display_name" not in manifest


@pytest.mark.parametrize("changes,code,pointer", [
    ({"extra": 1, "path": "../escape"}, "RESOURCE_DECLARATION_FIELDS_INVALID", "/resources/0"),
    ({"path": "../escape", "kind": "unsupported"}, "RESOURCE_ESCAPE", None),
    ({"kind": "unsupported"}, "RESOURCE_KIND_UNSUPPORTED", "/resources/0/kind"),
    ({"media_type": ""}, "RESOURCE_DECLARATION_INVALID", "/resources/0"),
    ({"sha256": "invalid"}, "RESOURCE_DIGEST_INVALID", "/resources/0/sha256"),
])
def test_resource_diagnostics_and_read_order_are_unchanged(changes, code, pointer):
    manifest = _manifest()
    manifest["resources"][0].update(changes)
    reader = _Reader(manifest)
    result = load_method(MethodSource(Path("unused")), reader)
    assert not result.ok
    assert (result.error.code, result.error.pointer) == (code, pointer)
    assert reader.calls == ["method.yaml"]


def test_duplicate_resource_id_is_reported_before_unsupported_kind():
    manifest = _manifest()
    duplicate = dict(manifest["resources"][0], kind="unsupported", path="other.yaml")
    manifest["resources"].append(duplicate)
    reader = _Reader(manifest)
    result = load_method(MethodSource(Path("unused")), reader)
    assert result.error.code == "DUPLICATE_RESOURCE_ID"
    assert result.error.pointer == "/resources/1/id"
    assert reader.calls == ["method.yaml", "workflow.yaml"]


@pytest.mark.parametrize("field,value,code,pointer", [
    ("entry", {"resource": "workflow.main", "extra": True}, "MANIFEST_ENTRY_INVALID", "/entry"),
    ("entry", {"resource": "missing"}, "MANIFEST_ENTRY_INVALID", "/entry/resource"),
    ("requires", {}, "REQUIRES_INVALID", "/requires"),
    ("requires", ["not an object"], "REQUIRES_INVALID", "/requires/0"),
    ("requires", [{"capability_id": ""}], "DUPLICATE_CAPABILITY", "/requires/0/capability_id"),
])
def test_entry_and_requires_errors_still_follow_resource_capture(field, value, code, pointer):
    manifest = _manifest()
    manifest[field] = value
    reader = _Reader(manifest)
    result = load_method(MethodSource(Path("unused")), reader)
    assert not result.ok
    assert (result.error.code, result.error.pointer) == (code, pointer)
    assert reader.calls == ["method.yaml", "workflow.yaml"]


def test_success_retains_manifest_and_captured_resource_without_defaults():
    manifest = _manifest()
    reader = _Reader(manifest)
    result = load_method(MethodSource(Path("unused")), reader)
    assert result.ok
    assert result.value.manifest == manifest
    assert "documents" not in result.value.manifest
    resource = result.value.resources["workflow.main"]
    assert resource.captured.data == BODY
    assert resource.value == {"schema_version": 1, "entry": "done", "steps": []}
    assert result.value.source_bundle.resources[0].resource_id == resource.resource_id
    assert result.value.source_bundle.resources[0].captured is resource.captured
    assert reader.calls == ["method.yaml", "workflow.yaml", "bundle-lock.json"]

"""Injected-reader budgets and captured-content boundaries."""
from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest
import yaml

from ordessa_engineering.methods.definitions.models.identity import method_digest
from ordessa_engineering.methods.definitions.errors import MethodError, MethodFailure
from ordessa_engineering.methods.definitions.models import LoadLimits, MethodSource
from ordessa_engineering.methods.loading.captured import verify_loaded_method
from ordessa_engineering.methods.loading.loader import load_method
from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader


class MemoryReader:
    def __init__(self, files):
        self.files = files
        self.calls = []

    def read(self, source, relative_path, max_bytes):
        self.calls.append(relative_path)
        if relative_path not in self.files:
            raise MethodFailure(MethodError("RESOURCE_NOT_FOUND", "not found", path=relative_path))
        return self.files[relative_path]


def bundle(*, deep=False, lock=False):
    workflow = b"schema_version: 1\nentry: done\nsteps:\n- id: done\n  kind: stop\n  outcome: finished\nstop_outcomes: [finished]\nwait_kinds: []\n"
    manifest = {
        "schema_version": 1, "method_id": "test.method", "release_version": "1",
        "compiler_contract": "ordessa.methods/v1", "entry": {"resource": "workflow.main"},
        "resources": [{"id": "workflow.main", "kind": "workflow", "path": "workflow.yaml",
                       "media_type": "application/yaml", "sha256": hashlib.sha256(workflow).hexdigest()}],
        "requires": [],
    }
    if deep:
        nested = "leaf"
        for _ in range(70):
            nested = {"child": nested}
        manifest["metadata"] = nested
    files = {"method.yaml": yaml.safe_dump(manifest, sort_keys=False).encode(), "workflow.yaml": workflow}
    if lock:
        digest = hashlib.sha256(files["method.yaml"]).hexdigest()
        payload = {"manifest_sha256": digest, "resource_digests": [
            {"id": "workflow.main", "sha256": manifest["resources"][0]["sha256"]}],
                   "required_capabilities": []}
        golden = {"schema_version": 2}
        lock_data = {"manifest_sha256": digest, "snapshot_payload": payload,
                     "method_ref": {"snapshot_digest": {"hex": method_digest("method-snapshot", payload)}},
                     "compiled_plan_path": "golden.json",
                     "compiled_plan_digest": {"hex": method_digest("compiled-method-program", golden)}}
        files["bundle-lock.json"] = json.dumps(lock_data).encode()
        files["golden.json"] = json.dumps(golden).encode()
    return files


def test_missing_reader_fails_without_touching_filesystem(tmp_path):
    result = load_method(MethodSource(tmp_path))
    assert not result.ok
    assert result.error.code == "RESOURCE_READER_UNAVAILABLE"


@pytest.mark.parametrize("invalid", ["not bytes", bytearray(b"a"), None])
def test_reader_must_return_immutable_bytes(invalid):
    result = load_method(MethodSource(Path("unread")), MemoryReader({"method.yaml": invalid}))
    assert not result.ok
    assert result.error.code == "RESOURCE_READER_INVALID"


def test_untrusted_reader_cannot_ignore_per_file_limit():
    files = bundle()
    result = load_method(MethodSource(Path("unread")), MemoryReader(files), LoadLimits(manifest_bytes=1))
    assert not result.ok
    assert result.error.code == "RESOURCE_TOO_LARGE"


def test_total_budget_includes_manifest():
    files = bundle()
    limit = len(files["workflow.yaml"])
    result = load_method(MethodSource(Path("unread")), MemoryReader(files), LoadLimits(total_bytes=limit))
    assert not result.ok
    assert result.error.code == "RESOURCE_TOTAL_TOO_LARGE"


@pytest.mark.parametrize("exclude", ["bundle-lock.json", "golden.json"])
def test_total_budget_includes_lock_and_golden(exclude):
    files = bundle(lock=True)
    limit = sum(map(len, files.values())) - len(files[exclude])
    result = load_method(MethodSource(Path("unread")), MemoryReader(files), LoadLimits(total_bytes=limit))
    assert not result.ok
    assert result.error.code == "RESOURCE_TOTAL_TOO_LARGE"


def test_captured_rebuild_preserves_configured_depth_without_rereading():
    files = bundle(deep=True)
    reader = MemoryReader(files)
    limits = LoadLimits(structure_depth=100)
    result = load_method(MethodSource(Path("unread")), reader, limits)
    assert result.ok
    calls = tuple(reader.calls)
    files.clear()
    rebuilt = verify_loaded_method(result.value)
    assert rebuilt.manifest == result.value.manifest
    assert rebuilt.load_limits == limits
    assert rebuilt.source_bundle.limits == limits
    assert tuple(reader.calls) == calls


def test_captured_rebuild_rejects_reduced_budget():
    result = load_method(MethodSource(Path("unread")), MemoryReader(bundle()))
    assert result.ok
    loaded = result.value
    narrowed = replace(loaded.source_bundle, limits=LoadLimits(total_bytes=1))
    with pytest.raises(MethodFailure) as caught:
        verify_loaded_method(replace(loaded, source_bundle=narrowed,
            parsed_source=replace(loaded.parsed_source, source_bundle=narrowed)))
    assert caught.value.error.code == "RESOURCE_TOTAL_TOO_LARGE"


def test_filesystem_adapter_rejects_symlink(tmp_path):
    files = bundle()
    for name, raw in files.items():
        (tmp_path / name).write_bytes(raw)
    (tmp_path / "actual.yaml").write_bytes(files["workflow.yaml"])
    (tmp_path / "workflow.yaml").unlink()
    (tmp_path / "workflow.yaml").symlink_to("actual.yaml")
    result = load_method(MethodSource(tmp_path), FileResourceReader())
    assert not result.ok
    assert result.error.code == "RESOURCE_NOT_PRIVATE_FILE"


def _nested_mapping(levels):
    value = "leaf"
    for _ in range(levels):
        value = {"child": value}
    return value


def _nested_sequence(levels):
    value = "leaf"
    for _ in range(levels):
        value = [value]
    return value


@pytest.mark.parametrize("shape,levels", [
    ("root-scalar", 0), ("empty-mapping", 0), ("empty-sequence", 0),
    ("mapping", 1), ("sequence", 1),
    ("mapping-at-limit", 3), ("sequence-at-limit", 3),
    ("mapping-over-limit", 4), ("sequence-over-limit", 4),
])
def test_parse_depth_precheck_and_value_validation_agree(shape, levels):
    """Event-level alias/depth precheck and the recursive value validator must
    refuse the same structures at the same boundary.

    The precheck documents root depth zero, matching validate_json_value. A
    divergence would let one stage accept what the other rejects, so both are
    compared on the same document with the same depth limit.
    """
    from ordessa_engineering.methods.loading.parsing import _reject_aliases_anchors
    from ordessa_engineering.methods.validation.values import validate_json_value

    limit = 3
    if shape == "root-scalar":
        text = json.dumps("scalar")
    elif shape == "empty-mapping":
        text = json.dumps({})
    elif shape == "empty-sequence":
        text = json.dumps([])
    elif shape.startswith("mapping"):
        text = json.dumps(_nested_mapping(levels))
    else:
        text = json.dumps(_nested_sequence(levels))

    precheck = None
    try:
        _reject_aliases_anchors(text, "probe.json", limit)
        precheck = "accepted"
    except MethodFailure as exc:
        precheck = exc.error.code
    validated = None
    try:
        validate_json_value(json.loads(text), path="probe.json", depth_limit=limit)
        validated = "accepted"
    except MethodFailure as exc:
        validated = exc.error.code
    assert precheck == validated, (shape, levels, precheck, validated)

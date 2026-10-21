"""Parsed-value codecs and structural validation, using synthetic manifests only."""
import ast
import copy
import subprocess
import sys
from pathlib import Path

import pytest

from ordessa_agents.profiles.definitions import codec, models, validation

MANIFEST = {"schemaVersion": "profile/1", "harnessDefinitionRef": {
    "environmentNamespace": "codec-test", "definitionId": "opaque", "revision": "1"},
    "declarations": [{"declarationId": "choice", "configurationKind": "unknown.kind",
        "schemaVersion": "unknown/1", "action": "value", "requirement": "required",
        "payload": {"someUnknownValue": 0.5}}]}


def wire_manifest():
    content = validation.canonical_content(MANIFEST, "codec-test")
    ref = models.ProfileRevisionRef("codec-test", "main", 1, codec.content_digest(content))
    return {"ref": codec.encode_revision_ref(ref), "content": copy.deepcopy(MANIFEST)}


def test_codec_roundtrip_preserves_opaque_configuration_and_detaches_values():
    wire = wire_manifest()
    manifest = codec.decode_revision(wire)
    assert codec.encode_revision(manifest) == wire
    entry = models.Profile("main", 2, "Main", None, manifest.ref)
    assert codec.decode_profile(codec.encode_profile(entry)) == entry
    assert codec.decode_revision_ref(codec.encode_revision_ref(manifest.ref)) == manifest.ref
    wire["content"]["declarations"][0]["payload"]["someUnknownValue"] = 3
    assert codec.encode_content(manifest.content) == MANIFEST
    out = codec.encode_revision(manifest)
    out["content"]["declarations"].clear()
    assert codec.encode_content(manifest.content) == MANIFEST


@pytest.mark.parametrize("mutation", [
    lambda m: m["declarations"].append(copy.deepcopy(m["declarations"][0])),
    lambda m: m["declarations"][0].update(action="reset"),
    lambda m: m["declarations"][0].update(action="disabled"),
    lambda m: m["declarations"][0].update(requirement="sometimes"),
    lambda m: m["declarations"][0].update(payload={"password": "plaintext"}),
    lambda m: m["declarations"][0].update(payload=float("nan")),
    lambda m: m["declarations"][0].update(resourceRefs=[{"environmentNamespace": "other", "ref": "x"}]),
    lambda m: m.update(unrecognized=True),
])
def test_invalid_configuration_is_refused(mutation):
    wire = wire_manifest()
    mutation(wire["content"])
    with pytest.raises(validation.ProfileValidationError):
        codec.decode_revision(wire)


@pytest.mark.parametrize("decoder,value", [
    (codec.decode_revision, "/tmp/not-a-file"),
    (codec.decode_revision, {"ref": {}, "content": {}}),
    (codec.decode_profile, {}),
    (codec.decode_revision_ref, {"environmentNamespace": "codec-test", "profileId": "main",
                        "manifestRevision": True, "contentDigest": "sha256:" + "0"*64}),
])
def test_invalid_parsed_inputs_are_refused(decoder, value):
    with pytest.raises(ValueError):
        decoder(value)


def test_digest_and_entry_identity_are_verified():
    wire = wire_manifest()
    wire["ref"]["contentDigest"] = "sha256:" + "0" * 64
    with pytest.raises(validation.ProfileValidationError, match="digest"):
        codec.decode_revision(wire)
    entry = models.Profile("main", 1, "Main", None, codec.decode_revision_ref(wire["ref"]))
    for field, value in [("profileId", "other"), ("catalogRevision", True), ("displayName", ""),
                          ("archivedAt", 1), ("extra", None)]:
        malformed = {**codec.encode_profile(entry), field: value}
        with pytest.raises(validation.ProfileValidationError):
            codec.decode_profile(malformed)


def violations(source):
    tree = ast.parse(source)
    failures = []
    for node in ast.walk(tree):
        names = ([node.module or ""] if isinstance(node, ast.ImportFrom) else
                 [alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
        for name in names:
            if any(part in name.split(".") for part in (
                    "management", "catalog", "units", "harness", "pacthold", "apps")) or name.startswith((
                    "ordessa_server", "ordessa_harness", "sqlite3", "pathlib", "os", "socket", "subprocess")):
                failures.append(name)
        if isinstance(node, ast.Call) and ((isinstance(node.func, ast.Name) and node.func.id == "open") or
                (isinstance(node.func, ast.Attribute) and node.func.attr in (
                    "open", "read_text", "write_text", "read_bytes", "write_bytes", "connect"))):
            failures.append("IO")
    return failures


def test_definitions_have_no_io_or_reverse_dependency_with_counterexamples():
    directory = Path(models.__file__).parent
    for path in directory.glob("*.py"):
        assert not violations(path.read_text()), path
    for planted in ["from ..management.service import ProfileService", "import sqlite3",
                    "from ordessa_harness_pi import X", "open('x')", "obj.read_text()"]:
        assert violations(planted)


def test_codec_operations_and_definition_imports_do_not_open_files():
    program = """
import builtins
original = builtins.__import__
def restricted(name, *args, **kwargs):
    if name.startswith(('pacthold', 'ordessa_server', 'ordessa_harness',
                        'ordessa_units', 'ordessa_agents.harness')):
        raise AssertionError('forbidden runtime dependency: ' + name)
    return original(name, *args, **kwargs)
builtins.__import__ = restricted
def refuse(*args, **kwargs):
    raise AssertionError('definitions must not open files')
builtins.open = refuse
from ordessa_agents.profiles.definitions import models, codec, validation
from ordessa_agents.profiles.management.service import ProfileService
from ordessa_agents.profiles.management.ports import ProfileStorePort
import importlib.util
assert importlib.util.find_spec("ordessa_agents.profiles.definitions.contracts") is None
assert importlib.util.find_spec("ordessa_agents.profiles.definitions.wire_schema") is None
try:
    import ordessa_agents.profiles.catalog.service
except ModuleNotFoundError:
    pass
else:
    raise AssertionError("retired catalog entry is reachable")
content = {'schemaVersion': '1', 'harnessDefinitionRef': {
    'environmentNamespace': 'isolated', 'definitionId': 'unknown'}, 'declarations': []}
ref = models.ProfileRevisionRef('isolated', 'main', 1,
    codec.content_digest(validation.canonical_content(content, 'isolated')))
wire = {'ref': codec.encode_revision_ref(ref), 'content': content}
assert codec.encode_revision(codec.decode_revision(wire)) == wire
"""
    result = subprocess.run([sys.executable, '-c', program], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_models_have_no_serialization_or_codec_surface():
    source = Path(models.__file__).read_text()
    tree = ast.parse(source)
    forbidden = {"to_dict", "from_dict", "content_json"}
    wrappers = []
    codec_calls = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in forbidden:
            wrappers.append(node.name)
        if isinstance(node, ast.ImportFrom) and node.level and node.module == "codec":
            wrappers.append("codec import")
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {
                "encode_content", "encode_revision", "encode_profile", "encode_declaration",
                "encode_revision_ref", "decode_content", "decode_revision", "decode_profile",
                "decode_declaration", "decode_revision_ref", "canonical", "content_digest"}:
            codec_calls.append(node.func.attr)
    assert wrappers == []
    assert codec_calls == []

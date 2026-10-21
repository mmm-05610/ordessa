"""Refresh-tool discipline for the owned Engineering operation registry.

The tool at ``docs/implementation/packages-convergence-20261012/engineering/refresh_owned_registry.py``
is the fixed, one-shot R1 tool that moved the registry from the reviewed revision
101 to the approved revision 102. These tests replay the frozen historical closure and the
tool's guarantees: reviewed-delta-only, content locks, dependency-first ordering,
all-or-nothing *precheck* (a refusal writes nothing) and idempotence. The pure
planner is called directly; the tool is never run for real.

The fixtures under ``tests/fixtures/r1-refresh/`` are the real reviewed bytes
come from the paused R1 snapshot (2026-10-16) and reviewed commit dd47fd7323: the revision-101 registry
resource (``sha256:b212c3c4…``) and the matching pre-refresh ``source_integrity``
manifest (``sha256:db7740c5…``). The refresh tests feed those real bytes to the
planner — they are not reconstructed from the post-refresh tree and no test
stands a fake digest in for a real one, so the plan that comes back is a genuine
101-to-102 result. The real 102 resource and post-refresh integrity text are
frozen separately; these tests never identify the current active registry as 102.
Current source/wheel closure verification lives in test_current_registry_closure.py.

``test_reviewed_delta_scope_is_unchanged_classification`` is a classification
check on the tool's constant allow-lists. It reads no fixture and exercises no
refresh; it says only that the allow-list still names the reviewed R1 scope and
must not be read as migration or change evidence.
"""
from __future__ import annotations

import hashlib
import importlib.resources
import importlib.util
import json
from pathlib import Path

import pytest

from ordessa_engineering.adapters.registry import loading as rs
from ordessa_engineering.adapters.registry import source_integrity as si

ROOT = Path(__file__).resolve().parents[3]
TOOL_PATH = ROOT / "docs/implementation/packages-convergence-20261012/engineering/refresh_owned_registry.py"
PACKAGE_ROOT = Path(si.__file__).parents[2]
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "r1-refresh"
REGISTRY_101 = FIXTURES / "operation_registry.v1.r101.json"
INTEGRITY_101 = FIXTURES / "source_integrity.r101.py"
REGISTRY_102 = FIXTURES / "operation_registry.v1.r102.json"
INTEGRITY_102 = FIXTURES / "source_integrity.r102.py"

_EXPECTED_PRE_REFRESH_SHA256 = "b212c3c49d06ae246f80ca97ea4cc82e5a947d08a706702ff6d444f7b0e7dc0d"
_EXPECTED_POST_REFRESH_SHA256 = "41fdb6b777a0d90ff0b988c85589dfcb3470654ecf394bf6add074158656ad30"

_ADDED = {
    "adapters/decision/source_bindings.py",
    "adapters/decision/source_reviewer.py",
    "adapters/filesystem/project_sources.py",
    "adapters/persistence/sqlite/method_declaration_codec.py",
    "adapters/persistence/sqlite/package_document_materials.py",
    "application/contracts/declared_generation.py",
    "application/contracts/dispatch_identity.py",
    "application/contracts/source_reviews.py",
    "application/contracts/work_context.py",
    "application/orchestration/declared_prepare_packages.py",
    "application/orchestration/declared_review_change.py",
    "application/orchestration/steps/declared_generation_dispatch.py",
    "application/orchestration/steps/declared_generation_port.py",
    "application/usecases/queries/works.py",
    "application/usecases/works.py",
}


def _tool():
    spec = importlib.util.spec_from_file_location("refresh_owned_registry", TOOL_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Replay the original pure planner against recorded dependency/source facts.
    # The tool and every content/dependency guard stay byte-identical. Runtime
    # current-job metadata is exercised independently, never forged as R1 facts.
    module.RESOURCE = REGISTRY_102
    module.INTEGRITY = INTEGRITY_102
    module.current_foreign_facts = lambda: {
        key: value for key, value in json.loads(REGISTRY_102.read_text())["implementation"].items()
        if key != "engineering"}
    module.current_operations = lambda: json.loads(REGISTRY_102.read_text())["operations"]
    return module


def _live_manifest(tool):
    return tool.INTEGRITY.read_text(encoding="utf-8")


def _live_closures(tool):
    """The genuine recorded post-R1 closure, independent of today's source tree."""
    manifest = _live_manifest(tool)
    return (tool._manifest_names(manifest, "ENGINEERING_FILES"),
            tool._manifest_names(manifest, "INFRASTRUCTURE_FILES"))


def _hashes(tool, engineering, infrastructure):
    # Pins are the genuine reviewed output bytes, not hashes of later sources.
    pins = json.loads(REGISTRY_102.read_text())["implementation"]["engineering"]
    return ({name: pins[name] for name in engineering},
            {name: pins["ordessa_infrastructure:" + name] for name in infrastructure})

def _live_hashes(tool):
    return _hashes(tool, *_live_closures(tool))


def _plan(tool, old_bytes, integrity_text, engineering_hashes, infrastructure_hashes,
          foreign=None, operations=None):
    return tool.build_plan(old_bytes=old_bytes, integrity_text=integrity_text,
                           engineering_hashes=engineering_hashes,
                           infrastructure_hashes=infrastructure_hashes,
                           foreign_facts=tool.current_foreign_facts() if foreign is None else foreign,
                           operations=tool.current_operations() if operations is None else operations)


def _before_bytes():
    return REGISTRY_101.read_bytes()


def _before_text():
    return INTEGRITY_101.read_text(encoding="utf-8")


def test_refreshed_registry_closure_is_complete_and_duplicate_free():
    registry = json.loads(REGISTRY_102.read_text())
    assert registry["revision"] == 102
    engineering = {key for key in registry["implementation"]["engineering"]
                   if not key.startswith("ordessa_infrastructure:")}
    infrastructure = {key for key in registry["implementation"]["engineering"]
                      if key.startswith("ordessa_infrastructure:")}
    actual = set(_tool()._manifest_names(INTEGRITY_102.read_text(), "ENGINEERING_FILES"))
    assert engineering == actual
    assert len(engineering) == len(_tool()._manifest_names(INTEGRITY_102.read_text(), "ENGINEERING_FILES")) == 299
    assert len(set(_tool()._manifest_names(INTEGRITY_102.read_text(), "ENGINEERING_FILES"))) == 299
    assert len(infrastructure) == len(_tool()._manifest_names(INTEGRITY_102.read_text(), "INFRASTRUCTURE_FILES")) == 14
    assert len(set(_tool()._manifest_names(INTEGRITY_102.read_text(), "INFRASTRUCTURE_FILES"))) == 14
    assert len(registry["operations"]) == 21


def test_reviewed_delta_scope_is_unchanged_classification():
    """Classification unit test: the allow-list constants still name the R1 scope.

    No fixture is read and no refresh is exercised, so this is not migration or
    change evidence.
    """
    tool = _tool()
    assert tool.APPROVED_ENGINEERING_ADDED == _ADDED
    assert tool.APPROVED_ENGINEERING_REMOVED == {"application/orchestration/cancellation.py"}
    assert len(tool.APPROVED_ENGINEERING_CHANGED) == 50
    assert set(tool.APPROVED_INFRASTRUCTURE_ADDED) == {"encoding/immutable_json.py", "identifiers.py"}
    assert tool.APPROVED_OPERATIONS_REMOVED == {
        "engineering.runs.cancel", "engineering.runs.resume", "engineering.work.bind_inputs",
        "engineering.work.record_command_step", "engineering.work.record_dispatch_step"}
    assert tool.APPROVED_OPERATIONS_ADDED == {"engineering.work.invoke"}
    assert tool.APPROVED_OPERATIONS_UPDATED == {"engineering.work.start"}


def test_fixtures_are_the_real_reviewed_bytes():
    """The fixtures are the paused snapshot's bytes, not a reconstruction."""
    tool = _tool()
    registry_101 = REGISTRY_101.read_bytes()
    live = tool.RESOURCE.read_bytes()
    assert hashlib.sha256(registry_101).hexdigest() == tool.EXPECTED_PRE_REFRESH_SHA256
    assert hashlib.sha256(registry_101).hexdigest() == _EXPECTED_PRE_REFRESH_SHA256
    assert hashlib.sha256(live).hexdigest() == tool.EXPECTED_POST_REFRESH_SHA256
    assert hashlib.sha256(live).hexdigest() == _EXPECTED_POST_REFRESH_SHA256

    before = json.loads(registry_101)
    assert before["revision"] == 101
    engineering = {key for key in before["implementation"]["engineering"]
                   if not key.startswith("ordessa_infrastructure:")}
    infrastructure = {key.split(":", 1)[1] for key in before["implementation"]["engineering"]
                      if key.startswith("ordessa_infrastructure:")}
    assert len(engineering) == 285
    assert len(before["operations"]) == 25
    # the 101 carries exactly the twelve reviewed Infrastructure pins, read from
    # the real 101 bytes rather than the post-refresh tree
    assert infrastructure == set(tool.EXPECTED_PRE_REFRESH_INFRASTRUCTURE)
    assert len(infrastructure) == 12

    # the pre-refresh manifest is the matching real file, not reverse-engineered
    assert len(tool._manifest_names(_before_text(), "ENGINEERING_FILES")) == 285
    assert len(tool._manifest_names(_before_text(), "INFRASTRUCTURE_FILES")) == 12


def test_real_101_refresh_plan_reproduces_the_approved_102():
    """The real 101 input and the real pre-refresh manifest reproduce 102 exactly."""
    tool = _tool()
    engineering_hashes, infrastructure_hashes = _live_hashes(tool)
    plan = _plan(tool, _before_bytes(), _before_text(), engineering_hashes, infrastructure_hashes)
    assert plan is not None
    live_registry = tool.RESOURCE.read_text(encoding="utf-8")
    assert plan["new_registry_text"] == live_registry
    assert plan["new_integrity_text"] == _live_manifest(tool)
    assert hashlib.sha256(plan["new_registry_text"].encode("utf-8")).hexdigest() == _EXPECTED_POST_REFRESH_SHA256

    receipt = plan["receipt"]
    assert receipt["before_revision"] == 101
    assert receipt["after_revision"] == 102
    assert receipt["before_resource_sha256"] == _EXPECTED_PRE_REFRESH_SHA256
    assert receipt["after_resource_sha256"] == _EXPECTED_POST_REFRESH_SHA256
    assert receipt["engineering_closure_entries"] == 299
    assert receipt["infrastructure_closure_entries"] == 14
    assert receipt["operation_entries"] == 21
    assert len(receipt["changed_owned_source"]) == 50
    assert receipt["registry_digest"] == json.loads(live_registry)["registry_digest"]


def test_planner_is_idempotent_on_the_refreshed_tree():
    tool = _tool()
    engineering_hashes, infrastructure_hashes = _live_hashes(tool)
    assert _plan(tool, tool.RESOURCE.read_bytes(), _live_manifest(tool),
                 engineering_hashes, infrastructure_hashes) is None


def test_refresh_refuses_a_registry_at_the_same_path_with_other_bytes():
    """Content lock: an internally consistent registry that is neither the
    reviewed 101 input nor the approved 102 output refuses at the same path."""
    tool = _tool()
    forged = json.loads(_before_bytes())
    forged["revision"] = 103
    forged["implementation_digest"] = tool._content_digest(forged["implementation"])
    forged["registry_digest"] = tool._content_digest(
        {key: value for key, value in forged.items() if key != "registry_digest"})
    other_bytes = json.dumps(forged, indent=2, sort_keys=True).encode("utf-8")
    assert hashlib.sha256(other_bytes).hexdigest() not in (
        _EXPECTED_PRE_REFRESH_SHA256, _EXPECTED_POST_REFRESH_SHA256)
    engineering_hashes, infrastructure_hashes = _live_hashes(tool)
    with pytest.raises(tool.RefreshRefused, match="neither the locked 101 input"):
        _plan(tool, other_bytes, _before_text(), engineering_hashes, infrastructure_hashes)


def test_refresh_refuses_a_preserved_101_infrastructure_pin_that_changed():
    """Rejection 1: a changed digest at a preserved Infrastructure path refuses.

    The pin count is unchanged, so a count-only (or name-only) check would pass.
    """
    tool = _tool()
    engineering_hashes, infrastructure_hashes = _live_hashes(tool)
    infrastructure_hashes["database/sqlite.py"] = "sha256:" + "3" * 64
    with pytest.raises(tool.RefreshRefused, match="is not preserved byte-for-byte"):
        _plan(tool, _before_bytes(), _before_text(), engineering_hashes, infrastructure_hashes)


@pytest.mark.parametrize(("drift", "match"), (
    ("reviewed-source-content", "Engineering content drift"),
    ("operation-contract-content", "operation change")))
def test_refresh_refuses_reviewed_source_or_operation_content_drift(drift, match):
    """Rejection 2: same path or same key with different bytes/contract refuses."""
    tool = _tool()
    engineering_hashes, infrastructure_hashes = _live_hashes(tool)
    operations = dict(tool.current_operations())
    if drift == "reviewed-source-content":
        # a reviewed, unchanged source file: the same path with different bytes
        engineering_hashes["domain/artifacts/refs.py"] = "sha256:" + "4" * 64
    else:
        # a reviewed operation: the same key with a different contract
        freeze = operations["engineering.packages.freeze"]
        operations["engineering.packages.freeze"] = {**freeze, "version": "9"}
    with pytest.raises(tool.RefreshRefused, match=match):
        _plan(tool, _before_bytes(), _before_text(), engineering_hashes, infrastructure_hashes,
              operations=operations)


@pytest.mark.parametrize("fact", (
    "ordessa_decision", "decision_contract_version", "pydantic_graph_version",
    "jsonschema_version", "referencing_version"))
def test_refresh_refuses_a_moved_external_dependency_fact_without_local_drift(fact):
    """Rejection 3: the dependency check precedes the "no change" verdict.

    The owned tree is byte-identical (the unchanged run is a no-op), yet a moved
    external fact still refuses, so "no change" is never reported on stale
    dependency evidence.
    """
    tool = _tool()
    engineering_hashes, infrastructure_hashes = _live_hashes(tool)
    live_bytes = tool.RESOURCE.read_bytes()
    live_manifest = _live_manifest(tool)
    facts = tool.current_foreign_facts()
    assert _plan(tool, live_bytes, live_manifest, engineering_hashes, infrastructure_hashes) is None

    current = facts[fact]
    moved = {**facts, fact: ({**current, "added.py": "sha256:" + "0" * 64}
                             if isinstance(current, dict) else "0")}
    with pytest.raises(tool.RefreshRefused, match="dependency drift"):
        _plan(tool, live_bytes, live_manifest, engineering_hashes, infrastructure_hashes, foreign=moved)


@pytest.mark.parametrize("tamper", ("added-module", "engineering-content", "infrastructure-hash",
                                    "operation", "foreign", "infrastructure-name"))
def test_refresh_refuses_unapproved_delta_from_the_real_101(tamper):
    tool = _tool()
    engineering, infrastructure = _live_closures(tool)
    engineering_hashes, infrastructure_hashes = _hashes(tool, engineering, infrastructure)
    integrity_text = _before_text()
    foreign = None
    operations = None
    if tamper == "added-module":
        engineering_hashes["application/orchestration/unreviewed_module.py"] = "sha256:" + "0" * 64
    elif tamper == "engineering-content":
        engineering_hashes["domain/changes/dispatch.py"] = "sha256:" + "2" * 64
    elif tamper == "infrastructure-hash":
        infrastructure_hashes["identifiers.py"] = "sha256:" + "3" * 64
    elif tamper == "operation":
        operations = {**tool.current_operations(), "engineering.new.op": {"version": "1", "inputs": {}, "results": []}}
    elif tamper == "foreign":
        foreign = {**tool.current_foreign_facts(), "jsonschema_version": "0.0.0"}
    else:
        integrity_text = tool._render_manifest(integrity_text, "INFRASTRUCTURE_FILES",
                                               tuple(sorted(set(infrastructure) | {"encoding/extra.py"})))
    with pytest.raises(tool.RefreshRefused):
        _plan(tool, _before_bytes(), integrity_text, engineering_hashes, infrastructure_hashes,
              foreign=foreign, operations=operations)


def _scaffold(monkeypatch, tmp_path, tool):
    """A synthetic tree for the publish/refusal tests only.

    The digests here are deliberate placeholders: these tests exercise ``main``
    with ``build_plan`` monkeypatched, so nothing in this scaffold is refresh or
    migration evidence.
    """
    source = tmp_path / "src" / "ordessa_engineering"
    registry_dir = source / "adapters" / "registry"
    (registry_dir / "resources").mkdir(parents=True)
    (source / "a.py").write_text("x = 1\n", encoding="utf-8")
    integrity = registry_dir / "source_integrity.py"
    integrity.write_text("ENGINEERING_FILES = ('a.py',)\nINFRASTRUCTURE_FILES = ()\n", encoding="utf-8")
    resource = registry_dir / "resources" / "operation_registry.v1.json"
    resource.write_text(json.dumps({
        "schema_version": "engineering-operation-registry/1", "registry_id": "ordessa-engineering.operations",
        "revision": 101, "operations": {}, "implementation": {},
        "implementation_digest": "sha256:" + "0" * 64, "registry_digest": "sha256:" + "0" * 64}) + "\n",
        encoding="utf-8")
    monkeypatch.setattr(tool, "SOURCE", source)
    monkeypatch.setattr(tool, "RESOURCE", resource)
    monkeypatch.setattr(tool, "INTEGRITY", integrity)
    monkeypatch.setattr(tool, "EVIDENCE", tmp_path / "evidence")
    monkeypatch.setattr(tool, "current_foreign_facts", lambda: {})
    monkeypatch.setattr(tool, "current_operations", lambda: {})
    return resource, integrity


def test_main_writes_nothing_when_the_plan_is_refused(monkeypatch, tmp_path):
    tool = _tool()
    resource, integrity = _scaffold(monkeypatch, tmp_path, tool)
    before = (resource.read_bytes(), integrity.read_bytes())

    def refuse(**_kwargs):
        raise tool.RefreshRefused("tampered")

    monkeypatch.setattr(tool, "build_plan", refuse)
    with pytest.raises(tool.RefreshRefused):
        tool.main()
    assert resource.read_bytes() == before[0]
    assert integrity.read_bytes() == before[1]
    assert not (tmp_path / "evidence").exists()


def test_main_publishes_all_artifacts_and_keeps_the_previous_bytes(monkeypatch, tmp_path):
    tool = _tool()
    resource, integrity = _scaffold(monkeypatch, tmp_path, tool)
    monkeypatch.setattr(tool, "build_plan", lambda **_kwargs: {
        "new_integrity_text": "ENGINEERING_FILES = ('a.py',)\nINFRASTRUCTURE_FILES = ()\n",
        "new_registry_text": '{"written": true}\n', "receipt": {"ok": True}})
    assert tool.main() == 0
    assert integrity.read_text(encoding="utf-8").endswith("INFRASTRUCTURE_FILES = ()\n")
    assert resource.read_text(encoding="utf-8") == '{"written": true}\n'
    assert json.loads((tmp_path / "evidence" / "RECEIPT.json").read_text(encoding="utf-8")) == {"ok": True}
    backups = tmp_path / "evidence" / "backup-before-r102"
    assert json.loads((backups / "operation_registry.v1.json").read_text(encoding="utf-8"))["revision"] == 101
    assert (backups / "source_integrity.py").read_text(encoding="utf-8").startswith("ENGINEERING_FILES")


def test_main_reports_a_write_failure_and_leaves_recoverable_evidence(monkeypatch, tmp_path):
    """A write-phase failure fails loudly and is recoverable, not rolled back."""
    tool = _tool()
    resource, integrity = _scaffold(monkeypatch, tmp_path, tool)
    refreshed = "ENGINEERING_FILES = ('a.py',)\nINFRASTRUCTURE_FILES = ()\n# refreshed\n"
    monkeypatch.setattr(tool, "build_plan", lambda **_kwargs: {
        "new_integrity_text": refreshed, "new_registry_text": '{"written": true}\n',
        "receipt": {"ok": True}})
    original = tool._write_atomic
    calls = {"n": 0}

    def flaky(path, text):
        calls["n"] += 1
        if calls["n"] == 4:  # 1 = integrity backup, 2 = integrity, 3 = registry backup, 4 = registry
            raise OSError("disk full")
        original(path, text)

    monkeypatch.setattr(tool, "_write_atomic", flaky)
    with pytest.raises(OSError, match="disk full"):
        tool.main()
    report = json.loads((tmp_path / "evidence" / "RECOVERY.json").read_text(encoding="utf-8"))
    assert report["outcome"] == "write-failed"
    assert report["failed_target"] == "operation_registry.v1.json"
    assert report["already_written"] == ["source_integrity.py"]
    assert report["not_written"] == ["RECEIPT.json"]
    # not a transaction: the integrity file was already replaced and is not rolled
    # back, but its previous bytes are kept so an operator can restore by hand
    assert integrity.read_text(encoding="utf-8") == refreshed
    backup = tmp_path / "evidence" / "backup-before-r102" / "source_integrity.py"
    assert backup.read_text(encoding="utf-8") == "ENGINEERING_FILES = ('a.py',)\nINFRASTRUCTURE_FILES = ()\n"

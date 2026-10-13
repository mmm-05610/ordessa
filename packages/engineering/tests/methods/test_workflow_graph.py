"""Long-chain and cycle counterexamples for the public validation entry.

Every case uses one self-contained bundle with a single registered capability
that declares two outcomes, so only graph diagnostics can appear.
`workflow_steps` is a configurable limit rather than a hard cap, so a legal
large value must still be answered with a ValidationReport instead of a runtime
recursion failure.
"""
from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

import pytest
import yaml

from ordessa_engineering.methods.definitions.models import (
    CapabilityDescriptor, CompilationCapabilities, LoadLimits, MethodSource,
)
from ordessa_engineering.methods.definitions.models.identity import method_digest
from ordessa_engineering.methods.loading.loader import load_method
from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
from ordessa_engineering.methods import validate_method

CONTRACT = {"method_config_schema": None, "workflow_outcomes": ["ok", "no"]}
CAPABILITY = CapabilityDescriptor("cap.one", "operation", "1.0.0",
                                  method_digest("capability-contract", CONTRACT), CONTRACT)
OUTCOMES = ("ok", "no")


def _step(step_id, outcomes):
    return {"id": step_id, "kind": "operation", "operation": "cap.one", "outcomes": outcomes}


def _both(transition):
    """Both registered outcomes take the same transition."""
    return {name: transition for name in OUTCOMES}


def _chain(length, *, tail_back_edge=False):
    steps = []
    for index in range(length):
        if index + 1 < length:
            steps.append(_step(f"s{index}", _both({"next": f"s{index + 1}"})))
        elif tail_back_edge:
            steps.append(_step(f"s{index}", _both({"next": "s0"})))
        else:
            steps.append(_step(f"s{index}", _both({"stop": "done"})))
    return steps


def _diamond():
    return [_step("entry", {"ok": {"next": "left"}, "no": {"next": "right"}}),
            _step("left", _both({"next": "leaf"})),
            _step("right", _both({"next": "leaf"})),
            _step("leaf", _both({"stop": "done"}))]


def _validate(tmp_path, steps, *, limits=None):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    workflow = {"schema_version": 1, "entry": steps[0]["id"], "steps": steps,
                "stop_outcomes": ["done"], "wait_kinds": []}
    # json round-trip detaches sub-objects shared by the helpers; a shared
    # identity serializes as a YAML anchor, which the strict parser refuses.
    content = yaml.safe_dump(json.loads(json.dumps(workflow)), sort_keys=False).encode()
    (bundle / "workflow.yaml").write_bytes(content)
    manifest = {"schema_version": 1, "method_id": "test.method", "release_version": "1.0.0",
                "compiler_contract": "ordessa.methods/v1", "entry": {"resource": "workflow.main"},
                "resources": [{"id": "workflow.main", "kind": "workflow", "path": "workflow.yaml",
                               "media_type": "application/yaml",
                               "sha256": hashlib.sha256(content).hexdigest()}],
                "requires": [{"capability_id": "cap.one", "kind": "operation",
                              "interface_version": "1.0.0",
                              "contract_digest": CAPABILITY.contract_digest}]}
    (bundle / "method.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    result = load_method(MethodSource(bundle), FileResourceReader(),
                         limits=LoadLimits() if limits is None else LoadLimits(workflow_steps=limits))
    assert result.ok, result.error
    return validate_method(result.value, CompilationCapabilities((CAPABILITY,), trust_class="host"))


def test_short_chain_is_valid(tmp_path):
    report = _validate(tmp_path, _chain(2))
    assert report.valid
    assert [item.code for item in report.diagnostics] == []


@pytest.mark.parametrize("length,limit,valid", [
    (37, None, True),
    (64, None, True),
    (65, None, False),
    (37, 32, False),
])
def test_default_step_budget_and_explicit_lower_limit(tmp_path, length, limit, valid):
    report = _validate(tmp_path, _chain(length), limits=limit)
    assert report.valid is valid
    if not valid:
        assert {item.code for item in report.diagnostics} == {"WORKFLOW_STEP_COUNT_INVALID"}


def test_diamond_is_a_dag_not_a_cycle(tmp_path):
    report = _validate(tmp_path, _diamond())
    assert report.valid
    assert not any(item.code == "UNSUPPORTED_FLOW_CYCLE" for item in report.diagnostics)
    assert not any(item.code == "UNREACHABLE_STEP" for item in report.diagnostics)


def test_self_loop_reports_the_cycle(tmp_path):
    report = _validate(tmp_path, [_step("only", _both({"next": "only"}))])
    assert [item.pointer for item in report.diagnostics
            if item.code == "UNSUPPORTED_FLOW_CYCLE"] == ["/steps/only"]


def test_tail_back_edge_reports_the_cycle(tmp_path):
    report = _validate(tmp_path, _chain(5, tail_back_edge=True))
    assert [item.pointer for item in report.diagnostics
            if item.code == "UNSUPPORTED_FLOW_CYCLE"] == ["/steps/s0"]


def test_long_legal_chain_reports_instead_of_failing(tmp_path):
    """1500 steps under a legal limits value must yield a report, not a crash."""
    report = _validate(tmp_path, _chain(1500), limits=1500)
    assert not any(item.code == "UNREACHABLE_STEP" for item in report.diagnostics)


def test_long_chain_tail_back_edge_reports_the_cycle(tmp_path):
    report = _validate(tmp_path, _chain(1500, tail_back_edge=True), limits=1500)
    assert [item.pointer for item in report.diagnostics
            if item.code == "UNSUPPORTED_FLOW_CYCLE"]


def _recursive_reference(edges, entry, by_id):
    """The original recursive form, kept as the order/shape reference."""
    diagnostics = []
    gray, black = set(), set()

    def visit(node):
        if node in gray:
            diagnostics.append(f"/steps/{node}")
            return
        if node in black:
            return
        gray.add(node)
        for child in edges.get(node, ()):
            if child in by_id:
                visit(child)
        gray.remove(node)
        black.add(node)

    visit(entry)
    return diagnostics


def _iterative_under_test(edges, entry, by_id):
    """The traversal now in workflow.py, extracted here to compare orders.

    This mirrors the production loop so the reference and the implementation
    are exercised on identical fixed adjacency without going through a bundle.
    """
    diagnostics = []
    gray, black = set(), set()
    stack = [(entry, 0)]
    while stack:
        node, cursor = stack.pop()
        if cursor:
            gray.discard(node)
            black.add(node)
            continue
        if node in gray:
            diagnostics.append(f"/steps/{node}")
            continue
        if node in black:
            continue
        gray.add(node)
        stack.append((node, 1))
        for child in reversed([item for item in edges.get(node, ()) if item in by_id]):
            stack.append((child, 0))
    return diagnostics


@pytest.mark.parametrize("shape", [
    "self-loop", "two-back-edges", "mutual-pair", "cycle-with-branch",
    "two-cycles-sharing-a-node", "diamond-plus-back-edge",
])
def test_iterative_cycle_diagnostics_match_the_recursive_reference(shape):
    """Fixed adjacency order: iterative output equals the recursive reference.

    Both forms must report the same diagnostics in the same order, so the
    traversal change cannot silently drop or reorder a back-edge. Duplicate
    adjacency entries are kept because they are real edges.
    """
    graphs = {
        "self-loop": ({"only": ["only"]}, "only", {"only"}),
        "two-back-edges": ({"a": ["b", "b"], "b": ["a", "a"]}, "a", {"a", "b"}),
        "mutual-pair": ({"a": ["b"], "b": ["a"]}, "a", {"a", "b"}),
        "cycle-with-branch": ({"a": ["b"], "b": ["c", "a"], "c": ["a", "b"]}, "a", {"a", "b", "c"}),
        "two-cycles-sharing-a-node": (
            {"a": ["b", "c"], "b": ["a"], "c": ["a"], "d": ["a"]}, "a", {"a", "b", "c", "d"}),
        "diamond-plus-back-edge": (
            {"a": ["b", "c"], "b": ["d"], "c": ["d"], "d": ["a"]}, "a", {"a", "b", "c", "d"}),
    }
    edges, entry, by_id = graphs[shape]
    assert _iterative_under_test(edges, entry, by_id) == _recursive_reference(edges, entry, by_id), shape


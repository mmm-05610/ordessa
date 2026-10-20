"""Keep the cross-component closeout regressions in the integration suite.

This guard fingerprints the moved test source instead of importing or running
the old Pacthold test module. Only the SIGKILL test's three source-path setup
statements are excluded from its pre-move body fingerprint; those statements
are checked separately below.
"""
from __future__ import annotations

import ast
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
MOVED_TEST = REPO_ROOT / "tests/integration/environment/test_closeout_environment_dispatch.py"
OLD_TEST = REPO_ROOT / "packages/execution/kernel/tests/environment/test_closeout_environment_dispatch.py"
SIGKILL_TEST = "test_sigkill_after_durable_claim_recovers_unknown_without_redispatch"

# Captured from the pre-move test AST. The body fingerprints cover every test
# statement except the three SIGKILL source-path setup assignments, which are
# explicitly verified by _check_sigkill_source_paths.
EXPECTED_TESTS = (
    ("test_invoke_runs_handler_once_and_persists_result_before_replay", 4,
     "5e73c2c47433c62eb36e97befc1866fa12aa7994d6853b19c7fcdfad93f5a5bf",
     "7f23b08f4adab7d294f316fcde8a871954bb2c01022c3d7d3d3c06e7b979f1a7"),
    ("test_handler_failure_is_durable_unknown_and_never_reissued_after_restart", 4,
     "b09c6d7ed090444ddcf0674fa81be79faf175af9eceb223cab29a3a03a8514a5",
     "37f200e054231bf592dd602889325888f69e69c7218b311702691d3eda7e4508"),
    ("test_policy_refusal_does_not_spend_request_key_before_admission", 4,
     "bf977f8140a6dde9d40e63bc0f49a38351a2b154c307f99675c5f706bc2752a1",
     "7ebfc66d835cadc5decfc83a7f41b37d9e1fd542f7f15bbd5fa0880b0f62e052"),
    ("test_missing_policy_denies_effect_handler_without_spending_key", 2,
     "98fcf42f824170fce2e9757126e1020690602c637c48c1d1da05495c682d8315",
     "e56ada3dd7fd698d3b993a5374e7a386ced97ffbb65c8caf5ef7ca0b18b18a98"),
    ("test_drain_refuses_invoke_before_durable_claim_or_handler", 3,
     "14050e0ccb215bb84eb1588774ce4fe8dbe717c61bb1a64609b84d1e5fca0ffd",
     "3e6c1cce9ae8fd740a5cb79e925458c20b068e96dfd966bdbc37b42df9fd3dc8"),
    ("test_query_reads_namespaced_durable_history_not_only_instance_memory", 4,
     "51ab9bd7203b06be806a7b95b7a31c3cc9a7e2770ef5bb6894083541df173545",
     "6ef652065c64486ead538fa31908c0846aee24ac56255de5119d0f526b686201"),
    ("test_same_key_different_capture_conflicts_after_restart", 1,
     "81ff46f34881648f9dedcccf40503f224ed6c1276a794b4edfab5e5bb21d386f",
     "07b0e9ec26b0864b4786a8e6d394cd7a00aa693c4db27d784a99c7aab2005be0"),
    ("test_activation_stage_reuses_environment_registry_and_retires_through_lifecycle", 8,
     "89a9e93c7f5c55eaf19f83db27b95b5daf64120b8fc1c1b9c59832a186028ff8",
     "543d5f22d289facf51d42b98ace9c2b148fc8213a167d106f90522fdf5c21d46"),
    ("test_reliable_admission_and_claim_linearize_before_drain_but_handler_runs_unlocked", 6,
     "d0f70c3160f71187eff0c324cad6e8e8974bf4bc7693593c9c82ac4f36aae339",
     "4982db859579d752e921f13a4d55f3ca17230ac8be655350a4885c553325c658"),
    ("test_raw_handler_has_one_in_process_claim_for_concurrent_same_key", 5,
     "a8e52322f00a359b984f784caa2105fec26b4273825fff516cfa57137060bafd",
     "3038bec4d2a97944e16fcf3a976b66758325e34fdc85b9a0682884b88391b92a"),
    (SIGKILL_TEST, 5,
     "0470d6aaf3dea14b54c5072aa9bc12b5566917b3439e50daaa39e7874d6a883f",
     "3cd07bf9d0e0d1cfbd6b564c1cab31f6b42cfcf346baebe2335d2a57a1f4b510"),
)
EXPECTED_MODULE_DIGEST = "3f8dd24e19a2052a0b76712f11dfe414e5d61c29bb7b559466ed2b471be4decd"


def _canonical(node):
    if isinstance(node, ast.AST):
        # Python 3.12+ expose empty type_params on definitions; omit only the
        # empty optional field so a real generic signature still fingerprints.
        fields = ((key, _canonical(value)) for key, value in ast.iter_fields(node)
                  if not (key == "type_params" and not value))
        return (type(node).__name__, tuple(fields))
    if isinstance(node, (list, tuple)):
        return tuple(_canonical(value) for value in node)
    if isinstance(node, bytes):
        return {"bytes": node.hex()}
    return node


def _digest(node) -> str:
    canonical = json.dumps(_canonical(node), ensure_ascii=False, sort_keys=True,
                           separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _function_nodes(tree: ast.Module) -> list[ast.FunctionDef]:
    return [node for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")]


def _check_sigkill_source_paths(function: ast.FunctionDef) -> None:
    assert len(function.body) >= 4
    setup = function.body[:3]
    assert all(isinstance(node, ast.Assign) and len(node.targets) == 1
               for node in setup)
    targets = [node.targets[0].id if isinstance(node.targets[0], ast.Name) else None
               for node in setup]
    assert targets == ["test_file", "repo_root", "sources"]

    expected_repo_root = ast.parse("test_file.parents[3]", mode="eval").body
    assert _canonical(setup[1].value) == _canonical(expected_repo_root)

    expected_sources = ast.parse(
        "["
        "str(repo_root / 'packages' / 'backend' / 'pacthold' / 'src'),"
        "str(repo_root / 'packages' / 'backend' / 'environment-api' / 'src'),"
        "str(repo_root / 'packages' / 'backend' / 'persistence-sqlite' / 'src'),"
        "]",
        mode="eval",
    ).body
    assert _canonical(setup[2].value) == _canonical(expected_sources)


def _assert_source_preserved(source: str | None) -> None:
    assert source is not None, "moved integration test source is missing"
    tree = ast.parse(source)
    functions = _function_nodes(tree)
    actual = []
    for function in functions:
        assertions = sorted((node for node in ast.walk(function) if isinstance(node, ast.Assert)),
                            key=lambda node: (node.lineno, node.col_offset))
        normalized = deepcopy(function)
        if function.name == SIGKILL_TEST:
            _check_sigkill_source_paths(function)
            normalized.body = normalized.body[3:]
        actual.append((function.name, len(assertions), _digest(tuple(assertions)), _digest(normalized)))

    assert tuple(actual) == EXPECTED_TESTS
    assert sum(item[1] for item in actual) == 46

    normalized_tree = deepcopy(tree)
    sigkill = next(node for node in _function_nodes(normalized_tree)
                   if node.name == SIGKILL_TEST)
    sigkill.body = sigkill.body[3:]
    assert _digest(normalized_tree) == EXPECTED_MODULE_DIGEST


def test_closeout_regressions_are_collected_from_integration_location():
    assert MOVED_TEST.is_file(), f"expected moved test at {MOVED_TEST}"
    assert not OLD_TEST.exists(), f"integration test still sits in kernel tree: {OLD_TEST}"
    _assert_source_preserved(MOVED_TEST.read_text(encoding="utf-8"))


def test_placement_guard_rejects_missing_test_and_changed_assertion():
    source = MOVED_TEST.read_text(encoding="utf-8")
    with pytest.raises(AssertionError, match="source is missing"):
        _assert_source_preserved(None)

    tree = ast.parse(source)
    tree.body = [node for node in tree.body
                 if not (isinstance(node, ast.FunctionDef)
                         and node.name == "test_policy_refusal_does_not_spend_request_key_before_admission")]
    with pytest.raises(AssertionError):
        _assert_tree_preserved(tree)

    tree = ast.parse(source)
    target = next(node for node in _function_nodes(tree)
                  if node.name == "test_policy_refusal_does_not_spend_request_key_before_admission")
    next(node for node in ast.walk(target) if isinstance(node, ast.Assert)).test = ast.Constant(value=False)
    with pytest.raises(AssertionError):
        _assert_tree_preserved(tree)


def _assert_tree_preserved(tree: ast.Module) -> None:
    """AST-only counterpart used to demonstrate that the guard catches edits."""
    functions = _function_nodes(tree)
    actual = []
    for function in functions:
        assertions = sorted((node for node in ast.walk(function) if isinstance(node, ast.Assert)),
                            key=lambda node: (node.lineno, node.col_offset))
        normalized = deepcopy(function)
        if function.name == SIGKILL_TEST:
            _check_sigkill_source_paths(function)
            normalized.body = normalized.body[3:]
        actual.append((function.name, len(assertions), _digest(tuple(assertions)), _digest(normalized)))
    assert tuple(actual) == EXPECTED_TESTS

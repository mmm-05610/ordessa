#!/usr/bin/env python3
"""Controlled fixture driver for the Python gate case ledger.

Run only from a disposable environment with pytest already supplied. This file
is prepared for the parent to execute; it was not run by the candidate author.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from typing import Any


def load_runner(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("verify_clean_python_gates", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load candidate runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_junit(path: Path, *, tests: int = 1, failures: int = 0, errors: int = 0,
                skipped: int = 0, cases: str | None = None,
                root_totals: str = "") -> None:
    body = cases if cases is not None else (
        '<testcase classname="fixture" name="test_ok"><properties>'
        '<property name="ordessa_nodeid" value="test_case.py::test_ok"/>'
        '</properties></testcase>'
    )
    path.write_text(
        f'<testsuites{root_totals}><testsuite name="pytest" tests="{tests}" failures="{failures}" '
        f'errors="{errors}" skipped="{skipped}">{body}</testsuite></testsuites>',
        encoding="utf-8",
    )


def assert_junit_rejections(runner: Any, root: Path) -> list[str]:
    cases = root / "xml-cases"
    cases.mkdir()
    valid_id = "test_case.py::test_ok"
    good = ('<testcase classname="fixture" name="test_ok"><properties>'
            f'<property name="ordessa_nodeid" value="{valid_id}"/>'
            '</properties></testcase>')
    fixtures = [
        ("malformed", "<testsuites><testsuite", [valid_id], "JUnit XML"),
        ("missing-id", '<testcase classname="fixture" name="test_ok"/>', [valid_id], "exactly one ordessa_nodeid"),
        ("duplicate-property", '<testcase><properties><property name="ordessa_nodeid" value="x"/><property name="ordessa_nodeid" value="x"/></properties></testcase>', ["x"], "exactly one ordessa_nodeid"),
        ("wrong-id", good.replace(valid_id, "other.py::test_ok"), [valid_id], "ID sequence differs"),
        ("duplicate-id", good + good, [valid_id, "other.py::test_other"], "duplicate ordessa_nodeid"),
        ("count-mismatch", good, [valid_id], "tests summary"),
        ("failure-summary-mismatch", good.replace("</testcase>", "<failure/> </testcase>"), [valid_id], "failures summary"),
        ("skip-marker", good.replace("</testcase>", "<skipped/> </testcase>"), [valid_id], "non-PASS testcase markers"),
        ("nested-case", '<testsuite name="nested" tests="1" failures="0" errors="0" skipped="0"><testsuite><testcase/></testsuite></testsuite>', [valid_id], "nested or non-direct testcase"),
        ("multiple-suite", '<testsuites><testsuite tests="0" failures="0" errors="0" skipped="0"/><testsuite tests="0" failures="0" errors="0" skipped="0"/></testsuites>', [], "expected one pytest testsuite"),
    ]
    accepted: list[str] = []
    for name, body, expected, message in fixtures:
        path = cases / f"{name}.xml"
        if name == "malformed":
            path.write_text(body, encoding="utf-8")
        elif name == "multiple-suite":
            path.write_text(body, encoding="utf-8")
        else:
            tests = 2 if name in {"count-mismatch", "duplicate-id"} else 1
            failures = 1 if name == "failure-summary-mismatch" else 0
            skipped = 1 if name == "skip-marker" else 0
            if name == "failure-summary-mismatch":
                body = good
            write_junit(path, tests=tests, failures=failures, skipped=skipped, cases=body)
        try:
            parsed = runner.validate_junit_case_ledger(path, expected)
            runner.assert_all_junit_cases_pass(parsed)
        except Exception as error:
            if message.lower() not in str(error).lower() and name != "malformed":
                raise AssertionError(f"{name}: rejected for wrong reason: {error}") from error
            accepted.append(name)
        else:
            raise AssertionError(f"{name}: invalid JUnit fixture was accepted")
    # Empty XML remains invalid even if it declares internally consistent zero counts.
    empty_path = cases / "empty-cases.xml"
    write_junit(empty_path, tests=0, cases="")
    try:
        runner.validate_junit_case_ledger(empty_path, [])
    except ValueError as error:
        if "zero testcase" not in str(error).lower():
            raise AssertionError(f"empty-cases: rejected for wrong reason: {error}") from error
        accepted.append("empty-cases")
    else:
        raise AssertionError("empty-cases: zero-test JUnit XML was accepted")

    valid_root_totals = cases / "root-totals-valid.xml"
    write_junit(valid_root_totals, root_totals=' tests="1" failures="0" errors="0" skipped="0"')
    parsed = runner.validate_junit_case_ledger(valid_root_totals, [valid_id])
    runner.assert_all_junit_cases_pass(parsed)
    accepted.append("root-totals-valid")

    for name, root_attrs, message in [
        ("root-negative-total", ' tests="-1" failures="0" errors="0" skipped="0"', "does not match testcase totals"),
        ("root-malformed-total", ' tests="NaN" failures="0" errors="0" skipped="0"', "invalid tests total"),
        ("root-total-mismatch", ' tests="2" failures="0" errors="0" skipped="0"', "does not match testcase totals"),
    ]:
        path = cases / f"{name}.xml"
        write_junit(path, root_totals=root_attrs)
        try:
            runner.validate_junit_case_ledger(path, [valid_id])
        except ValueError as error:
            if message.lower() not in str(error).lower():
                raise AssertionError(f"{name}: rejected for wrong reason: {error}") from error
            accepted.append(name)
        else:
            raise AssertionError(f"{name}: invalid testsuites aggregate total was accepted")

    suite_negative = cases / "suite-negative-total.xml"
    write_junit(suite_negative, tests=-1)
    try:
        runner.validate_junit_case_ledger(suite_negative, [valid_id])
    except ValueError as error:
        if "does not match testcase markers" not in str(error).lower():
            raise AssertionError(f"suite-negative-total: rejected for wrong reason: {error}") from error
        accepted.append("suite-negative-total")
    else:
        raise AssertionError("suite-negative-total: negative suite total was accepted")

    id_a, id_b = "test_case.py::test_a", "test_case.py::test_b"
    reordered = cases / "reordered-ids.xml"
    body = ''.join(
        f'<testcase><properties><property name="ordessa_nodeid" value="{nodeid}"/></properties></testcase>'
        for nodeid in (id_b, id_a)
    )
    write_junit(reordered, tests=2, cases=body)
    try:
        runner.validate_junit_case_ledger(reordered, [id_a, id_b])
    except ValueError as error:
        if "sequence differs" not in str(error).lower():
            raise AssertionError(f"reordered-ids: rejected for wrong reason: {error}") from error
        accepted.append("reordered-ids")
    else:
        raise AssertionError("reordered-ids: correct ID set in wrong order was accepted")
    return accepted


def test_group(runner: Any, python: str, root: Path, name: str, source: str,
              expected_status: str, expected_execution: str) -> dict[str, Any]:
    snapshot = root / f"snapshot-{name}"
    run_dir = root / f"run-{name}"
    (snapshot / "tooling/checks").mkdir(parents=True)
    run_dir.mkdir()
    candidate = Path(__file__).resolve().parents[1] / "checks"
    shutil.copyfile(candidate / "verify_clean_pytest_plugin.py", snapshot / "tooling/checks/verify_clean_pytest_plugin.py")
    shutil.copyfile(candidate / "verify_clean_python_gates.py", snapshot / "tooling/checks/verify_clean_python_gates.py")
    (snapshot / "test_case.py").write_text(source, encoding="utf-8")
    group = {"id": name, "legacy_target": f"fixture::{name}", "targets": ["test_case.py"]}
    if name == "empty-mapped-target":
        (snapshot / "empty").mkdir()
        (snapshot / "empty/test_no_cases.py").write_text("VALUE = 1\n", encoding="utf-8")
        group["targets"].append("empty")
    result = runner.run_group(snapshot, run_dir, python, group)
    if result.get("status") != expected_status or result.get("execution_status") != expected_execution:
        raise AssertionError(f"{name}: expected {expected_status}/{expected_execution}, got {result}")
    return result


def assert_manifest_rejections(runner: Any, root: Path) -> list[str]:
    """Prove invalid manifests fail before any group runner can start pytest."""
    snapshot = root / "manifest-snapshot"
    (snapshot / "tooling/checks").mkdir(parents=True)
    (snapshot / "test_case.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    base = {
        "schema": runner.MANIFEST_SCHEMA,
        "groups": [
            {"id": group_id, "legacy_target": f"fixture::{group_id}", "targets": ["test_case.py"]}
            for group_id in runner.EXPECTED_GROUP_IDS
        ],
    }
    cases: list[tuple[str, Any, str]] = []
    cases.append(("empty-groups", {**base, "groups": []}, "exactly 9"))
    cases.append(("deleted-group", {**base, "groups": base["groups"][:-1]}, "exactly 9"))
    duplicate = [dict(item) for item in base["groups"]]
    duplicate[-1]["id"] = duplicate[0]["id"]
    cases.append(("duplicate-group-id", {**base, "groups": duplicate}, "duplicate group IDs"))
    cases.append(("empty-targets", {**base, "groups": [{**base["groups"][0], "targets": []}, *base["groups"][1:]]}, "nonempty list"))
    cases.append(("duplicate-mapped-target", {**base, "groups": [{**base["groups"][0], "targets": ["test_case.py", "test_case.py"]}, *base["groups"][1:]]}, "duplicate mapped target"))
    results: list[str] = []
    original = runner.run_group
    def forbidden_run_group(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("invalid manifest reached run_group")
    runner.run_group = forbidden_run_group
    try:
        for name, manifest, expected in cases:
            manifest_path = root / f"{name}.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            run_dir = root / f"manifest-run-{name}"
            argv = ["verify_clean_python_gates.py", "--snapshot", str(snapshot),
                    "--run-dir", str(run_dir), "--manifest", str(manifest_path)]
            old_argv = sys.argv
            sys.argv = argv
            output = io.StringIO()
            try:
                with contextlib.redirect_stdout(output):
                    rc = runner.main()
            finally:
                sys.argv = old_argv
            result_path = run_dir / "python-ledger-results.json"
            result = json.loads(result_path.read_text(encoding="utf-8"))
            if rc == 0 or result.get("status") != "FAIL" or expected.lower() not in result.get("validation_error", "").lower():
                raise AssertionError(f"{name}: expected fail-closed manifest rejection, rc={rc}, result={result}, output={output.getvalue()}")
            results.append(name)
    finally:
        runner.run_group = original
    return results


def assert_target_and_exitstatus_rejections(runner: Any, root: Path) -> list[str]:
    snapshot = root / "target-snapshot"
    snapshot.mkdir()
    (snapshot / "test_case.py").write_text("def test_ok(): pass\n", encoding="utf-8")
    cases: list[tuple[str, list[str], str]] = [
        ("empty-targets-direct", [], "nonempty list"),
        ("absolute-target", [str(snapshot / "test_case.py")], "relative"),
        ("parent-target", ["../outside.py"], "within snapshot"),
        ("missing-target", ["missing_test.py"], "absent"),
        ("duplicate-target", ["test_case.py", "test_case.py"], "duplicate mapped target"),
    ]
    results: list[str] = []
    for name, targets, expected in cases:
        group = {"id": name, "legacy_target": f"fixture::{name}", "targets": targets}
        value = runner.run_group(snapshot, root / f"run-{name}", sys.executable, group)
        if value.get("status") != "FAIL" or value.get("execution_status") != "NOT_RUN" or expected not in value.get("reason", ""):
            raise AssertionError(f"{name}: invalid target was not rejected before execution: {value}")
        results.append(name)

    for name, data, child_rc, accepted in [
        ("exitstatus-equal-zero", {"pytest_exitstatus": 0}, 0, True),
        ("exitstatus-equal-nonzero", {"pytest_exitstatus": 2}, 2, True),
        ("exitstatus-missing", {}, 0, False),
        ("exitstatus-mismatch", {"pytest_exitstatus": 0}, 2, False),
        ("exitstatus-string", {"pytest_exitstatus": "0"}, 0, False),
    ]:
        try:
            runner.validate_pytest_exitstatus(data, child_rc, name)
        except ValueError:
            if accepted:
                raise AssertionError(f"{name}: matching pytest exit status was rejected")
        else:
            if not accepted:
                raise AssertionError(f"{name}: missing or inconsistent pytest exit status was accepted")
        results.append(name)
    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--python", required=True, help="parent-supplied isolated Python with pytest already available")
    parser.add_argument("--owned-root", required=True, type=Path, help="new empty directory under the caller-owned nightly cache")
    args = parser.parse_args()
    owned_root = args.owned_root.resolve()
    owned_root.mkdir(parents=True, exist_ok=False)
    runner_path = Path(__file__).resolve().parents[1] / "checks/verify_clean_python_gates.py"
    runner = load_runner(runner_path)
    report: dict[str, Any] = {"status": "PASS", "python_scenarios": [], "junit_rejections": [], "manifest_rejections": [], "target_and_exitstatus_rejections": []}
    try:
        report["junit_rejections"] = assert_junit_rejections(runner, owned_root)
        report["manifest_rejections"] = assert_manifest_rejections(runner, owned_root)
        report["target_and_exitstatus_rejections"] = assert_target_and_exitstatus_rejections(runner, owned_root)
        scenarios = [
            ("pass", "def test_ok():\n    assert 2 + 2 == 4\n", "PASS", "EXECUTED_CLEAN"),
            ("skip", "import pytest\n@pytest.mark.skip(reason='controlled skip')\ndef test_skip():\n    assert True\n", "FAIL", "EXECUTED_WITH_FAILURE"),
            ("xfail", "import pytest\n@pytest.mark.xfail(reason='controlled xfail')\ndef test_xfail():\n    assert False\n", "FAIL", "EXECUTED_WITH_FAILURE"),
            ("xpass", "import pytest\n@pytest.mark.xfail(reason='controlled strict-false xpass', strict=False)\ndef test_xpass():\n    assert True\n", "FAIL", "EXECUTED_WITH_FAILURE"),
            ("empty-mapped-target", "def test_ok():\n    assert 2 + 2 == 4\n", "FAIL", "NOT_RUN"),
            ("collection-error", "def test_bad(:\n    pass\n", "FAIL", "NOT_RUN"),
        ]
        for name, source, status, execution_status in scenarios:
            report["python_scenarios"].append(test_group(runner, args.python, owned_root, name, source, status, execution_status))
    except Exception as error:
        report["status"] = "FAIL"
        report["error"] = f"{type(error).__name__}: {error}"
        (owned_root / "fixture-result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        raise
    (owned_root / "fixture-result.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Run each legacy Python gate scope with collected-ID and JUnit reconciliation."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
from typing import Any


MANIFEST_SCHEMA = "verify-clean-current-python-gates/1"
EXPECTED_GROUP_IDS = (
    "pacthold_kernel",
    "harness",
    "server",
    "acp_orchestration",
    "environment_api",
    "kernel_persistence",
    "platform_services",
    "cross_persistence",
    "all_current_python_supplement",
)


def validate_targets(snapshot: Path, targets: Any) -> None:
    if not isinstance(targets, list) or not targets:
        raise ValueError("group targets must be a nonempty list")
    root = snapshot.resolve()
    seen: set[str] = set()
    for target in targets:
        if not isinstance(target, str) or not target or "\\" in target:
            raise ValueError(f"invalid mapped target path: {target!r}")
        relative = PurePosixPath(target)
        if relative.is_absolute() or any(part == ".." for part in relative.parts):
            raise ValueError(f"mapped target must be a relative path within snapshot: {target!r}")
        if relative.as_posix() != target and target != ".":
            raise ValueError(f"mapped target must be a normalized relative path: {target!r}")
        if target in seen:
            raise ValueError(f"duplicate mapped target: {target}")
        seen.add(target)
        resolved = (root / Path(target)).resolve()
        if not resolved.is_relative_to(root):
            raise ValueError(f"mapped target resolves outside snapshot: {target!r}")
        if not resolved.exists():
            raise ValueError(f"mapped target is absent: {target}")
        if resolved.is_file() and (resolved.suffix != ".py"):
            raise ValueError(f"mapped file target is not Python: {target}")
        if not resolved.is_file() and not resolved.is_dir():
            raise ValueError(f"mapped target is neither a Python file nor directory: {target}")
        if resolved.is_dir() and not any(resolved.rglob("test_*.py")) and not any(resolved.rglob("*_test.py")):
            raise ValueError(f"mapped directory contains no test_*.py or *_test.py source files: {target}")


def validate_manifest(snapshot: Path, data: Any) -> list[dict[str, Any]]:
    if not isinstance(data, dict) or data.get("schema") != MANIFEST_SCHEMA:
        raise ValueError(f"manifest schema must be {MANIFEST_SCHEMA!r}")
    groups = data.get("groups")
    if not isinstance(groups, list) or len(groups) != len(EXPECTED_GROUP_IDS):
        raise ValueError(f"manifest must contain exactly {len(EXPECTED_GROUP_IDS)} original groups")
    ids: list[str] = []
    for group in groups:
        if not isinstance(group, dict):
            raise ValueError("each manifest group must be an object")
        group_id = group.get("id")
        if not isinstance(group_id, str) or not group_id:
            raise ValueError("each manifest group must have a nonempty id")
        ids.append(group_id)
        legacy_target = group.get("legacy_target")
        if not isinstance(legacy_target, str) or not legacy_target:
            raise ValueError(f"{group_id}: missing legacy_target")
        validate_targets(snapshot, group.get("targets"))
    if len(ids) != len(set(ids)):
        raise ValueError("manifest contains duplicate group IDs")
    if set(ids) != set(EXPECTED_GROUP_IDS):
        missing = sorted(set(EXPECTED_GROUP_IDS) - set(ids))
        extra = sorted(set(ids) - set(EXPECTED_GROUP_IDS))
        raise ValueError(f"manifest group IDs differ from the original nine; missing={missing}, extra={extra}")
    return groups


def validate_pytest_exitstatus(data: Any, child_returncode: int, phase: str) -> None:
    if not isinstance(data, dict) or type(data.get("pytest_exitstatus")) is not int:
        raise ValueError(f"{phase} recorder lacks an integer pytest_exitstatus")
    if data["pytest_exitstatus"] != child_returncode:
        raise ValueError(f"{phase} recorder pytest_exitstatus {data['pytest_exitstatus']} differs from child return code {child_returncode}")


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def junit_case_ledger(path: Path) -> dict[str, Any]:
    """Read pytest JUnit XML without relying on pytest's mangled classname/name."""
    if not path.is_file():
        raise ValueError("JUnit XML missing")
    root = ET.parse(path).getroot()
    if root.tag == "testsuite":
        suites = [root]
    elif root.tag == "testsuites":
        suites = root.findall("testsuite")
    else:
        raise ValueError(f"unexpected JUnit root element: {root.tag}")
    if len(suites) != 1:
        raise ValueError(f"expected one pytest testsuite, found {len(suites)}")

    suite = suites[0]
    cases = suite.findall("testcase")
    if len(root.findall(".//testcase")) != len(cases):
        raise ValueError("nested or non-direct testcase elements are unsupported")
    if not cases:
        raise ValueError("JUnit XML contains zero testcase entries")
    ids: list[str] = []
    failures: list[str] = []
    errors: list[str] = []
    skips: list[str] = []
    for index, case in enumerate(cases):
        properties = case.findall("./properties/property")
        named = [prop for prop in properties if prop.get("name") == "ordessa_nodeid"]
        if len(named) != 1:
            raise ValueError(f"testcase[{index}] must have exactly one ordessa_nodeid property")
        nodeid = named[0].get("value")
        if not nodeid:
            raise ValueError(f"testcase[{index}] has an empty ordessa_nodeid")
        ids.append(nodeid)
        outcomes = [child.tag for child in case if child.tag in {"failure", "error", "skipped"}]
        if len(outcomes) > 1:
            raise ValueError(f"testcase[{index}] has multiple outcome markers")
        label = nodeid
        if outcomes == ["failure"]:
            failures.append(label)
        elif outcomes == ["error"]:
            errors.append(label)
        elif outcomes == ["skipped"]:
            skips.append(label)

    if len(ids) != len(set(ids)):
        raise ValueError("JUnit XML contains duplicate ordessa_nodeid properties")
    declared = {}
    actual = {"tests": len(cases), "failures": len(failures), "errors": len(errors), "skipped": len(skips)}
    for key, count in actual.items():
        raw = suite.get(key)
        if raw is None:
            raise ValueError(f"JUnit testsuite lacks required {key} summary")
        try:
            parsed = int(raw)
        except ValueError as error:
            raise ValueError(f"JUnit testsuite has invalid {key} summary: {raw!r}") from error
        if parsed < 0 or parsed != count:
            raise ValueError(f"JUnit {key} summary {parsed} does not match testcase markers {count}")
        declared[key] = parsed

    # Pytest's current testsuites wrapper normally has only a name attribute.
    # If a producer supplies aggregate totals there, validate rather than ignore them.
    if root.tag == "testsuites":
        for key, count in actual.items():
            raw = root.get(key)
            if raw is None:
                continue
            try:
                parsed = int(raw)
            except ValueError as error:
                raise ValueError(f"JUnit testsuites root has invalid {key} total: {raw!r}") from error
            if parsed < 0 or parsed != count:
                raise ValueError(f"JUnit testsuites root {key} total {parsed} does not match testcase totals {count}")

    return {"ids": ids, **actual, "declared": declared,
            "bad_ids": failures + errors + skips}


def validate_junit_case_ledger(path: Path, expected_ids: list[str]) -> dict[str, Any]:
    data = junit_case_ledger(path)
    if not isinstance(expected_ids, list) or not expected_ids or any(not isinstance(nodeid, str) or not nodeid for nodeid in expected_ids):
        raise ValueError("expected collected node-ID sequence is empty or malformed")
    if len(expected_ids) != len(set(expected_ids)):
        raise ValueError("expected collected node-ID sequence contains duplicates")
    if data["ids"] != expected_ids:
        raise ValueError("JUnit ordessa_nodeid sequence differs from original collected node IDs")
    return data


def assert_all_junit_cases_pass(data: dict[str, Any]) -> None:
    if data["bad_ids"]:
        raise ValueError(f"JUnit contains non-PASS testcase markers: {data['bad_ids']}")


def run_group(snapshot: Path, run_dir: Path, python: str, group: dict[str, Any]) -> dict[str, Any]:
    gate_id = group["id"]
    targets = group.get("targets") if isinstance(group, dict) else None
    result: dict[str, Any] = {"id": gate_id, "legacy_target": group.get("legacy_target") if isinstance(group, dict) else None, "targets": targets}
    try:
        validate_targets(snapshot, targets)
    except ValueError as error:
        result.update(status="FAIL", execution_status="NOT_RUN", reason=str(error))
        return result

    collect_json = run_dir / f"{gate_id}.collect.json"
    collect_out = run_dir / f"{gate_id}.collect.stdout"
    collect_err = run_dir / f"{gate_id}.collect.stderr"
    run_json = run_dir / f"{gate_id}.run.json"
    run_out = run_dir / f"{gate_id}.run.stdout"
    run_err = run_dir / f"{gate_id}.run.stderr"
    junit = run_dir / f"{gate_id}.junit.xml"
    target_args = targets
    env = os.environ.copy()
    env["PYTHONPATH"] = str(snapshot / "tooling/checks")
    env["ORDESSA_VERIFY_LEDGER_JSON"] = str(collect_json)
    common = [python, "-m", "pytest", "-p", "verify_clean_pytest_plugin", "-p", "no:cacheprovider", *target_args]
    collected = subprocess.run(common[:3] + ["--collect-only", "-q"] + common[3:], cwd=snapshot, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    collect_out.write_text(collected.stdout, encoding="utf-8", errors="replace")
    collect_err.write_text(collected.stderr, encoding="utf-8", errors="replace")
    result["collect_rc"] = collected.returncode
    if not collect_json.is_file():
        result.update(status="FAIL", execution_status="NOT_RUN", reason="collection recorder absent; execution NOT_RUN")
        return result
    try:
        cdata = json.loads(collect_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        result.update(status="FAIL", execution_status="NOT_RUN", reason=f"collection recorder invalid; execution NOT_RUN: {error}")
        return result
    if not isinstance(cdata, dict):
        result.update(status="FAIL", execution_status="NOT_RUN", reason="collection recorder is not an object; execution NOT_RUN")
        return result
    try:
        validate_pytest_exitstatus(cdata, collected.returncode, "collection")
    except ValueError as error:
        result.update(status="FAIL", execution_status="NOT_RUN", reason=str(error))
        return result
    if collected.returncode != 0:
        collected_value = cdata.get("collected_nodeids", [])
        collected_count = len(collected_value) if isinstance(collected_value, list) else 0
        result.update(status="FAIL", execution_status="NOT_RUN", collected_count=collected_count, reason="collection failed/interrupted; execution NOT_RUN")
        return result
    collected_ids = cdata.get("collected_nodeids", [])
    if not isinstance(collected_ids, list) or any(not isinstance(nodeid, str) or not nodeid for nodeid in collected_ids):
        result.update(status="FAIL", reason="collection recorder has malformed node IDs")
        return result
    result["collected_count"] = len(collected_ids)
    if not collected_ids or len(collected_ids) != len(set(collected_ids)):
        result.update(status="FAIL", reason="empty or duplicate collected node IDs")
        return result

    # A nonempty aggregate must not conceal a mapped target that collected no cases.
    case_paths = [Path(nodeid.split("::", 1)[0]) for nodeid in collected_ids]
    coverage = {}
    for target in targets:
        mapped = Path(target)
        if (snapshot / mapped).is_file():
            count = sum(case == mapped for case in case_paths)
        else:
            count = sum(case.is_relative_to(mapped) for case in case_paths)
        coverage[target] = count
    result["target_collected_counts"] = coverage
    if any(count == 0 for count in coverage.values()):
        result.update(status="FAIL", execution_status="NOT_RUN", reason="mapped target collected zero test cases")
        return result

    env["ORDESSA_VERIFY_LEDGER_JSON"] = str(run_json)
    run_cmd = [python, "-m", "pytest", "-q", "--junitxml", str(junit), "-p", "verify_clean_pytest_plugin", "-p", "no:cacheprovider", *target_args]
    executed = subprocess.run(run_cmd, cwd=snapshot, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    run_out.write_text(executed.stdout, encoding="utf-8", errors="replace")
    run_err.write_text(executed.stderr, encoding="utf-8", errors="replace")
    result["run_rc"] = executed.returncode
    if not run_json.is_file():
        result.update(status="FAIL", execution_status="INCOMPLETE", reason="execution recorder absent")
        return result
    try:
        rdata = json.loads(run_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        result.update(status="FAIL", execution_status="INCOMPLETE", reason=f"execution recorder invalid: {error}")
        return result
    if not isinstance(rdata, dict):
        result.update(status="FAIL", execution_status="INCOMPLETE", reason="execution recorder is not an object")
        return result
    try:
        validate_pytest_exitstatus(rdata, executed.returncode, "execution")
    except ValueError as error:
        result.update(status="FAIL", execution_status="INCOMPLETE", reason=str(error))
        return result
    run_ids = rdata.get("collected_nodeids", [])
    reports = rdata.get("reports", {})
    if not isinstance(run_ids, list) or any(not isinstance(nodeid, str) or not nodeid for nodeid in run_ids):
        result.update(status="FAIL", reason="execution recorder has malformed node IDs")
        return result
    result["executed_collection_count"] = len(run_ids)
    if run_ids != collected_ids:
        result.update(status="FAIL", reason="collected IDs changed between discovery and execution")
        return result
    if not isinstance(reports, dict) or set(reports) != set(collected_ids):
        result.update(status="FAIL", reason="executed report ID set differs from collected IDs")
        return result

    bad: list[dict[str, Any]] = []
    required_stages = {"setup", "call", "teardown"}
    for nodeid in collected_ids:
        stages = reports.get(nodeid)
        if not isinstance(stages, dict) or set(stages) != required_stages:
            bad.append({"nodeid": nodeid, "status": "FAIL_OR_INCOMPLETE", "stages": stages})
            continue
        malformed_stage = any(not isinstance(stages[stage], list) or len(stages[stage]) != 1
                              or not isinstance(stages[stage][0], dict)
                              or not isinstance(stages[stage][0].get("outcome"), str)
                              for stage in required_stages)
        if malformed_stage:
            bad.append({"nodeid": nodeid, "status": "FAIL_OR_INCOMPLETE", "stages": stages})
            continue
        stage_records = [stages[stage][0] for stage in required_stages]
        outcomes = {stage: [stages[stage][0]["outcome"]] for stage in required_stages}
        wasxfail = [record.get("wasxfail") for record in stage_records if record.get("wasxfail") is not None]
        if wasxfail:
            bad.append({"nodeid": nodeid, "status": "XFAIL_OR_XPASS", "wasxfail": wasxfail, "stages": outcomes})
        elif any(value == "skipped" for values in outcomes.values() for value in values):
            bad.append({"nodeid": nodeid, "status": "SKIP", "stages": outcomes})
        elif any(value != "passed" for values in outcomes.values() for value in values) or any(len(values) != 1 for values in outcomes.values()):
            bad.append({"nodeid": nodeid, "status": "FAIL_OR_INCOMPLETE", "stages": outcomes})

    try:
        xml_data = validate_junit_case_ledger(junit, collected_ids)
    except (OSError, ValueError, ET.ParseError) as error:
        result.update(status="FAIL", execution_status="INCOMPLETE", reason=f"JUnit report invalid: {error}")
        return result
    xml_ids = xml_data["ids"]
    xml_bad_ids = xml_data["bad_ids"]
    result.update(junit_count=xml_data["tests"], junit_failures=xml_data["failures"],
                  junit_errors=xml_data["errors"], junit_skips=xml_data["skipped"],
                  junit_ids_match=(xml_ids == collected_ids), junit_summary=xml_data["declared"])
    if executed.returncode != 0 or xml_bad_ids or bad:
        result.update(status="FAIL", execution_status="EXECUTED_WITH_FAILURE", reason="nonzero pytest exit, failure, error, skip, incomplete stage, or non-passing case observed", bad_cases=bad[:50], junit_bad_cases=xml_bad_ids[:50])
        return result
    result.update(status="PASS", execution_status="EXECUTED_CLEAN", reason="all collected IDs executed once with all three passing phases, no xfail/skip, exact JUnit IDs, and matching clean summary totals")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", required=True, type=Path)
    parser.add_argument("--run-dir", required=True, type=Path)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--python", default=sys.executable)
    args = parser.parse_args()
    try:
        data = json.loads(args.manifest.read_text(encoding="utf-8"))
        groups = validate_manifest(args.snapshot, data)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        args.run_dir.mkdir(parents=True, exist_ok=True)
        write_json(args.run_dir / "python-ledger-results.json", {
            "status": "FAIL", "groups": [], "validation_error": str(error),
        })
        print(f"FAIL manifest validation: {error}")
        return 1
    results: list[dict[str, Any]] = []
    failed = False
    for group in groups:
        group_result = run_group(args.snapshot, args.run_dir, args.python, group)
        if group_result["status"] != "PASS":
            failed = True
        print(f"{group_result['status']} {group['id']} collected={group_result.get('collected_count', 0)}")
        results.append(group_result)
    write_json(args.run_dir / "python-ledger-results.json", {"status": "FAIL" if failed else "PASS", "groups": results})
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

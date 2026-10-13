"""Counterexamples for declared semantics, using fresh captured bytes each time."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest
import yaml

from ordessa_engineering.methods.definitions.models import CapabilityDescriptor, CompilationCapabilities, MethodSource
from ordessa_engineering.methods.loading.loader import load_method
from ordessa_engineering.adapters.filesystem.resource_reader import FileResourceReader
from ordessa_engineering.methods import validate_method

ROOT = Path(__file__).resolve().parents[4]


def _test_decision_policies(standard):
    """Synthetic policy dimensions only in the copied counterexample bundle.

    Production assets intentionally defer semantic pass pending calibration.
    Compiler negatives must still exercise declared choice/score/noul policy
    validation without reintroducing a threshold into those real assets.
    """
    for criterion in standard["criteria"]:
        vocabulary = criterion.get("answer_vocabulary")
        if not vocabulary:
            continue
        policy = {"calibration_profile_id": "test-only-unactivated",
                  "activation": "matching_validated_evaluation_required",
                  "missing_evaluation": "manual", "truncation": "unknown"}
        if vocabulary["kind"] == "choice":
            options = [item["option_id"] for item in vocabulary["options"]]
            policy.update(minimum_selected_probability="0.5", selected_option=options[0],
                option_statuses={option: "threshold_dependent" if option == options[0]
                                 else "violated" for option in options}, below_threshold="manual")
        elif vocabulary["kind"] == "score":
            policy.update(minimum_expected_index="1.0", minimum_top_level_probability="0.5",
                          below_threshold="manual")
        else:
            policy.update(maximum_p_true="0.5", above_threshold="manual")
        criterion["decision_policy"] = policy


def _prepare(tmp_path, *, resource_id=None, mutate=None, manifest_mutate=None):
    source = ROOT / "methods" / "incremental-engineering"
    bundle = tmp_path / "bundle"
    shutil.copytree(source, bundle, ignore=shutil.ignore_patterns("bundle-lock.json"))
    manifest = yaml.safe_load((bundle / "method.yaml").read_text())
    if resource_id:
        declaration = next(row for row in manifest["resources"] if row["id"] == resource_id)
        path = bundle / declaration["path"]
        value = yaml.safe_load(path.read_text())
        if declaration["kind"] == "standard":
            _test_decision_policies(value)
        mutate(value)
        raw = yaml.safe_dump(value, sort_keys=False).encode()
        path.write_bytes(raw)
        declaration["sha256"] = hashlib.sha256(raw).hexdigest()
    if manifest_mutate:
        manifest_mutate(manifest)
    (bundle / "method.yaml").write_text(yaml.safe_dump(manifest, sort_keys=False))
    result = load_method(MethodSource(bundle), FileResourceReader())
    assert result.ok, result.error
    rows = json.loads((bundle / "contracts/capability-catalog.json").read_text())["capabilities"]
    capabilities = CompilationCapabilities(tuple(CapabilityDescriptor(row["capability_id"], row["kind"], row["interface_version"], row["contract_digest"], row["contract"]) for row in rows), trust_class="fixture")
    return validate_method(result.value, capabilities)


def test_real_declarations_validate(tmp_path):
    assert _prepare(tmp_path).valid


@pytest.mark.parametrize("change,code", [
    (lambda m: m["documents"][0].update(validation_target="payload"), "METHOD_STRUCTURE_INVALID"),
    (lambda m: m["documents"][0].update(template={"resource": "workflow.change_cycle"}), "DOCUMENT_TEMPLATE_REF_INVALID"),
    (lambda m: m.update(skills={"executor": {"resource": "workflow.change_cycle"}}), "SKILL_REF_INVALID"),
])
def test_manifest_semantics_rejected(tmp_path, change, code):
    report = _prepare(tmp_path, manifest_mutate=change)
    assert not report.valid
    assert code in {item.code for item in report.diagnostics}


@pytest.mark.parametrize("change,code", [
    (lambda w: w["steps"][0].update(next="await_proposal"), "UNSUPPORTED_FLOW_CYCLE"),
    (lambda w: w["steps"][1]["inputs"].update(target="undeclared"), "WORKFLOW_CONTEXT_UNKNOWN"),
    (lambda w: w["steps"][0]["bind"].update(undeclared="event.proposal_ref"), "WORKFLOW_BINDING_INVALID"),
    (lambda w: w["steps"][0].update(shell="echo bypass"), "METHOD_STRUCTURE_INVALID"),
])
def test_workflow_semantics_rejected(tmp_path, change, code):
    report = _prepare(tmp_path, resource_id="workflow.change_cycle", mutate=change)
    assert not report.valid
    assert code in {item.code for item in report.diagnostics}


@pytest.mark.parametrize("change,code", [
    (lambda s: s["criteria"][2]["policy"].update(unknown="pass"), "UNKNOWN_CANNOT_PASS"),
    (lambda s: s["criteria"][2]["decision_policy"].update(minimum_selected_probability="1.01"), "THRESHOLD_OUT_OF_RANGE"),
    (lambda s: s["criteria"][2]["decision_policy"].update(missing_evaluation="pass"), "MISSING_EVALUATION_CANNOT_PASS"),
    (lambda s: s["criteria"][2]["decision_policy"].update(selected_option="missing"), "DECISION_OPTION_POLICY_INVALID"),
    (lambda s: s["criteria"][2]["checks"][0]["bindings"].update(question_ids=["missing"]), "QUESTION_BINDING_INVALID"),
])
def test_standard_semantics_rejected(tmp_path, change, code):
    report = _prepare(tmp_path, resource_id="standard.source_review", mutate=change)
    assert not report.valid
    assert code in {item.code for item in report.diagnostics}


def test_question_vocabulary_must_match_criterion(tmp_path):
    report = _prepare(tmp_path, resource_id="decision.source_support", mutate=lambda q: q["questions"][0].update(kind="score"))
    assert not report.valid
    assert "QUESTION_VOCABULARY_MISMATCH" in {item.code for item in report.diagnostics}


@pytest.mark.parametrize("change,code", [
    (lambda s: s["criteria"][2]["decision_policy"].update(minimum_expected_index="3.0"), "THRESHOLD_OUT_OF_RANGE"),
    (lambda s: s["criteria"][2]["decision_policy"].update(minimum_top_level_probability="1.1"), "THRESHOLD_OUT_OF_RANGE"),
    (lambda s: s["criteria"][2]["answer_vocabulary"]["levels"][1].update(index=0), "ANSWER_VOCABULARY_INVALID"),
    (lambda s: s["criteria"][2]["decision_policy"].update(selected_option="complete"), "DECISION_POLICY_KIND_MISMATCH"),
    (lambda s: s["criteria"][3]["decision_policy"].update(below_threshold="manual"), "DECISION_POLICY_KIND_MISMATCH"),
])
def test_score_and_noul_policy_dimensions(tmp_path, change, code):
    report = _prepare(tmp_path, resource_id="standard.quality_review", mutate=change)
    assert not report.valid
    assert code in {item.code for item in report.diagnostics}

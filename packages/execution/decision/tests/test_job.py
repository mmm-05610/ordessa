"""decision-job/1 validation: closed keys, references and lowered limits."""
import pytest

from ordessa_decision import DecisionError, default_host_limits, validate_job


def job(**overrides):
    value = {
        "spec_version": "decision-job/1", "job_id": "job-1", "version": 1,
        "input": {"score": 7, "tags": ["a", "b"]},
        "limits": {"max_model_calls": 1, "max_steps": 4,
                   "max_value_bytes": 4096, "timeout_seconds": 5.0},
        "steps": [{"id": "first", "type": "rules", "engine": None, "when": {"fact": "input.score", "op": "gte", "value": 5},
                   "payload": {"values": {"doubled": "input.score * 2"}}}],
        "result": {"from": "first", "path": ["values", "doubled"]},
    }
    value.update(overrides)
    return value


def test_valid_job_is_accepted_and_defaults_are_conservative():
    parsed = validate_job(job())
    assert parsed.job_id == "job-1"
    assert parsed.steps[0]["id"] == "first"
    assert default_host_limits()["max_model_calls"] >= 1


@pytest.mark.parametrize("mutate,code", [
    (lambda v: v.update(extra=1), "invalid_job"),
    (lambda v: v.update(spec_version="decision-job/2"), "invalid_job"),
    (lambda v: v["steps"][0].update(id=""), "invalid_identifier"),
    (lambda v: v.update(steps=[v["steps"][0], dict(v["steps"][0])]), "duplicate_step"),
    (lambda v: v["steps"][0].update(type="branch"), "invalid_step"),
    (lambda v: v["steps"][0].update(type="ask", engine="cel"), "invalid_step"),
    (lambda v: v["steps"][0].update(when={"fact": "input.score", "op": "matches", "value": "x"}),
     "invalid_when"),
    (lambda v: v["result"].update({"from": "unknown"}), "result_references_unknown_step"),
    (lambda v: v["limits"].update(max_steps=40), "limit_exceeds_host"),
    (lambda v: v["limits"].update(max_model_calls=True), "invalid_limit"),
    (lambda v: v["steps"][0].pop("payload"), "invalid_step"),
])
def test_invalid_jobs_are_refused(mutate, code):
    value = job()
    mutate(value)
    with pytest.raises(DecisionError) as refused:
        validate_job(value)
    assert refused.value.code == code


@pytest.mark.parametrize("question,code", [
    ({"kind": "choice", "text": "Pick", "options": {"a": "A"}}, "invalid_question"),
    ({"kind": "choice", "text": "Pick", "options": {"a": "A", "b": "B"},
      "scale": ("x", "y")}, "invalid_question"),
    ({"kind": "score", "text": "Pick", "scale": ("one",)}, "invalid_question"),
    ({"kind": "noul", "text": "Pick", "options": {"a": "A"}}, "invalid_question"),
    ({"kind": "choice", "text": "", "options": {"a": "A", "b": "B"}}, "invalid_question"),
    ({"kind": "choice", "text": "Pick", "options": {"a": "A", "b": "B"},
      "unknown": 1}, "invalid_question"),
    ({"kind": "choice", "text": "Pick", "options": {"a": "A", "b": "B"},
      "policy_ref": {"policy_id": ""}}, "invalid_question"),
])
def test_ask_questions_are_refused_before_any_effect(question, code):
    value = job(steps=[{"id": "ask", "type": "ask", "engine": None,
                        "when": {"fact": "input.score", "op": "gte", "value": 0},
                        "payload": {"question": question}}],
                result={"from": "ask", "path": ["answer"]})
    with pytest.raises(DecisionError) as refused:
        validate_job(value)
    assert refused.value.code == code

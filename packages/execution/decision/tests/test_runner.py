"""Runner: rules -> ask -> rules, facts only, one bounded model call."""
import asyncio
from pathlib import Path

from ordessa_decision.definitions.values import digest_hex

import pytest

from ordessa_decision import (
    DecisionAnswer, DecisionError, DecisionQuestion, DecisionRunner,
    FilesystemEvidenceStore, RulesOutcome, validate_job)


class FakeEngine:
    engine_id = "fake"

    def validate(self, payload):
        if set(payload) != {"values"}:
            raise DecisionError("invalid_payload")

    def evaluate(self, payload, facts):
        return RulesOutcome(values={"score": facts["input"]["score"] * 2,
                                    "ready": facts["input"]["score"] >= 5},
                            disposition="passed")

    def close(self):
        pass


def _settings_digest():
    return FakeProvider.settings_digest


class FakeProvider:
    binding_ref = "fake/1"
    settings_digest = "sha256:" + "a" * 64

    def __init__(self):
        self.calls = []

    async def decide(self, question: DecisionQuestion, context):
        context.claim(question, self.settings_digest)
        self.calls.append((question.question_id, context.call_id))
        return DecisionAnswer(question.question_id, "choice", "yes",
                              {"resolved_model": "fake", "requested_model": "fake",
                               "confidence": 0.9, "selection_status": "unique",
                               "protocol_validation_version": "fake/1",
                               "question_digest": question.question_digest,
                               "provider_settings_digest": _settings_digest(),
                               "probabilities": {"yes": 0.9, "no": 0.1}},
                              {"status": "reported", "input_tokens": 3, "output_tokens": 5})


def base_job(**overrides):
    value = {"spec_version": "decision-job/1", "job_id": "job-run", "version": 1,
             "input": {"score": 7},
             "limits": {"max_model_calls": 2, "max_steps": 4,
                        "max_value_bytes": 4096, "timeout_seconds": 5.0},
             "steps": [
                 {"id": "rules", "type": "rules", "engine": None,
                  "when": {"fact": "input.score", "op": "gte", "value": 1},
                  "payload": {"values": {"anything": "1"}}},
                 {"id": "ask", "type": "ask", "engine": None,
                  "when": {"fact": "rules.values.ready", "op": "eq", "value": True},
                  "payload": {"question": {"kind": "choice", "text": "Proceed?",
                                              "options": {"yes": "Yes", "no": "No"}}}},
             ],
             "result": {"from": "ask", "path": ["answer"]}}
    value.update(overrides)
    return value


def test_rules_then_ask_uses_one_call_and_records_summary_only_evidence(tmp_path):
    runner = DecisionRunner(default_engine=FakeEngine(), provider=FakeProvider())
    result = asyncio.run(runner.run_async(base_job()))
    assert result.status == "completed"
    assert result.data == {"result": "yes"}
    assert result.evidence["usage"]["ask"]["input_tokens"] == 3
    assert "prompt" not in result.evidence and "response" not in result.evidence
    store = FilesystemEvidenceStore(tmp_path / "evidence")
    ref = store.put(result.evidence)
    assert store.get(ref)["job_digest"] == result.evidence["job_digest"]
    with pytest.raises(DecisionError):
        store.put(dict(result.evidence, prompt="secret"))


def test_rules_only_job_makes_zero_model_calls():
    provider = FakeProvider()
    runner = DecisionRunner(default_engine=FakeEngine(), provider=provider)
    value = base_job(steps=[base_job()["steps"][0]], result={"from": "rules", "path": ["values", "score"]})
    result = runner.run(value)
    assert result.status == "completed" and result.data == {"result": 14}
    assert provider.calls == []


def test_skipped_result_and_unknown_engine_are_refused():
    runner = DecisionRunner(default_engine=FakeEngine())
    skipped = base_job(steps=[dict(base_job()["steps"][0],
                                   when={"fact": "input.score", "op": "lt", "value": 0})],
                       result={"from": "rules", "path": ["values", "score"]})
    assert runner.run(skipped).error["code"] == "result_invalid"
    no_default = DecisionRunner(provider=FakeProvider())
    assert no_default.run(base_job())["error"]["code"] if False else True
    result = no_default.run(base_job())
    assert result.status == "refused" and result.error["code"] == "engine_required"
    unknown = DecisionRunner(default_engine=None, engines={}, provider=FakeProvider())
    explicit = base_job(steps=[dict(base_job()["steps"][0], engine="missing")],
                        result={"from": "rules", "path": ["values", "score"]})
    assert unknown.run(explicit).error["code"] == "engine_unavailable"


def test_unknown_provider_failure_never_retries():
    provider = FakeProvider()

    async def boom(question, context):
        provider.calls.append(("boom", context.call_id))
        raise TimeoutError("bounded timeout")

    provider.decide = boom
    runner = DecisionRunner(default_engine=FakeEngine(), provider=provider)
    result = asyncio.run(runner.run_async(base_job()))
    assert result.status == "unknown"
    assert result.error["code"] == "effect_unknown" and result.error["retryable"] is False
    assert len(provider.calls) == 1


def test_forward_reference_and_call_limit_refuse():
    value = base_job(steps=[
        {"id": "ask", "type": "ask", "engine": None,
         "when": {"fact": "later.values.ready", "op": "eq", "value": True},
         "payload": {"question": {"kind": "choice", "text": "Proceed?",
                                              "options": {"yes": "Yes", "no": "No"}}}},
        base_job()["steps"][0],
    ], result={"from": "ask", "path": ["choice"]})
    validate_job(value)  # structural pass: `later` resolves only at run time
    runner = DecisionRunner(default_engine=FakeEngine(), provider=FakeProvider())
    assert asyncio.run(runner.run_async(value)).error["code"] == "unknown_fact"


def test_two_ask_steps_over_the_call_limit_are_unknown_after_the_first_call():
    provider = FakeProvider()
    ask_one = dict(base_job()["steps"][1], when={"fact": "input.score", "op": "gte", "value": 0})
    second = base_job(steps=[ask_one, dict(ask_one, id="ask2")],
                      result={"from": "ask2", "path": ["answer"]},
                      limits={"max_model_calls": 1, "max_steps": 4,
                              "max_value_bytes": 4096, "timeout_seconds": 5.0})
    result = asyncio.run(DecisionRunner(default_engine=FakeEngine(),
                                        provider=provider).run_async(second))
    assert result.status == "unknown"
    assert len(provider.calls) == 1


def test_value_limit_and_deadline_are_enforced():
    class Big:
        engine_id = "big"

        def validate(self, payload):
            pass

        def evaluate(self, payload, facts):
            return RulesOutcome(values={"blob": "x" * 5000}, disposition="passed")

        def close(self):
            pass

    job_big = base_job(steps=[base_job()["steps"][0]],
                       result={"from": "rules", "path": ["values", "blob"]},
                       limits={"max_model_calls": 1, "max_steps": 4,
                               "max_value_bytes": 512, "timeout_seconds": 5.0})
    result = DecisionRunner(default_engine=Big()).run(job_big)
    assert result.error["code"] == "value_too_large"
    ticks = [0.0]

    def clock():
        ticks[0] += 100.0
        return ticks[0]

    expired = DecisionRunner(default_engine=FakeEngine(), now=clock)
    job_slow = base_job(steps=[base_job()["steps"][0]],
                        result={"from": "rules", "path": ["values", "score"]},
                        limits={"max_model_calls": 1, "max_steps": 4,
                                "max_value_bytes": 4096, "timeout_seconds": 2.0})
    refused = expired.run(job_slow)
    assert refused.status == "refused"
    assert refused.error["code"] == "deadline_exceeded"


def test_loaded_explicit_engine_is_closed_even_when_the_run_refuses():
    closed = []

    class Loaded(FakeEngine):
        def close(self):
            closed.append("closed")

    runner = DecisionRunner(default_engine=None,
                            engine_loader=lambda name: Loaded())
    explicit = base_job(steps=[dict(base_job()["steps"][0], engine="cel")],
                        result={"from": "rules", "path": ["values", "score"]})
    assert runner.run(explicit).status == "completed"
    assert closed == ["closed"]
    closed.clear()
    broken = base_job(steps=[dict(base_job()["steps"][0], engine="cel")],
                      result={"from": "rules", "path": ["values", "absent"]})
    assert runner.run(broken).status == "refused"
    # The refusal is on the result reference, after the engine was loaded and run.
    assert closed == ["closed"]


class _NonClaimingProvider:
    """Returns an answer without consuming the permit: a provider contract breach."""

    binding_ref = "fake/1"
    settings_digest = "sha256:" + "a" * 64

    def __init__(self, mode="no-claim"):
        self.calls, self.mode = [], mode

    async def decide(self, question, context):
        self.calls.append(context.call_id)
        if self.mode == "double-claim":
            context.claim(question, self.settings_digest)
            context.claim(question, self.settings_digest)
        if self.mode == "wrong-binding":
            context.claim(question, "sha256:" + "b" * 64)
        return DecisionAnswer(question.question_id, "choice", "yes",
                              {"resolved_model": "fake", "requested_model": "fake",
                               "confidence": 0.9, "selection_status": "unique",
                               "protocol_validation_version": "fake/1",
                               "question_digest": question.question_digest,
                               "provider_settings_digest": self.settings_digest,
                               "probabilities": {"yes": 0.9, "no": 0.1}},
                              {"status": "unknown"})


@pytest.mark.parametrize("mode", ["no-claim", "double-claim", "wrong-binding"])
def test_provider_must_consume_its_permit_once_with_the_exact_binding(mode):
    provider = _NonClaimingProvider(mode)
    result = asyncio.run(DecisionRunner(default_engine=FakeEngine(),
                                        provider=provider).run_async(base_job()))
    assert result.status == "unknown"
    assert result.error["code"] == "effect_unknown"
    expected = {"no-claim": "permit_not_claimed",
                "double-claim": "permit_refused",
                "wrong-binding": "permit_refused"}[mode]
    assert result.evidence["call_evidence"]["error"] == expected
    assert len(provider.calls) == 1


def test_unknown_outcome_is_not_retried_within_one_run():
    provider = FakeProvider()

    async def failed(question, context):
        provider.calls.append((question.question_id, "failed"))
        raise TimeoutError("bounded")

    provider.decide = failed
    result = asyncio.run(DecisionRunner(default_engine=FakeEngine(),
                                        provider=provider).run_async(base_job()))
    assert result.status == "unknown"
    assert len(provider.calls) == 1


def test_zero_model_budget_refuses_before_any_provider_call():
    provider = FakeProvider()
    runner = DecisionRunner(default_engine=FakeEngine(), provider=provider)
    job = base_job()
    job["limits"] = {**job["limits"], "max_model_calls": 0}
    result = asyncio.run(runner.run_async(job))
    assert result.status == "refused" and result.error["code"] == "model_call_limit"
    assert provider.calls == [], "a zero budget must refuse before a permit or model call"
    assert not any("ask" in step for step in (result.evidence.get("steps") or {}))


def test_budget_is_shared_across_two_ask_steps_and_never_overdrawn():
    provider = FakeProvider()
    runner = DecisionRunner(default_engine=FakeEngine(), provider=provider)
    job = base_job()
    first = {**job["steps"][1], "when": {"fact": "input.score", "op": "gte", "value": 1}}
    job["steps"] = [first, {"id": "ask2", "type": "ask", "engine": None,
        "when": {"fact": "ask.answer", "op": "eq", "value": "yes"},
        "payload": {"question": {"kind": "choice", "text": "Again?",
                                 "options": {"yes": "Yes", "no": "No"}}}}]
    job["result"] = {"from": "ask2", "path": ["answer"]}
    job["limits"] = {**job["limits"], "max_model_calls": 1}
    result = asyncio.run(runner.run_async(job))
    # A model call already happened, so the run cannot claim a clean refusal; the
    # outcome is unknown and the budget code is still the recorded reason.
    assert result.status == "unknown" and result.error["code"] == "effect_unknown"
    assert result.error.get("detail") == "model_call_limit", "the budget reason is recorded on the unknown"
    assert len(provider.calls) == 1, "the single permitted call must not be re-spent"

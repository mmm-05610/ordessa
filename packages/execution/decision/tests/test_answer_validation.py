"""§11.1 answer revalidation: kinds, tie, legend, probabilities, two asks."""
import asyncio

import pytest

from decision_runtime import DecisionAnswer, DecisionRunner, RulesOutcome
from decision_runtime.definitions.values import digest_hex


class Engine:
    engine_id = "fake"

    def validate(self, payload):
        pass

    def evaluate(self, payload, facts):
        return RulesOutcome(values={"ran": True}, disposition="passed")

    def close(self):
        pass


class Provider:
    binding_ref = "fake/1"
    settings_digest = digest_hex({"binding": "fake/1"})

    def __init__(self, factory):
        self.factory = factory
        self.calls = []

    async def decide(self, question, context):
        context.claim(question, self.settings_digest)
        self.calls.append((question.question_id, context.attempt_no))
        return self.factory(question)


def job(steps, result, limits=None):
    return {"spec_version": "decision-job/1", "job_id": "answers", "version": 1,
            "input": {"n": 1},
            "limits": limits or {"max_model_calls": 3, "max_steps": 5,
                                 "max_value_bytes": 65536, "timeout_seconds": 5.0},
            "steps": steps, "result": result}


def ask(step_id, kind, **question):
    body = {"kind": kind, "text": "Pick"}
    body.update(question)
    return {"id": step_id, "type": "ask", "engine": None,
            "when": {"fact": "input.n", "op": "gte", "value": 0},
            "payload": {"question": body}}


def choice_answer(question, value, **receipt):
    base = {"resolved_model": "fake", "requested_model": "fake", "confidence": 0.7,
            "selection_status": "unique", "protocol_validation_version": "fake/1",
            "question_digest": question.question_digest,
            "provider_settings_digest": digest_hex({"binding": "fake/1"}),
            "probabilities": {"a": 0.7, "b": 0.3}}
    base.update(receipt)
    return DecisionAnswer(question.question_id, "choice", value, base, {"status": "unknown"})


def run(provider, **kwargs):
    runner = DecisionRunner(default_engine=Engine(), provider=provider)
    return asyncio.run(runner.run_async(job(**kwargs)))


def test_two_ask_steps_use_attempt_ordinals_and_record_receipts():
    provider = Provider(lambda q: choice_answer(q, "a"))
    steps = [ask("first", "choice", options={"a": "A", "b": "B"}),
             ask("second", "choice", options={"a": "A", "b": "B"})]
    result = run(provider, steps=steps, result={"from": "second", "path": ["answer"]})
    assert result.status == "completed" and result.data == {"result": "a"}
    assert [call[1] for call in provider.calls] == [1, 2]
    assert set(result.evidence["receipt"]) == {"first", "second"}


def test_score_and_noul_answer_shapes_are_validated():
    score = Provider(lambda q: DecisionAnswer(
        q.question_id, "score", 1.7,
        {"resolved_model": "fake", "requested_model": "fake",
         "protocol_validation_version": "fake/1",
         "question_digest": q.question_digest,
         "provider_settings_digest": digest_hex({"binding": "fake/1"}),
         "legend": {"0": "low", "1": "mid", "2": "high"},
         "probabilities": {"0": 0.1, "1": 0.1, "2": 0.8}},
        {"status": "reported", "input_tokens": 1, "output_tokens": 2}))
    result = run(score, steps=[ask("s", "score", scale=("low", "mid", "high"))],
                 result={"from": "s", "path": ["answer"]})
    assert result.status == "completed" and result.data == {"result": 1.7}
    noul = Provider(lambda q: DecisionAnswer(
        q.question_id, "noul", 0.6,
        {"resolved_model": "fake", "requested_model": "fake",
         "protocol_validation_version": "fake/1", "question_digest": q.question_digest,
         "provider_settings_digest": digest_hex({"binding": "fake/1"})},
        {"status": "unknown"}))
    ok = run(noul, steps=[ask("n", "noul")], result={"from": "n", "path": ["answer"]})
    assert ok.status == "completed" and ok.data == {"result": 0.6}


@pytest.mark.parametrize("factory", [
    lambda q: choice_answer(q, None),
    lambda q: choice_answer(q, "a", selection_status="tie", tied_option_ids=["a"]),
    lambda q: choice_answer(q, "a", probabilities={"a": 0.5, "b": 0.5}),
    lambda q: choice_answer(q, "a", probabilities={"a": 1.5, "b": -0.5}),
    lambda q: choice_answer(q, "b", probabilities={"a": 0.7, "b": 0.3}),
    lambda q: choice_answer(q, "a", probabilities={"a": 0.6, "x": 0.4}),
])
def test_invalid_choice_answers_become_unknown_after_the_call(factory):
    provider = Provider(factory)
    result = run(provider, steps=[ask("c", "choice", options={"a": "A", "b": "B"})],
                 result={"from": "c", "path": ["answer"]})
    assert result.status == "unknown"
    assert result.error["code"] == "effect_unknown"
    assert len(provider.calls) == 1


def test_score_guess_without_legend_is_refused_as_unknown():
    provider = Provider(lambda q: DecisionAnswer(
        q.question_id, "score", 1.0,
        {"resolved_model": "fake", "requested_model": "fake",
         "probabilities": {"0": 0.1, "1": 0.2, "2": 0.7}}, {"status": "unknown"}))
    result = run(provider, steps=[ask("s", "score", scale=("low", "mid", "high"))],
                 result={"from": "s", "path": ["answer"]})
    assert result.status == "unknown"


@pytest.mark.parametrize("mutate", [
    lambda receipt: receipt.pop("question_digest"),
    lambda receipt: receipt.update(question_digest="sha256:" + "0" * 64),
    lambda receipt: receipt.update(provider_settings_digest="sha256:" + "0" * 64),
    lambda receipt: receipt.update(protocol_validation_version=""),
    lambda receipt: receipt.pop("resolved_model"),
])
def test_receipt_binding_failures_are_unknown_after_the_call(mutate):
    def factory(question):
        answer = choice_answer(question, "a")
        receipt = dict(answer.provider_receipt)
        mutate(receipt)
        return DecisionAnswer(question.question_id, "choice", "a", receipt,
                              {"status": "unknown"})
    provider = Provider(factory)
    result = run(provider, steps=[ask("c", "choice", options={"a": "A", "b": "B"})],
                 result={"from": "c", "path": ["answer"]})
    assert result.status == "unknown"
    assert len(provider.calls) == 1

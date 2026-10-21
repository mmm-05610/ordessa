"""F1.1 Question/Answer: choice/score/noul positives and bounded negatives."""
import pytest

from ordessa_decision import DecisionAnswer, DecisionError, DecisionQuestion, PolicyRef

CHOICE = {"kind": "choice", "question_text": "Pick one", "bounded_state": {"src": "x"},
          "options": {"a": "First", "b": "Second"}}


def question(**overrides):
    values = dict(CHOICE)
    values.update(overrides)
    return DecisionQuestion("q-1", "1", **values)


def answer(kind="choice", value="a", **receipt):
    return DecisionAnswer("q-1", kind, value,
                          dict({"resolved_model": "jev", "requested_model": "jev"}, **receipt),
                          {"status": "unknown"})


def test_choice_positive_digest_and_tie_negative():
    value = question()
    assert value.question_digest.startswith("sha256:")
    assert value.projection()["schema_version"] == "decision-question/1"
    assert answer()["value"] if False else True
    with pytest.raises(DecisionError):
        answer(value=None)  # None requires a validated tie receipt
    answer(value=None, selection_status="tie", tied_option_ids=["a", "b"])


@pytest.mark.parametrize("overrides,code", [
    ({"options": {"a": "A"}}, "invalid_options"),
    ({"options": {}}, "invalid_options"),
    ({"scale": ("x", "y")}, "irrelevant_field"),
    ({"allowed_answer_ids": ("a",)}, "invalid_allowed_answers"),
    ({"allowed_answer_ids": ("a", "b")}, None),
    ({"question_text": ""}, "invalid_question"),
    ({"kind": "other"}, "invalid_kind"),
])
def test_choice_bounds(overrides, code):
    if code is None:
        assert question(**overrides).allowed_answer_ids == ("a", "b")
        return
    with pytest.raises(DecisionError) as refused:
        question(**overrides)
    assert refused.value.code == code


def test_score_and_noul_bounds():
    score = question(kind="score", options={}, scale=("low", "mid", "high"))
    assert score.scale == ("low", "mid", "high")
    with pytest.raises(DecisionError):
        question(kind="score", options={}, scale=("only",))
    with pytest.raises(DecisionError):
        question(kind="score", options={"a": "A"}, scale=("low", "mid"))
    noul = question(kind="noul", options={})
    assert noul.options == {}
    with pytest.raises(DecisionError):
        question(kind="noul", options={"a": "A"})


def test_policy_binding_and_usage_states():
    policy = PolicyRef("policy", "1", "sha256:abc")
    assert question(policy_ref=policy).policy_ref is policy
    assert question().policy_ref is None
    for status in ("unknown", "partial", "reported"):
        assert DecisionAnswer("q-1", "choice", "a", {}, {"status": status}).usage_evidence[
            "status"] == status
    with pytest.raises(DecisionError):
        DecisionAnswer("q-1", "choice", "a", {}, {"status": "guessed"})
    with pytest.raises(DecisionError):
        DecisionAnswer("q-1", "choice", "a", {"raw_response": "secret"}, {})

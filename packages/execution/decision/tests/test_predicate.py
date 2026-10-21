"""Neutral `when` predication; missing facts are refused, never skipped."""
import pytest

from ordessa_decision import DecisionError, evaluate_when

FACTS = {"input": {"score": 7, "tags": ["a", "b"], "name": "demo"},
         "prepare": {"values": {"ok": True}}}


def test_comparisons_and_in():
    assert evaluate_when({"fact": "input.score", "op": "eq", "value": 7}, FACTS)
    assert evaluate_when({"fact": "input.score", "op": "gt", "value": 3}, FACTS)
    assert evaluate_when({"fact": "input.name", "op": "in", "value": ["demo", "x"]}, FACTS)
    assert not evaluate_when({"fact": "input.score", "op": "lt", "value": 3}, FACTS)


def test_combinators():
    when = {"all": [{"fact": "prepare.values.ok", "op": "eq", "value": True},
                    {"any": [{"fact": "input.score", "op": "gte", "value": 7},
                             {"fact": "input.score", "op": "lt", "value": 0}]}]}
    assert evaluate_when(when, FACTS)
    assert evaluate_when({"not": {"fact": "input.score", "op": "gt", "value": 100}}, FACTS)


@pytest.mark.parametrize("when", [
    {"fact": "input.missing", "op": "eq", "value": 1},
    {"fact": "input.score", "op": "between", "value": [1, 2]},
    {"fact": "input..score", "op": "eq", "value": 1},
    {"all": []},
    {"any": "nope"},
    {"fact": "input.score", "op": "eq"},
])
def test_invalid_when_is_refused(when):
    with pytest.raises(DecisionError):
        evaluate_when(when, FACTS)

"""`cel` engine tests; the mature dependency is currently BLOCKED (not installed)."""
import pytest

from ordessa_decision.definitions.values import DecisionError
from ordessa_decision_rules_cel import build

PAYLOAD = {"checks": [{"id": "small", "when": "input.price < 10"}], "default": {"ok": True}}


def test_missing_cel_python_is_a_bounded_blocked_refusal():
    try:
        import celpy  # noqa: F401
    except ModuleNotFoundError:
        with pytest.raises(DecisionError) as refused:
            build()
        assert refused.value.code == "cel_unavailable"
    else:  # pragma: no cover - runs only once Codex installs the dependency
        assert build().engine_id == "cel"


def test_cel_semantics_against_the_mature_engine():
    try:
        import celpy  # noqa: F401
    except ModuleNotFoundError:
        pytest.skip("BLOCKED: cel-python not installed by the integration owner")
    engine = build()
    outcome = engine.evaluate(PAYLOAD, {"input": {"price": 3}})
    assert outcome.issues == ()
    failed = engine.evaluate(PAYLOAD, {"input": {"price": 30}})
    assert failed.issues == ({"check": "small", "when": "input.price < 10"},)
    # CEL integer arithmetic, collections and macros (authoritative semantics).
    assert engine.evaluate({"checks": [{"id": "i", "when": "10 / 4 == 2"}],
                           "default": {}}, {}) .issues == ()
    assert engine.evaluate({"checks": [{"id": "x", "when": "input.tags.exists(t, t == 'b')"}],
                           "default": {}}, {"input": {"tags": ["a", "b"]}}).issues == ()

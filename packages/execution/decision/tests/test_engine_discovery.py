"""Real entry-point discovery and default-engine behaviour (no new features)."""
import pytest

from decision_runtime import DecisionError, DecisionRunner, RulesOutcome
from decision_runtime import rules as rules_module


class Engine:
    engine_id = "fake"

    def validate(self, payload):
        pass

    def evaluate(self, payload, facts):
        return RulesOutcome(values={"x": 1}, disposition="passed")

    def close(self):
        pass


def job(engine=None):
    return {"spec_version": "decision-job/1", "job_id": "discovery", "version": 1,
            "input": {"n": 1},
            "limits": {"max_model_calls": 0, "max_steps": 2,
                       "max_value_bytes": 1024, "timeout_seconds": 2.0},
            "steps": [{"id": "rules", "type": "rules", "engine": engine,
                       "when": {"fact": "input.n", "op": "gte", "value": 0},
                       "payload": {"values": {"x": "1"}}}],
            "result": {"from": "rules", "path": ["values", "x"]}}


def test_unknown_entry_point_and_non_allowlisted_engine_refuse():
    with pytest.raises(DecisionError) as refused:
        rules_module.load_rules_engine("definitely-not-installed")
    assert refused.value.code == "engine_not_allowed"
    with pytest.raises(DecisionError) as refused:
        rules_module.load_rules_engine("definitely-not-installed",
                                       allowlist=("definitely-not-installed",))
    assert refused.value.code == "engine_unavailable"
    assert rules_module.ENTRY_POINT_GROUP == "ordessa.decision.rules"


def test_no_default_engine_refuses_and_explicit_engine_without_loader_refuses():
    refused = DecisionRunner(default_engine=None).run(job())
    assert refused.status == "refused" and refused.error["code"] == "engine_required"
    explicit = DecisionRunner(default_engine=None).run(job(engine="cel"))
    assert explicit.status == "refused" and explicit.error["code"] == "engine_unavailable"
    ok = DecisionRunner(default_engine=Engine()).run(job())
    assert ok.status == "completed" and ok.data == {"result": 1}


def test_entry_point_factory_is_a_callable_or_an_object_with_build(monkeypatch):
    class EntryPoint:
        def __init__(self, loaded):
            self._loaded = loaded

        def load(self):
            return self._loaded

    class FactoryObject:
        def build(self):
            return Engine()

    def factory_function():
        return Engine()

    monkeypatch.setattr(rules_module, "_candidates", lambda: {"cel": EntryPoint(factory_function)})
    assert rules_module.load_rules_engine("cel").engine_id == "fake"
    monkeypatch.setattr(rules_module, "_candidates", lambda: {"cel": EntryPoint(FactoryObject())})
    assert rules_module.load_rules_engine("cel").engine_id == "fake"
    monkeypatch.setattr(rules_module, "_candidates", lambda: {"cel": EntryPoint(object())})
    with pytest.raises(DecisionError) as refused:
        rules_module.load_rules_engine("cel")
    assert refused.value.code == "engine_unavailable"

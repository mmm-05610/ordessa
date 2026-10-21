"""`cel` rules engine backed by the mature `cel-python` implementation.

Missing `cel-python` is BLOCKED (`cel_unavailable`), never a reason to evaluate
with a hand-written subset. Payload is the authoritative example shape:
`{"checks": [{"id": str, "when": "<CEL bool expr>"}], "default": {json}}`; a
matching check contributes `{"check": id, "when": expr}` to the outcome values so
the runner can record it faithfully.
"""
from __future__ import annotations

from ordessa_decision.definitions.models import RulesOutcome
from ordessa_decision.definitions.values import DecisionError, plain

ENGINE_ID = "cel"
_MAX_CHECKS = 64


def _celpy():
    try:
        import celpy
        from celpy import celtypes
    except Exception as exc:  # dependency absence is a bounded refusal
        raise DecisionError("cel_unavailable") from exc
    return celpy, celtypes


class CelEngine:
    engine_id = ENGINE_ID

    def validate(self, payload) -> None:
        if type(payload) is not dict or set(payload) != {"checks", "default"}:
            raise DecisionError("invalid_payload")
        checks = payload["checks"]
        if type(checks) is not list or len(checks) > _MAX_CHECKS:
            raise DecisionError("invalid_payload")
        for check in checks:
            if (type(check) is not dict or set(check) != {"id", "when"}
                    or type(check["id"]) is not str or not check["id"]
                    or type(check["when"]) is not str):
                raise DecisionError("invalid_payload")
        plain(payload["default"])
        celpy, _ = _celpy()
        env = celpy.Environment()
        for check in checks:
            try:
                env.compile(check["when"])
            except Exception as exc:
                raise DecisionError("invalid_expression") from exc

    def evaluate(self, payload, facts) -> RulesOutcome:
        self.validate(payload)
        celpy, _ = _celpy()
        environment = celpy.Environment()
        activation = celpy.json_to_cel(plain(dict(facts)))
        issues, values = [], {"default": plain(payload["default"])}
        for check in payload["checks"]:
            try:
                program = environment.program(environment.compile(check["when"]))
                result = program.evaluate(activation)
            except Exception as exc:
                raise DecisionError("expression_failed") from exc
            if type(result) is not celpy.celtypes.BoolType:
                raise DecisionError("non_bool_check")
            if not bool(result):
                issues.append({"check": check["id"], "when": check["when"]})
        return RulesOutcome(values=values, disposition=None if issues else "passed",
                            issues=tuple(issues))

    def close(self) -> None:
        return None


def build():
    _celpy()  # refuse at construction when the dependency is unavailable
    return CelEngine()

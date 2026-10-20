"""Neutral `when` predication over facts; never CEL, never workflow control."""
from __future__ import annotations

from .definitions.values import DecisionError, plain

_OPS = {"eq", "ne", "lt", "lte", "gt", "gte", "in"}
_MAX_DEPTH = 16


def _compare(op: str, left, right) -> bool:
    try:
        if op == "eq":
            return left == right
        if op == "ne":
            return left != right
        if op == "in":
            if type(right) is not list:
                raise DecisionError("invalid_when")
            return left in right
        if type(left) is bool or type(right) is bool:
            raise DecisionError("invalid_when")
        if not isinstance(left, (int, float, str)) or not isinstance(right, (int, float, str)):
            raise DecisionError("invalid_when")
        if type(left) is str or type(right) is str:
            if type(left) is not type(right):
                raise DecisionError("invalid_when")
            return {"lt": left < right, "lte": left <= right,
                    "gt": left > right, "gte": left >= right}[op]
        return {"lt": left < right, "lte": left <= right,
                "gt": left > right, "gte": left >= right}[op]
    except TypeError as exc:
        raise DecisionError("invalid_when") from exc


def _resolve(path: str, facts) -> object:
    if type(path) is not str or not path or path.startswith(".") or ".." in path.split("."):
        raise DecisionError("invalid_fact_reference")
    value = facts
    for part in path.split("."):
        if type(value) is not dict or part not in value:
            raise DecisionError("unknown_fact")
        value = value[part]
    return value


def evaluate_when(when, facts, *, depth: int = 0) -> bool:
    """Evaluate one closed `when` node; missing facts are a refusal, not skip."""
    if depth > _MAX_DEPTH or type(when) is not dict:
        raise DecisionError("invalid_when")
    keys = set(when)
    if keys in ({"all"}, {"any"}, {"not"}):
        kind = next(iter(keys))
        body = when[kind]
        if kind == "not":
            return not evaluate_when(body, facts, depth=depth + 1)
        if type(body) is not list or not body:
            raise DecisionError("invalid_when")
        values = [evaluate_when(item, facts, depth=depth + 1) for item in body]
        return all(values) if kind == "all" else any(values)
    if keys != {"fact", "op", "value"}:
        raise DecisionError("invalid_when")
    op = when["op"]
    if type(op) is not str or op not in _OPS:
        raise DecisionError("invalid_when")
    left = _resolve(when["fact"], facts)
    right = plain(when["value"])
    return _compare(op, left, right)

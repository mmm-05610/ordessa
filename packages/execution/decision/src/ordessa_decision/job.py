"""Validate the closed `decision-job/1` document before any effect."""
from __future__ import annotations

from dataclasses import dataclass

from .definitions.models import DecisionQuestion, PolicyRef
from .definitions.values import DecisionError, name, plain
from .predicate import evaluate_when

_QUESTION_KEYS = {"kind", "text", "options", "scale", "evidence_ids",
                  "allowed_answer_ids", "bounded_state", "policy_ref", "version"}

SPEC_VERSION = "decision-job/1"
_JOB = {"spec_version", "job_id", "version", "input", "limits", "steps", "result"}
_LIMITS = {"max_model_calls", "max_steps", "max_value_bytes", "timeout_seconds"}
_STEP = {"id", "type", "when", "payload", "engine"}
_RESULT = {"from", "path"}
_HOST_LIMITS = {
    "max_model_calls": (int, 0, 128),
    "max_steps": (int, 1, 256),
    "max_value_bytes": (int, 256, 1 << 20),
    "timeout_seconds": (float, 0.1, 600.0),
}


@dataclass(frozen=True)
class Job:
    job_id: str
    version: int
    input: dict
    limits: dict
    steps: tuple[dict, ...]
    result: dict
    raw: dict


def _limit(name_: str, value, *, host: dict):
    kind, low, high = _HOST_LIMITS[name_]
    if type(value) is bool or type(value) not in (int, float) or type(value) is not kind:
        raise DecisionError("invalid_limit")
    if not low <= value <= high:
        raise DecisionError("invalid_limit")
    if value > host[name_]:
        raise DecisionError("limit_exceeds_host")
    return value


def default_host_limits() -> dict:
    return {"max_model_calls": 8, "max_steps": 32, "max_value_bytes": 65536,
            "timeout_seconds": 30.0}


def validate_job(payload, *, host_limits: dict | None = None) -> Job:
    host = dict(default_host_limits() if host_limits is None else host_limits)
    if type(payload) is not dict or set(payload) != _JOB:
        raise DecisionError("invalid_job")
    if payload["spec_version"] != SPEC_VERSION:
        raise DecisionError("invalid_job")
    job_id = name(payload["job_id"])
    version = payload["version"]
    if type(version) is not int or type(version) is bool or not 1 <= version <= 1 << 31:
        raise DecisionError("invalid_job")
    value = plain(payload["input"])
    if type(value) is not dict:
        raise DecisionError("invalid_job")
    limits_raw = payload["limits"]
    if type(limits_raw) is not dict or set(limits_raw) != _LIMITS:
        raise DecisionError("invalid_limit")
    limits = {}
    for key in _LIMITS:
        limits[key] = _limit(key, limits_raw[key], host=host)
    steps_raw = plain(payload["steps"])
    if type(steps_raw) is not list or not 1 <= len(steps_raw) <= limits["max_steps"]:
        raise DecisionError("invalid_job")
    steps, seen = [], set()
    for step in steps_raw:
        if type(step) is not dict or set(step) != _STEP:
            raise DecisionError("invalid_step")
        step_id = name(step["id"])
        if step_id in seen:
            raise DecisionError("duplicate_step")
        seen.add(step_id)
        if step["type"] not in ("rules", "ask"):
            raise DecisionError("invalid_step")
        if type(step["when"]) is not dict or type(step["payload"]) is not dict:
            raise DecisionError("invalid_step")
        if step["engine"] is not None:
            name(step["engine"])
        if step["type"] == "ask" and step["engine"] is not None:
            raise DecisionError("invalid_step")
        if step["type"] == "ask":
            _validate_question(step, version)
        evaluate_when_valid(step["when"])
        steps.append({"id": step_id, "type": step["type"], "when": step["when"],
                      "payload": step["payload"], "engine": step["engine"]})
    result_raw = plain(payload["result"])
    if type(result_raw) is not dict or not set(result_raw) <= _RESULT or "from" not in result_raw:
        raise DecisionError("invalid_result")
    if name(result_raw["from"]) not in seen:
        raise DecisionError("result_references_unknown_step")
    path = result_raw.get("path", [])
    if type(path) is not list or any(type(item) is not str or not item for item in path):
        raise DecisionError("invalid_result")
    return Job(job_id, version, value, limits, tuple(steps),
               {"from": result_raw["from"], "path": path}, plain(payload))


def _validate_question(step, job_version):
    """Ask questions are closed and validated before any effect (no model call)."""
    body = step["payload"].get("question")
    if type(body) is not dict or not set(body) <= _QUESTION_KEYS or "kind" not in body:
        raise DecisionError("invalid_question")
    policy = body.get("policy_ref")
    if policy is not None and type(policy) is not dict:
        raise DecisionError("invalid_question")
    question_version = body.get("version", str(job_version))
    try:
        DecisionQuestion(
            question_id=step["id"], version=question_version, kind=body["kind"],
            bounded_state=body.get("bounded_state") or {},
            question_text=body.get("text"), options=body.get("options") or {},
            scale=tuple(body.get("scale") or ()),
            evidence_ids=tuple(body.get("evidence_ids") or ()),
            allowed_answer_ids=tuple(body.get("allowed_answer_ids") or ()),
            policy_ref=None if policy is None else PolicyRef(**policy))
    except (DecisionError, TypeError, KeyError) as exc:
        raise DecisionError("invalid_question") from exc


def evaluate_when_valid(when: dict) -> None:
    """Structural check without facts: each `fact` is a dotted path, ops closed."""
    if set(when) in ({"all"}, {"any"}, {"not"}):
        kind = next(iter(when))
        body = when[kind]
        if kind == "not":
            if type(body) is not dict:
                raise DecisionError("invalid_when")
            evaluate_when_valid(body)
            return
        if type(body) is not list or not body:
            raise DecisionError("invalid_when")
        for item in body:
            if type(item) is not dict:
                raise DecisionError("invalid_when")
            evaluate_when_valid(item)
        return
    if set(when) != {"fact", "op", "value"} or when["op"] not in {
            "eq", "ne", "lt", "lte", "gt", "gte", "in"}:
        raise DecisionError("invalid_when")
    fact = when["fact"]
    if (type(fact) is not str or not fact or fact.startswith(".")
            or ".." in fact.split(".")):
        raise DecisionError("invalid_when")
    plain(when["value"])

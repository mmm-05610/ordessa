"""F1.1 decision DTOs: finite choice/score/noul with evidence mechanisms."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from .values import (DecisionError, canonical_bytes, digest_hex, name, plain)

KINDS = ("choice", "score", "noul")
MAX_QUESTION_BYTES = 512 * 1024
MAX_TEXT = 65536
MAX_OPTIONS = 66
MAX_SCALE = 10
MAX_EVIDENCE_IDS = 64


def _digest(projection) -> str:
    return "sha256:" + digest_hex(projection, maximum=MAX_QUESTION_BYTES)


@dataclass(frozen=True)
class PolicyRef:
    policy_id: str
    version: str
    content_digest: str

    def __post_init__(self):
        name(self.policy_id)
        name(self.version)
        name(self.content_digest)


@dataclass(frozen=True)
class DecisionQuestion:
    question_id: str
    version: str
    kind: str
    bounded_state: Mapping
    question_text: str
    options: Mapping = field(default_factory=dict)
    scale: tuple = ()
    evidence_ids: tuple = ()
    allowed_answer_ids: tuple = ()
    policy_ref: PolicyRef | None = None

    def __post_init__(self):
        name(self.question_id)
        name(self.version)
        if self.kind not in KINDS:
            raise DecisionError("invalid_kind")
        if type(self.question_text) is not str or not self.question_text or len(self.question_text) > MAX_TEXT:
            raise DecisionError("invalid_question")
        if not isinstance(self.bounded_state, Mapping):
            raise DecisionError("invalid_state")
        plain(self.bounded_state)
        options = plain(dict(self.options))
        if self.kind == "choice":
            if (not 2 <= len(options) <= MAX_OPTIONS
                    or any(type(k) is not str or not k or type(v) is not str or not v
                           for k, v in options.items())):
                raise DecisionError("invalid_options")
        elif options:
            raise DecisionError("irrelevant_field")
        scale = tuple(self.scale)
        if self.kind == "score":
            if (not 2 <= len(scale) <= MAX_SCALE or any(type(x) is not str or not x for x in scale)
                    or len(set(scale)) != len(scale)):
                raise DecisionError("invalid_scale")
        elif scale:
            raise DecisionError("irrelevant_field")
        evidence = tuple(self.evidence_ids)
        if len(evidence) > MAX_EVIDENCE_IDS or any(type(x) is not str or not x for x in evidence):
            raise DecisionError("invalid_evidence_ids")
        allowed = tuple(self.allowed_answer_ids)
        if self.kind == "choice":
            if allowed and set(allowed) != set(options):
                raise DecisionError("invalid_allowed_answers")
            if len(set(allowed)) != len(allowed):
                raise DecisionError("invalid_allowed_answers")
        elif allowed:
            raise DecisionError("irrelevant_field")
        if self.policy_ref is not None and type(self.policy_ref) is not PolicyRef:
            raise DecisionError("invalid_policy_ref")
        object.__setattr__(self, "options", options)
        object.__setattr__(self, "scale", scale)
        object.__setattr__(self, "evidence_ids", evidence)
        object.__setattr__(self, "allowed_answer_ids", allowed)
        object.__setattr__(self, "bounded_state", plain(self.bounded_state))
        if len(self.projection_bytes()) > MAX_QUESTION_BYTES:
            raise DecisionError("question_too_large")

    def projection_bytes(self) -> bytes:
        return canonical_bytes(self.projection(), maximum=MAX_QUESTION_BYTES)

    def projection(self):
        return {"schema_version": "decision-question/1", "question_id": self.question_id,
                "version": self.version, "kind": self.kind,
                "bounded_state": dict(self.bounded_state),
                "question_text": self.question_text, "options": dict(self.options),
                "scale": list(self.scale), "evidence_ids": list(self.evidence_ids),
                "allowed_answer_ids": list(self.allowed_answer_ids),
                "policy_ref": None if self.policy_ref is None else {
                    "policy_id": self.policy_ref.policy_id,
                    "version": self.policy_ref.version,
                    "content_digest": self.policy_ref.content_digest}}

    @property
    def question_digest(self) -> str:
        return _digest(self.projection())


@dataclass(frozen=True)
class DecisionAnswer:
    question_id: str
    kind: str
    value: object
    provider_receipt: Mapping
    usage_evidence: Mapping = field(default_factory=lambda: {"status": "unknown"})

    def __post_init__(self):
        name(self.question_id)
        if self.kind not in KINDS:
            raise DecisionError("invalid_kind")
        if not isinstance(self.provider_receipt, Mapping):
            raise DecisionError("invalid_receipt")
        plain(self.provider_receipt)
        usage = plain(dict(self.usage_evidence))
        if usage.get("status") not in ("unknown", "partial", "reported"):
            raise DecisionError("invalid_usage")
        if self.kind == "choice":
            if self.value is None:
                if (self.provider_receipt.get("selection_status") != "tie"
                        or len(self.provider_receipt.get("tied_option_ids") or ()) < 2):
                    raise DecisionError("invalid_answer")
            elif type(self.value) is not str or not self.value:
                raise DecisionError("invalid_answer")
        elif self.kind == "score":
            value = self.value
            if type(value) is bool or type(value) not in (int, float) or value < 0:
                raise DecisionError("invalid_answer")
        else:
            value = self.value
            if type(value) is bool or type(value) not in (int, float) or not 0 <= value <= 1:
                raise DecisionError("invalid_answer")
        object.__setattr__(self, "provider_receipt", plain(self.provider_receipt))
        object.__setattr__(self, "usage_evidence", usage)

    def projection(self):
        return {"schema_version": "decision-answer/1", "question_id": self.question_id,
                "kind": self.kind, "value": plain(self.value),
                "provider_receipt": dict(self.provider_receipt),
                "usage_evidence": dict(self.usage_evidence)}

    @property
    def answer_digest(self) -> str:
        return _digest(self.projection())


@dataclass(frozen=True)
class RulesOutcome:
    values: Mapping
    disposition: object | None = None
    issues: tuple = ()

    def __post_init__(self):
        if not isinstance(self.values, Mapping):
            raise DecisionError("invalid_rules_outcome")
        if self.disposition is not None and type(self.disposition) is not str:
            raise DecisionError("invalid_rules_outcome")
        if type(self.issues) is not tuple or any(
                not isinstance(item, Mapping) for item in self.issues):
            raise DecisionError("invalid_rules_outcome")
        plain(dict(self.values))
        object.__setattr__(self, "values", plain(dict(self.values)))
        object.__setattr__(self, "issues", tuple(plain(dict(i)) for i in self.issues))

"""Sequential decision runner: rules -> ask -> rules, facts only, no retries."""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field

from .definitions.values import DecisionError, canonical_bytes, digest_hex, name, job_document_bound
from .job import Job, validate_job
from .definitions.models import DecisionAnswer, DecisionQuestion, PolicyRef, RulesOutcome
from .ports import CallPermit, ModelCallContext
from .definitions.models import RulesOutcome
from .ports import CallPermit, ModelCallContext
from .predicate import evaluate_when

MAX_EVIDENCE_BYTES = 64 * 1024


@dataclass
class RunResult:
    status: str                       # completed|refused|unknown
    data: dict | None = None
    error: dict | None = None
    evidence: dict = field(default_factory=dict)


_QUESTION_KEYS = {"kind", "text", "options", "scale", "evidence_ids",
                  "allowed_answer_ids", "bounded_state", "policy_ref", "version"}


def _check_size(value, limit):
    if len(canonical_bytes(value)) > limit:
        raise DecisionError("value_too_large")


def _unknown(code, evidence):
    return RunResult("unknown", error={"code": "effect_unknown", "detail": code,
                                       "retryable": False}, evidence=evidence)


def _question(step, job):
    body = step["payload"].get("question")
    if type(body) is not dict or not set(body) <= _QUESTION_KEYS or "kind" not in body:
        raise DecisionError("invalid_question")
    policy = body.get("policy_ref")
    return DecisionQuestion(
        question_id=step["id"], version=body.get("version") or str(job.version),
        kind=body["kind"], bounded_state=body.get("bounded_state") or {},
        question_text=body.get("text"), options=body.get("options") or {},
        scale=tuple(body.get("scale") or ()),
        evidence_ids=tuple(body.get("evidence_ids") or ()),
        allowed_answer_ids=tuple(body.get("allowed_answer_ids") or ()),
        policy_ref=None if policy is None else PolicyRef(**policy))


def _probabilities(receipt, expected_keys):
    probabilities = receipt.get("probabilities")
    if not isinstance(probabilities, dict) or set(probabilities) != set(expected_keys):
        return False
    total = 0.0
    for value in probabilities.values():
        if type(value) not in (int, float) or type(value) is bool or not 0 <= value <= 1:
            return False
        total += float(value)
    return abs(total - 1.0) <= 1e-6


_RECEIPT_STRINGS = ("resolved_model", "requested_model", "protocol_validation_version",
                    "question_digest", "provider_settings_digest")


def _validate_receipt(receipt, question, settings_digest):
    """F1.1 §11.1: the receipt binds the question and provider identity."""
    for key in _RECEIPT_STRINGS:
        value = receipt.get(key)
        if type(value) is not str or not value:
            raise DecisionError("invalid_answer")
    if receipt["question_digest"] != question.question_digest:
        raise DecisionError("invalid_answer")
    if receipt["provider_settings_digest"] != settings_digest:
        raise DecisionError("invalid_answer")


def _validate_answer(answer, question, settings_digest=None):
    if type(answer) is not DecisionAnswer or answer.question_id != question.question_id \
            or answer.kind != question.kind:
        raise DecisionError("invalid_answer")
    receipt = answer.provider_receipt
    if settings_digest is not None:
        _validate_receipt(receipt, question, settings_digest)
    if question.kind == "choice":
        if answer.value is None:
            tied = receipt.get("tied_option_ids") or ()
            if (receipt.get("selection_status") != "tie"
                    or len(tied) < 2 or len(set(tied)) != len(tied)
                    or not set(tied) <= set(question.options)):
                raise DecisionError("invalid_answer")
        else:
            if answer.value not in question.options:
                raise DecisionError("invalid_answer")
            if receipt.get("selection_status") == "tie":
                raise DecisionError("invalid_answer")
        expected = set(question.options)
    elif question.kind == "score":
        value = answer.value
        if type(value) is bool or type(value) not in (int, float) \
                or not 0 <= value <= len(question.scale) - 1:
            raise DecisionError("invalid_answer")
        legend = receipt.get("legend")
        if (not isinstance(legend, dict) or set(legend) != {str(i) for i in range(len(question.scale))}
                or any(legend[str(i)] != label for i, label in enumerate(question.scale))):
            raise DecisionError("invalid_answer")
        expected = {str(i) for i in range(len(question.scale))}
    else:
        value = answer.value
        if type(value) is bool or type(value) not in (int, float) or not 0 <= value <= 1:
            raise DecisionError("invalid_answer")
        return
    if not _probabilities(receipt, expected):
        raise DecisionError("invalid_answer")
    if question.kind == "choice" and answer.value is not None:
        keys = list(receipt["probabilities"])
        if receipt["probabilities"][answer.value] != max(receipt["probabilities"].values()):
            raise DecisionError("invalid_answer")
        if len({v for v in receipt["probabilities"].values()}) == 1 and answer.value is not None:
            # A uniform distribution is a tie, not a unique winner.
            raise DecisionError("invalid_answer")


def _refuse(code):
    return RunResult("refused", error={"code": code, "retryable": False})


def _resolve_result_path(value, path):
    for part in path:
        if type(value) is not dict or part not in value:
            raise DecisionError("result_path_missing")
        value = value[part]
    return value


class DecisionRunner:
    """Run one validated job over injected ports; the runner owns no service."""

    def __init__(self, *, default_engine=None, engines=None, provider=None,
                 host_limits=None, now=time.monotonic, engine_loader=None, job_document_max_bytes=None):
        self.job_document_max_bytes = job_document_bound(job_document_max_bytes)
        self.default_engine = default_engine
        self.engines = dict(engines or {})
        self.provider = provider
        self.host_limits = dict(host_limits or {})
        self.now = now
        self.engine_loader = engine_loader

    def _engine(self, step, owned):
        """Job-explicit engine wins; host default last; loaded engines are owned."""
        if step["engine"] is not None:
            engine = self.engines.get(step["engine"])
            if engine is not None:
                return engine
            if self.engine_loader is None:
                raise DecisionError("engine_unavailable")
            engine = self.engine_loader(step["engine"])
            owned.append(engine)
            return engine
        if self.default_engine is None:
            raise DecisionError("engine_required")
        return self.default_engine

    def run(self, payload) -> RunResult:
        """Synchronous entry for rules-only use; never re-enters a running loop."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.run_async(payload))
        raise DecisionError("running_loop")

    async def run_async(self, payload) -> RunResult:
        try:
            job = validate_job(payload, host_limits=self.host_limits or None)
            canonical_bytes({'job': job.raw, 'dryRun': False}, maximum=self.job_document_max_bytes)
        except DecisionError as exc:
            return _refuse(exc.code)
        return await self._run(job)

    async def _run(self, job: Job) -> RunResult:
        owned = []
        try:
            return await self._run_owned(job, owned)
        finally:
            for engine in owned:
                try:
                    engine.close()
                except Exception:
                    pass

    async def _run_owned(self, job: Job, owned):
        facts = {"input": job.input}
        step_digests, skipped, answers = {}, set(), {}
        model_calls, usage = 0, {}
        deadline = self.now() + job.limits["timeout_seconds"]
        for step in job.steps:
            step_id = step["id"]
            if self.now() > deadline:
                return _refuse("deadline_exceeded")
            try:
                if not evaluate_when(step["when"], facts):
                    skipped.add(step_id)
                    continue
                if step["type"] == "rules":
                    engine = self._engine(step, owned)
                    try:
                        engine.validate(step["payload"])
                    except DecisionError:
                        raise
                    outcome = engine.evaluate(step["payload"], facts)
                    if type(outcome) is not RulesOutcome:
                        raise DecisionError("invalid_rules_outcome")
                    facts[step_id] = {"values": outcome.values,
                                      "disposition": outcome.disposition}
                    _check_size(facts[step_id], job.limits["max_value_bytes"])
                    step_digests[step_id] = digest_hex({
                        "type": "rules", "engine": engine.engine_id,
                        "values": outcome.values, "disposition": outcome.disposition,
                        "issues": list(outcome.issues)})
                else:
                    if self.provider is None:
                        raise DecisionError("provider_unavailable")
                    if model_calls >= job.limits["max_model_calls"]:
                        raise DecisionError("model_call_limit")
                    question = _question(step, job)
                    settings_digest = self.provider.settings_digest
                    permit = CallPermit(job.job_id, question.question_digest,
                                        settings_digest, deadline)
                    context = ModelCallContext(job.job_id, step_id, model_calls + 1,
                                               question.question_digest, settings_digest,
                                               deadline, permit)
                    model_calls += 1
                    try:
                        answer = await self.provider.decide(question, context)
                        # Post-return contract validation, NOT a send gate: the
                        # physical single-use gate is the provider's permit claim
                        # immediately before dispatch (DESIGN §11.2). A provider
                        # returning an answer without consuming its permit has
                        # violated that contract, so nothing is persisted and the
                        # run is unknown (the frame may already have been sent).
                        if getattr(context.permit, "_claimed", None) is not True:
                            return _unknown("provider_permit_not_claimed",
                                            {"job_digest": digest_hex(job.raw, maximum=self.job_document_max_bytes),
                                             "steps": step_digests,
                                             "call_evidence": {"step": step_id,
                                                               "error": "permit_not_claimed"}})
                        _validate_answer(answer, question, settings_digest)
                    except Exception as exc:
                        # The provider call was attempted; the frame may already
                        # have been dispatched (permit consumed or not): never
                        # label this refused.
                        evidence = {"job_digest": digest_hex(job.raw, maximum=self.job_document_max_bytes),
                                    "steps": step_digests,
                                    "call_evidence": {"step": step_id,
                                                      "error": getattr(exc, "code",
                                                                       type(exc).__name__)}}
                        return _unknown("model_call_unknown", evidence)
                    receipt = answer.provider_receipt
                    facts[step_id] = {"answer": answer.value,
                                      "confidence": receipt.get("confidence"),
                                      "receipt": dict(receipt),
                                      "usage": dict(answer.usage_evidence)}
                    _check_size(facts[step_id], job.limits["max_value_bytes"])
                    answers[step_id] = answer
                    usage[step_id] = dict(answer.usage_evidence)
                    step_digests[step_id] = digest_hex({
                        "type": "ask", "question": question.question_digest,
                        "answer": answer.answer_digest})
            except DecisionError as exc:
                if model_calls:
                    return _unknown(exc.code, {"job_digest": digest_hex(job.raw, maximum=self.job_document_max_bytes),
                                               "steps": step_digests,
                                               "model_calls": model_calls})
                return _refuse(exc.code)
        target = job.result["from"]
        if target in skipped:
            return _refuse("result_invalid")
        try:
            result = _resolve_result_path(facts[target], job.result["path"])
        except (KeyError, DecisionError):
            return _refuse("result_invalid")
        evidence = {
            "job_digest": digest_hex(job.raw, maximum=self.job_document_max_bytes),
            "input_digest": digest_hex(job.input, maximum=self.job_document_max_bytes),
            "steps": step_digests, "answers": {key: a.answer_digest
                                              for key, a in answers.items()},
            "receipt": {key: dict(a.provider_receipt) for key, a in answers.items()},
            "usage": usage, "result_digest": digest_hex(result),
            "skipped": sorted(skipped),
        }
        return RunResult("completed", data={"result": result}, evidence=evidence)

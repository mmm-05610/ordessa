import asyncio
import math
import re
import time
import uuid
from decision_runtime.definitions import (CallPermit, ModelCallContext, DecisionAnswer,
    DecisionQuestion, DurabilityAck)
from decision_runtime.definitions.errors import BudgetExhausted, EvidenceUnknown, RuntimeFailure
from .limits import deadline_at
from decision_runtime.evidence.codec import record

def require_ack(ack, mode, *, expected_seq=None, expected_digest=None):
    if (not isinstance(ack, DurabilityAck) or type(ack.seq) is not int or ack.seq < 1
            or type(ack.digest) is not str or not re.fullmatch(r'sha256:[0-9a-f]{64}', ack.digest)
            or (expected_seq is not None and ack.seq != expected_seq)
            or (expected_digest is not None and ack.digest != expected_digest)):
        raise EvidenceUnknown()
    if ack.durability not in ('memory','durable') or (mode == 'real' and ack.durability != 'durable'):
        raise EvidenceUnknown()

async def append_checked(context, evidence, mode, event):
    """Caller holds the run lock, so the ACK binds one exact journal entry."""
    expected = record(event, context.evidence_seq + 1, context.evidence_digest, 65536)
    ack = await evidence.append_durable(event)
    require_ack(ack, mode, expected_seq=expected['seq'], expected_digest=expected['digest'])
    context.evidence_seq, context.evidence_digest = ack.seq, ack.digest

def safe_usage(usage):
    """Receipts are provider data: persist only numeric usage and closed status."""
    result = {'status': 'unknown'}
    if usage.get('status') in ('known', 'unknown', 'reported'):
        result['status'] = usage['status']
    for key in ('input_tokens','output_tokens','total_tokens','cost'):
        value = usage.get(key)
        if type(value) in (int, float) and math.isfinite(value) and value >= 0:
            result[key] = value
    return result

class ModelGateway:
    def __init__(self, context, provider, evidence, mode):
        self._context, self._provider, self._evidence, self._mode = context, provider, evidence, mode
        self._slots = asyncio.Semaphore(context.limits.max_inflight_model_calls)

    def _fail(self, code):
        self._context.failure_code = self._context.failure_code or code
        raise RuntimeFailure(self._context.failure_code) from None

    async def decide(self, question):
        ctx = self._context
        if not isinstance(question, DecisionQuestion) or question.policy_ref not in ctx.services.policy_refs:
            self._fail('question_policy_invalid')
        if question.kind == 'choice' and len(question.options) > ctx.limits.max_choice_options:
            self._fail('question_size')
        async with deadline_at(ctx.deadline):
            async with self._slots:
                async with ctx.lock:
                    ctx.check()
                    if ctx.model_attempts >= ctx.limits.max_model_attempts:
                        ctx.exhaust('max_model_attempts')
                    ctx.model_attempts += 1
                    call_id = 'call-' + uuid.uuid4().hex
                    settings_digest = self._provider.settings_digest
                    try:
                        await append_checked(ctx, self._evidence, self._mode, {
                            'type': 'call.intent', 'run_id': ctx.run_id, 'call_id': call_id,
                            'attempt': ctx.model_attempts, 'question_digest': question.question_digest})
                    except asyncio.CancelledError:
                        raise
                    except Exception:
                        ctx.mark_evidence_unknown()
                    ctx.check()
                    permit = CallPermit(ctx.run_id, question.question_digest, settings_digest, ctx.deadline)
                    model_context = ModelCallContext(ctx.run_id, call_id, ctx.model_attempts,
                        question.question_digest, settings_digest, ctx.deadline, permit)
                try:
                    answer = await self._provider.decide(question, model_context)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    self._fail('provider_failed')
                if not isinstance(answer, DecisionAnswer) or answer.question_id != question.question_id or answer.kind != question.kind:
                    self._fail('answer_mismatch')
                if answer.kind == 'choice':
                    if answer.value is None:
                        tied = answer.provider_receipt.get('tied_option_ids', ())
                        if answer.provider_receipt.get('selection_status') != 'tie' or len(tied) < 2 or any(v not in question.options for v in tied):
                            self._fail('answer_choice_invalid')
                    elif not isinstance(answer.value, str) or answer.value not in question.options:
                        self._fail('answer_choice_invalid')
                if answer.kind == 'score' and (type(answer.value) not in (float,int) or not math.isfinite(answer.value) or not 0 <= answer.value <= len(question.scale)-1):
                    self._fail('answer_score_invalid')
                if answer.kind == 'noul' and (type(answer.value) not in (float,int) or not math.isfinite(answer.value) or not 0 <= answer.value <= 1):
                    self._fail('answer_noul_invalid')
                try:
                    async with ctx.lock:
                        await append_checked(ctx, self._evidence, self._mode, {'type': 'call.response',
                            'run_id': ctx.run_id, 'call_id': call_id, 'attempt': model_context.attempt_no,
                            'answer_digest': answer.answer_digest, 'usage': safe_usage(answer.usage_evidence)})
                except asyncio.CancelledError:
                    raise
                except Exception:
                    ctx.mark_evidence_unknown()
                ctx.check()
                return answer

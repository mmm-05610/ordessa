import asyncio
import math
import time
import uuid
from ordessa_decision.contracts import (CallPermit, ModelCallContext, DecisionAnswer,
    DecisionQuestion, DurabilityAck)
from .errors import BudgetExhausted, EvidenceUnknown, RuntimeFailure
from .timeouts import deadline_at

def require_ack(ack, mode):
    if not isinstance(ack, DurabilityAck) or ack.seq < 1 or not ack.digest:
        raise EvidenceUnknown()
    if mode == 'real' and ack.durability != 'durable':
        raise EvidenceUnknown()

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

    async def decide(self, question):
        ctx = self._context
        if not isinstance(question, DecisionQuestion) or question.policy_ref not in ctx.services.policy_refs:
            raise RuntimeFailure('question_policy_invalid')
        if question.kind == 'choice' and len(question.options) > ctx.limits.max_choice_options:
            raise RuntimeFailure('question_size')
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
                        ack = await self._evidence.append_durable({
                            'type': 'call.intent', 'run_id': ctx.run_id, 'call_id': call_id,
                            'attempt': ctx.model_attempts, 'question_digest': question.question_digest})
                        require_ack(ack, self._mode)
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
                    raise RuntimeFailure('provider_failed') from None
                if not isinstance(answer, DecisionAnswer) or answer.question_id != question.question_id or answer.kind != question.kind:
                    raise RuntimeFailure('answer_mismatch')
                if answer.kind == 'choice':
                    if answer.value is None:
                        tied = answer.provider_receipt.get('tied_option_ids', ())
                        if answer.provider_receipt.get('selection_status') != 'tie' or len(tied) < 2 or any(v not in question.options for v in tied):
                            raise RuntimeFailure('answer_choice_invalid')
                    elif not isinstance(answer.value, str) or answer.value not in question.options:
                        raise RuntimeFailure('answer_choice_invalid')
                if answer.kind == 'score' and (type(answer.value) not in (float,int) or not math.isfinite(answer.value) or not 0 <= answer.value <= len(question.scale)-1):
                    raise RuntimeFailure('answer_score_invalid')
                if answer.kind == 'noul' and (type(answer.value) not in (float,int) or not math.isfinite(answer.value) or not 0 <= answer.value <= 1):
                    raise RuntimeFailure('answer_noul_invalid')
                try:
                    ack = await self._evidence.append_durable({'type': 'call.response',
                        'run_id': ctx.run_id, 'call_id': call_id, 'attempt': model_context.attempt_no,
                        'answer_digest': answer.answer_digest, 'usage': safe_usage(answer.usage_evidence)})
                    require_ack(ack, self._mode)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    ctx.mark_evidence_unknown()
                return answer

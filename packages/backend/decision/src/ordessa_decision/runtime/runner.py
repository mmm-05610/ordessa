"""Lifecycle orchestration around the upstream public async graph executor."""
import asyncio
import time
import uuid
from collections.abc import Mapping
from ordessa_decision.contracts import (BusinessOutcome, DecisionRequest, DecisionResult,
    RunManifest, ContractError, canonical, digest)
from .calls import ModelGateway, require_ack
from .context import RunContext
from .errors import BudgetExhausted, EvidenceUnknown, ExplicitCancellation, RuntimeFailure
from .flow import TrustedFlow
from .timeouts import deadline_at

async def bounded(operation, timeout):
    """Never await cancellation-resistant cleanup beyond the configured bound."""
    task = asyncio.create_task(operation)
    try:
        done, _ = await asyncio.wait({task}, timeout=timeout)
        if not done:
            task.cancel()
            task.add_done_callback(_consume)
            raise EvidenceUnknown()
        return task.result()
    except asyncio.CancelledError:
        task.cancel()
        task.add_done_callback(_consume)
        raise

def _consume(task):
    if not task.cancelled():
        task.exception()

async def run_decision(request, *, flow, services):
    if not isinstance(request, DecisionRequest) or not isinstance(flow, TrustedFlow):
        raise ContractError('run_input')
    flow.validate()
    if request.flow_ref != flow.ref or tuple(services.policy_refs) != tuple(flow.policy_refs):
        raise ContractError('flow_policy_mismatch')
    if services.mode == 'real' and services.evidence.durable is not True:
        raise ContractError('durable_evidence_required')
    run_id = str(uuid.uuid4())
    manifest = RunManifest(request.request_digest, flow.ref, services.policy_refs,
                           request.limits, services.decision_provider.binding_ref)
    context = RunContext(request, services, run_id, time.monotonic() + request.limits.wall_timeout_seconds)
    context.gateway = ModelGateway(context, services.decision_provider, services.evidence, services.mode)
    finish_started = False
    terminal = None
    started = False

    def result(status, *, outcome=None, code=None, dimension=None):
        return DecisionResult(run_id, request.request_id, request.task.task_revision,
            flow.ref, manifest.manifest_digest, services.policy_refs, status,
            outcome=outcome, error_code=code, failure_stage=None if status == 'completed' else 'runtime',
            exhausted_dimension=dimension, consumed=context.consumed())

    async def query_committed(expected):
        try:
            read = await bounded(services.evidence.read(run_id, services.read_context), request.limits.cleanup_timeout_seconds)
            if not isinstance(read, Mapping) or read.get('status') != 'completed':
                return False
            value = read.get('terminal')
            if not isinstance(value, Mapping) or value.get('run_id') != run_id or value.get('status') != expected['status']:
                return False
            observed_result = value.get('result')
            if not isinstance(observed_result, Mapping) or canonical(observed_result) != canonical(expected['result']):
                return False
            observed_digest = digest('result', observed_result)
            terminal_digest = value.get('terminal_digest',value.get('result_digest'))
            if terminal_digest != expected['terminal_digest'] or observed_digest != terminal_digest:
                return False
            if 'result_digest' in value and value['result_digest'] != terminal_digest:
                return False
            return True
        except Exception:
            pass
        return False

    async def commit(value):
        nonlocal finish_started, terminal
        terminal = {'run_id': run_id, 'status': value.status, 'result': value.to_dict(),
                    'terminal_digest': value.result_digest}
        finish_started = True
        try:
            ack = await bounded(services.evidence.finish(terminal), request.limits.cleanup_timeout_seconds)
            require_ack(ack, services.mode)
        except asyncio.CancelledError:
            raise
        except Exception:
            if not await query_committed(terminal):
                raise EvidenceUnknown(run_id) from None
        return value

    try:
        try:
            ack = await bounded(services.evidence.start({'type':'run.started', 'run_id':run_id,
                'request_digest':request.request_digest, 'flow_digest':flow.ref.content_digest,
                'manifest_digest':manifest.manifest_digest}), min(request.limits.wall_timeout_seconds, request.limits.cleanup_timeout_seconds))
            require_ack(ack, services.mode)
            started = True
        except asyncio.CancelledError:
            raise
        except Exception:
            raise EvidenceUnknown(run_id) from None
        try:
            async with deadline_at(context.deadline):
                state = flow.new_state(request)
                outcome = await flow.graph.run(state=state, deps=context, inputs=request, infer_name=False)
                context.check()
                if not isinstance(outcome, flow.output_schema):
                    raise RuntimeFailure('output_invalid')
                value = result('completed', outcome=outcome)
        except EvidenceUnknown:
            raise
        except BudgetExhausted as exc:
            value = result('budget_exhausted', dimension=exc.dimension)
        except TimeoutError:
            value = result('budget_exhausted', dimension='wall_timeout_seconds')
        except ExplicitCancellation:
            value = result('cancelled')
        except Exception as exc:
            value = result('failed', code=exc.code if isinstance(exc, RuntimeFailure) else 'graph_failed')
        return await commit(value)
    except EvidenceUnknown:
        # Calls and bounded helpers do not know the run's public query key.
        context.evidence_unknown = True
        raise EvidenceUnknown(run_id) from None
    except asyncio.CancelledError as cancellation:
        context.cancel()
        cancellation.run_id = run_id
        if hasattr(cancellation, 'add_note'):
            cancellation.add_note('decision run_id=' + run_id)
        async def cleanup():
            if finish_started:
                # An attempted terminal may already be durable. Never oppose it.
                await query_committed(terminal)
            elif started:
                await commit(result('cancelled'))
        cleanup_task = asyncio.create_task(cleanup())
        try:
            await asyncio.shield(bounded(_await_task(cleanup_task), request.limits.cleanup_timeout_seconds))
        except (Exception, asyncio.CancelledError):
            cleanup_task.cancel()
            cleanup_task.add_done_callback(_consume)
            if hasattr(cancellation, 'add_note'):
                cancellation.add_note('decision cleanup unconfirmed; query evidence')
        raise

async def _await_task(task):
    return await task

async def read_result(run_id, *, services):
    return await services.evidence.read(run_id, services.read_context)

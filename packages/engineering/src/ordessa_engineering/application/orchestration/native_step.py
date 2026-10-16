"""Original native dispatch result joins the sole method run's step log."""
from dataclasses import asdict

from ordessa_infrastructure.encoding import canonical_bytes,decode_json
from ..contracts.commands import ReadSet
from ..contracts.errors import ApplicationError
from ..contracts.run_waits import run_wait_row_digest
from ...domain.changes.dispatch_codec import decode_dispatch
from ...domain.common.mechanisms.codec import decode_blob_ref,decode_digest
from ...methods.compilation.encoding import program_plan_digest
from ...methods.definitions.models.compiled import OperationNode
from .method_bridge import MethodBridge
from .method_runs import _advance_step,_check_rounds,_route_result
from .dispatch_method_run import resolve_method_run_package
from ..contracts.operation_registry import registry_ref


def record_dispatch_step(owner,parameters,context,*,read_set=None):
    operation='engineering.work.record_dispatch_step'
    value,reads,digest=owner._input(operation,parameters,context,read_set)
    replay=owner._replay(operation,context,digest)
    if replay is not None:
        return replay
    try:
        expected=decode_digest(value['expected_row_digest'])
    except Exception as exc:
        raise ApplicationError('INVALID_INPUT') from exc
    bindings=owner.bindings
    if bindings is None or bindings.source is None or bindings.registry_loader is None:
        raise ApplicationError('WORK_WAIT_AUTHORITY_UNAVAILABLE')
    with owner.factory.begin(context.scope,'read') as uow:
        row=uow.workflow.run_row(value['run_id'])
    method=bindings._inputs(context,row)
    with bindings.methods.guard_method(context,method) as snapshot:
        program=bindings._bound_program(snapshot,method,row)
        _check_rounds(program,row['inputs'])
        selected_registry=registry_ref(bindings.registry_loader())
        if row['registry_ref']!=selected_registry:
            raise ApplicationError('METHOD_CAPABILITY_CHANGED')
        cursor=row['cursor']
        if (row['status']!='RUNNING' or type(cursor) is not int
                or not 0<=cursor<len(program.workflow.steps)):
            raise ApplicationError('WORK_OPERATION_UNAVAILABLE')
        node=program.workflow.steps[cursor]
        if type(node) is not OperationNode or node.operation!='engineering.executions.dispatch':
            raise ApplicationError('WORK_OPERATION_UNAVAILABLE')
        params=MethodBridge().operation_inputs(program,node.id,row['inputs']['slots'])['dispatch']
        if (params['run_id']!=value['run_id'] or params['step_id']!=node.id
                or params['attempt']!=value['attempt']):
            raise ApplicationError('WORK_DISPATCH_RESULT_MISMATCH')
        source_guard=getattr(bindings.source,'guard_step_completion',None)
        if not callable(source_guard):
            raise ApplicationError('WORK_COMPLETION_SOURCE_UNAVAILABLE')
        with source_guard(context,snapshot,node,{'run_id':value['run_id'],'row':row}) as observed:
            if type(observed) is not ReadSet or observed.scope!=context.scope:
                raise ApplicationError('WORK_COMPLETION_SOURCE_INVALID')
            def mutate(uow):
                uow.engineering.check_read_set(observed)
                if selected_registry!=registry_ref(bindings.registry_loader()):
                    raise ApplicationError('METHOD_CAPABILITY_CHANGED')
                current=uow.workflow.run_row(value['run_id'])
                if (current!=row or run_wait_row_digest(current)!=expected
                        or uow.workflow.next_step_ordinal(value['run_id'])!=value['expected_next_step_ordinal']):
                    raise ApplicationError('RUN_WAIT_CHANGED')
                package=resolve_method_run_package(uow,value['run_id'],bindings,
                    step_id=node.id,live=True,attempt=value['attempt'])
                dispatch=uow.dispatch.get(value['run_id'],node.id,value['attempt'],context.scope)
                binding=decode_dispatch(dispatch['binding_bytes'])
                if (binding.scope!=context.scope or binding.run_id!=value['run_id']
                        or binding.step_id!=node.id or binding.attempt!=value['attempt']
                        or binding.package_ref!=package.ref or dispatch['dispatch_fence']!=binding.fence
                        or binding.unit_ref_bytes!=canonical_bytes(params['unit_ref'])
                        or tuple(action for action,_ in binding.action_instances)!=tuple(params['actions'])):
                    raise ApplicationError('WORK_DISPATCH_RESULT_MISMATCH')
                # Verify original frozen ACP payload. Only the original fixed
                # session insertion is allowed; native payload is not translated.
                prompt=decode_json(uow.implementation.read_blob(binding.prompt_ref))
                expected_prompt=dict(params['params'])
                expected_prompt.setdefault('sessionId',prompt.get('sessionId'))
                if canonical_bytes(expected_prompt)!=canonical_bytes(prompt):
                    raise ApplicationError('WORK_DISPATCH_RESULT_MISMATCH')
                state=dispatch['dispatch_phase']
                if state not in ('completed','failed'):
                    raise ApplicationError('WORK_OPERATION_OUTCOME_UNKNOWN')
                if dispatch['result_blob_json'] is None:
                    raise ApplicationError('WORK_DISPATCH_RESULT_MISMATCH')
                observed_ref=decode_blob_ref(decode_json(dispatch['result_blob_json']))
                uow.implementation.read_blob(observed_ref)
                result=canonical_bytes({'phase':state,'execution_operation_ref':binding.execution_operation_ref,
                    'binding_digest':asdict(binding.digest),'result_blob_ref':asdict(observed_ref),
                    'engineering_completed':False,'accepted':False})
                selected_outcome=_route_result(result,node.result_routing) if node.result_routing is not None else state
                outcomes=node.result_routing.outcomes if node.result_routing is not None else node.outcomes
                transitions=[edge.target for edge in outcomes.entries if edge.outcome==selected_outcome]
                if len(transitions)!=1 or transitions[0].wait is not None:
                    raise ApplicationError('WORK_TRANSITION_UNAVAILABLE')
                return _advance_step(uow,current,program,node,run_id=value['run_id'],
                    next_ordinal=value['expected_next_step_ordinal'],state=state,
                    selected_outcome=selected_outcome,transitions=transitions,receipt_facts={
                        'schema_version':'engineering-method-step-receipt/1','scope':asdict(context.scope),
                        'run_id':value['run_id'],'method_ref':asdict(method),
                        'compiled_plan_digest':program_plan_digest(program),
                        'original_dispatch_binding_digest':asdict(binding.digest),
                        'original_operation_id':binding.execution_operation_ref,'state':state,
                        'result':result.decode('utf-8')})
            return owner._run(operation,context,reads,digest,mutate)

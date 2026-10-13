"""Coordinate one fixed method version's run over original Engineering state.

MethodRun is a read view over the original run/material/journal authority.
Operations and external effects remain explicit calls to original owners, with
their own admission/write cuts.
"""
from contextlib import contextmanager
import hashlib
from dataclasses import asdict, fields
from ..contracts.errors import ApplicationError
from ..contracts.method_work import WORK_CONTRACT, WAIT_EVENT, WorkSeed, WorkWaitSelection, BoundWorkWait
from ..contracts.run_waits import run_wait_row_digest
from ..contracts.operation_registry import registry_ref
from ..usecases.approvals.service import ApprovalUseCases
from ..usecases.support.clock import utc_now
from ...domain.artifacts.method_codec import decode_method_ref
from ...domain.common.mechanisms.codec import canonical_value, require_object
from ...domain.common.models.values import validate_id
from ...domain.common.outcomes.diagnostics import ReferenceError
from ...methods.compilation.encoding import program_plan_digest
from ...methods.definitions.models.compiled import CompiledProgram, WaitNode, StopNode
from ordessa_infrastructure.encoding import canonical_bytes


def _copy(value):
    return canonical_value(canonical_bytes(value))


def _route_result(result_bytes, routing):
    import json
    if type(result_bytes) is not bytes or type(routing.path) is not str:
        raise ApplicationError('WORK_RESULT_UNMAPPED')
    try:
        value=json.loads(result_bytes.decode('utf-8'))
        if routing.path == '':
            selected=value
        else:
            if not routing.path.startswith('/'):
                raise ValueError
            selected=value
            for part in routing.path[1:].split('/'):
                part=part.replace('~1','/').replace('~0','~')
                if type(selected) is dict:
                    selected=selected[part]
                elif type(selected) is list and (part=='0' or (part.isdigit() and not part.startswith('0'))):
                    selected=selected[int(part)]
                else:
                    raise KeyError(part)
        if type(selected) is not str:
            raise ValueError
        if not any(binding.outcome == selected for binding in routing.outcomes.entries):
            raise ValueError
        return selected
    except (UnicodeDecodeError, json.JSONDecodeError, KeyError, IndexError, TypeError, ValueError):
        raise ApplicationError('WORK_RESULT_UNMAPPED') from None


def _check_rounds(program, inputs):
    loops=program.workflow.loops or ()
    rounds=inputs.get('rounds')
    if not loops:
        if rounds is not None:
            raise ApplicationError('WORK_LOOP_STATE_INVALID')
        return
    if type(rounds) is not dict or set(rounds)!={loop.loop_id for loop in loops}:
        raise ApplicationError('WORK_LOOP_STATE_INVALID')
    if any(type(rounds[loop.loop_id]) is not int or not 1 <= rounds[loop.loop_id] <= loop.max_rounds
           for loop in loops):
        raise ApplicationError('WORK_LOOP_STATE_INVALID')

def _advance_step(uow, current, program, node, *, run_id, next_ordinal, state, selected_outcome, transitions, receipt_facts):
    """One original step receipt/round/cursor write cut for any admitted owner result."""
    cursor=current['cursor']
    stopped=transitions[0].stop
    if stopped is not None:
        if stopped not in program.workflow.stop_outcomes:
            raise ApplicationError('WORK_TRANSITION_UNAVAILABLE')
        destinations=[cursor]; target=None; status='SLICE_DONE'
    else:
        destinations=[i for i,n in enumerate(program.workflow.steps) if n.id==transitions[0].next]
        if len(destinations)!=1:
            raise ApplicationError('WORK_CURSOR_INVALID')
        target=program.workflow.steps[destinations[0]]
        status='WAITING_FOR_CONDITION' if type(target) is WaitNode else 'SLICE_DONE' if type(target) is StopNode else 'RUNNING'
    ordinal=next_ordinal; now=utc_now()
    attempt=1+sum(1 for prior in uow.workflow.step_rows(run_id)
                  if prior['step_id']==node.id and prior['receipt_ref'] is not None)
    next_inputs=current['inputs']
    loops=([loop for loop in program.workflow.loops or ()
            if loop.from_step==node.id and target.id==loop.to_step]
           if stopped is None else [])
    if loops:
        if len(loops)>1:
            raise ApplicationError('WORK_LOOP_AMBIGUOUS')
        rounds=dict(next_inputs.get('rounds',{}))
        for loop in loops:
            current_round=rounds.get(loop.loop_id,1)
            if current_round < loop.max_rounds:
                rounds[loop.loop_id]=current_round+1
                destinations=[i for i,n in enumerate(program.workflow.steps) if n.id==loop.to_step]
                if len(destinations)!=1: raise ApplicationError('WORK_LOOP_TARGET_INVALID')
                target=program.workflow.steps[destinations[0]]
                status='WAITING_FOR_CONDITION' if type(target) is WaitNode else 'SLICE_DONE' if type(target) is StopNode else 'RUNNING'
                stopped=None
            else:
                stopped=loop.on_exhausted
                if stopped not in program.workflow.stop_outcomes: raise ApplicationError('WORK_LOOP_STOP_INVALID')
                destinations=[cursor];target=None;status='SLICE_DONE'
        next_inputs={**next_inputs,'rounds':rounds}
    if type(target) is StopNode:
        stopped=target.outcome
    receipt=uow.workflow.create_generated(kind='step-receipt',stable_id=f'{run_id}-{ordinal}',body={
        **receipt_facts, 'ordinal':ordinal,'step_id':node.id,'operation':node.operation,
        'stop_outcome':stopped,'result_outcome':selected_outcome,'recorded_at':now})
    uow.workflow.insert_step_log(run_id=run_id,ordinal=ordinal,step_id=node.id,
        operation=node.operation,attempt=attempt,status=state,receipt_ref=receipt)
    if next_inputs != current['inputs']:
        uow.workflow.replace_run_inputs(run_id=run_id,expected_inputs=current['inputs'],inputs=next_inputs)
    uow.workflow.update_run(run_id=run_id,status=status,cursor=destinations[0],
        wait_reason=target.id if type(target) is WaitNode else None,now=now)
    return {'run_id':run_id,'status':status,'cursor':destinations[0],
        'step_receipt_ref':asdict(receipt),'dispatched':False}



class MethodRunBindings:
    """Actual selected method + current Work source + original run identity."""
    def __init__(self, factory, method_control, source, registry_loader):
        if getattr(method_control,'factory',None) is not factory:
            raise ApplicationError('METHOD_AUTHORITY_MISMATCH')
        self.factory,self.methods,self.source,self.registry_loader=factory,method_control,source,registry_loader

    @staticmethod
    def _inputs(context,row):
        value=row['inputs']
        expected={'work_contract','scope','method_ref','compiled_plan_digest','slots'}
        if (type(value) is not dict or set(value) not in (expected,expected|{'rounds'})
                or value['work_contract'] != WORK_CONTRACT or value['scope'] != asdict(context.scope)
                or type(value['slots']) is not dict
                or ('rounds' in value and (type(value['rounds']) is not dict or any(type(v) is not int or v < 1 for v in value['rounds'].values())))):
            raise ApplicationError('WORK_BINDING_INVALID')
        try:
            return decode_method_ref(value['method_ref'])
        except (ReferenceError,TypeError,ValueError):
            raise ApplicationError('WORK_BINDING_INVALID') from None

    @staticmethod
    def _program(snapshot):
        program=snapshot.program
        if type(program) is not CompiledProgram or program.workflow.resume_contract != WORK_CONTRACT:
            raise ApplicationError('WORK_RESUME_CONTRACT_UNAVAILABLE')
        return program

    @classmethod
    def _bound_program(cls, snapshot, method, row):
        if snapshot is None or (snapshot.ref.method_id, snapshot.ref.release_version,
                snapshot.ref.schema_version, snapshot.ref.snapshot_digest) != (
                method.method_id, method.release_version, method.schema_version,
                method.snapshot_digest.hex):
            raise ApplicationError('WORK_BINDING_INVALID')
        program=cls._program(snapshot)
        if row['inputs']['compiled_plan_digest'] != program_plan_digest(program):
            raise ApplicationError('WORK_BINDING_INVALID')
        return program

    @contextmanager
    def guard_wait(self,context,run_id,row):
        if self.source is None or self.registry_loader is None:
            raise ApplicationError('WORK_WAIT_AUTHORITY_UNAVAILABLE')
        method=self._inputs(context,row)
        with self.methods.guard_method(context,method) as snapshot:
            program=self._program(snapshot)
            _check_rounds(program,row['inputs'])
            if row['inputs']['compiled_plan_digest'] != program_plan_digest(program):
                raise ApplicationError('WORK_BINDING_INVALID')
            if row['registry_ref'] != registry_ref(self.registry_loader()):
                raise ApplicationError('METHOD_CAPABILITY_CHANGED')
            with self.factory.begin(context.scope,'read') as uow:
                marker=uow.workflow.read(row['method_ref'])
                if marker != {k:v for k,v in row['inputs'].items() if k not in ('slots','rounds')}:
                    raise ApplicationError('WORK_BINDING_INVALID')
                ordinal=uow.workflow.next_step_ordinal(run_id)
            cursor=row['cursor']
            if type(cursor) is not int or not 0 <= cursor < len(program.workflow.steps):
                raise ApplicationError('WORK_CURSOR_INVALID')
            node=program.workflow.steps[cursor]
            if type(node) is not WaitNode or node.event != WAIT_EVENT or row['wait_reason'] != node.id:
                raise ApplicationError('WORK_WAIT_UNAVAILABLE')
            with self.source.guard_condition(context,snapshot,node,{'run_id':run_id,'row':_copy({**row,'method_ref':asdict(row['method_ref'])}), 'row_digest':run_wait_row_digest(row),'next_step_ordinal':ordinal}) as selected:
                if type(selected) is not WorkWaitSelection:
                    raise ApplicationError('WORK_CONDITION_INVALID')
                condition=selected.condition
                if (condition.scope != context.scope or condition.run_id != run_id
                        or condition.row_digest != run_wait_row_digest(row) or condition.next_step_ordinal != ordinal):
                    raise ApplicationError('RUN_WAIT_CHANGED')
                if condition.intent is not None and any(r.method_ref != method
                        for r in condition.intent.required_review_requirements):
                    raise ApplicationError('METHOD_REQUIREMENTS_CHANGED')
                values=_copy(selected.event_values)
                # Match is equality of exact current-owner identities, not text
                # interpreted as user confirmation or an authorization boolean.
                for binding in (() if node.match is None else node.match.entries):
                    if binding.name not in values or binding.slot not in row['inputs']['slots']:
                        raise ApplicationError('WORK_EVENT_INCOMPLETE')
                    if values[binding.name] != row['inputs']['slots'][binding.slot]:
                        raise ApplicationError('WORK_EVENT_MISMATCH')
                updates=[]
                for binding in (() if node.bind is None else node.bind.entries):
                    if not binding.slot.startswith('event.') or binding.slot[6:] not in values:
                        raise ApplicationError('WORK_EVENT_INCOMPLETE')
                    if binding.name not in (program.workflow.context_slots or ()):
                        raise ApplicationError('WORK_EVENT_INVALID')
                    updates.append((binding.name,values[binding.slot[6:]]))
                destinations=[i for i,n in enumerate(program.workflow.steps) if n.id==node.next]
                if len(destinations)!=1:
                    raise ApplicationError('WORK_CURSOR_INVALID')
                next_cursor=destinations[0]; target=program.workflow.steps[next_cursor]
                status='WAITING_FOR_CONDITION' if type(target) is WaitNode else 'SLICE_DONE' if type(target) is StopNode else 'RUNNING'
                yield BoundWorkWait(**{f.name:getattr(condition,f.name) for f in fields(condition)}, next_cursor=next_cursor,next_status=status,
                    next_wait_reason=target.id if type(target) is WaitNode else None,slot_updates=tuple(updates))


class MethodRunOrchestrator(ApprovalUseCases):
    def __init__(self,factory,access,bindings):
        super().__init__(factory,access)
        if bindings is not None and (type(bindings) is not MethodRunBindings or bindings.factory is not factory):
            raise ApplicationError('WORK_AUTHORITY_MISMATCH')
        self.bindings=bindings

    def record_dispatch_step(self, parameters, context, *, read_set=None):
        """Adopt only the original terminal dispatch row; never dispatch or retry."""
        from .native_step import record_dispatch_step
        return record_dispatch_step(self,parameters,context,read_set=read_set)

    @staticmethod
    def claim_current_wait(tx, run_id, *, expected_row_digest, expected_next_step_ordinal,
                           now, next_cursor=None, next_inputs=None,
                           next_status="RUNNING", next_wait_reason=None):
        """CAS the current MethodRun against the original run and step log."""
        row = tx.run_row(run_id)
        if (run_wait_row_digest(row) != expected_row_digest
                or tx.next_step_ordinal(run_id) != expected_next_step_ordinal):
            raise ApplicationError('RUN_WAIT_CHANGED')
        if not row['status'].startswith('WAITING_FOR_'):
            raise ApplicationError('RUN_NOT_WAITING')
        if next_inputs is not None:
            tx.replace_run_inputs(run_id=run_id, expected_inputs=row['inputs'], inputs=next_inputs)
        tx.update_run(run_id=run_id, status=next_status, cursor=next_cursor,
                      wait_reason=next_wait_reason, now=now)

    def read(self,parameters,context):
        from ..contracts.commands import CommandContext
        if type(context) is not CommandContext:
            raise ApplicationError('INVALID_CONTEXT')
        if self.access is None:
            raise ApplicationError('ACCESS_AUTHORITY_UNAVAILABLE')
        self.access.require(context,'engineering.work.get')
        try:
            require_object(parameters,{'run_id'},'INVALID_INPUT'); validate_id(parameters['run_id'])
        except (ReferenceError,TypeError,ValueError):
            raise ApplicationError('INVALID_INPUT') from None
        with self.factory.begin(context.scope,'read') as uow:
            row=uow.workflow.run_row(parameters['run_id'])
            method=MethodRunBindings._inputs(context,row)
            marker=uow.workflow.read(row['method_ref'])
            if marker != {k:v for k,v in row['inputs'].items() if k not in ('slots','rounds')}:
                raise ApplicationError('WORK_BINDING_INVALID')
            ordinal=uow.workflow.next_step_ordinal(parameters['run_id'])
            steps=uow.workflow.step_rows(parameters['run_id'])
        # Historical snapshot reads are by the row's immutable method binding;
        # they must not require that method to remain the active selection.
        snapshot=self.bindings.methods.read_snapshot(method) if self.bindings is not None else None
        from .models.method_run import MethodRun
        program=MethodRunBindings._bound_program(snapshot,method,row)
        _check_rounds(program,row['inputs'])
        run=MethodRun.from_persisted(parameters['run_id'],row,steps,program.workflow.outputs)
        return {**row,'method_ref':asdict(row['method_ref']),
            'next_step_ordinal':ordinal,'steps':run.steps_view(),'outputs':run.outputs_view(),
            'method_binding':run.method_binding_view(),'method_run':run.to_dict()}

    def list(self,parameters,context):
        """Return a bounded, scope-local view of persisted MethodRuns.

        The run rows, journal steps, ordinals, and continuation lookahead are
        read through one original SQLite UoW. Immutable method snapshots are
        then resolved by their exact persisted reference; absence of that
        reader is an explicit capability gap, never an empty result.
        """
        from ..contracts.commands import CommandContext
        from .models.method_run import MethodRun
        from ...domain.common.models.values import Digest
        if type(context) is not CommandContext:
            raise ApplicationError('INVALID_CONTEXT')
        if self.access is None:
            raise ApplicationError('ACCESS_AUTHORITY_UNAVAILABLE')
        self.access.require(context,'engineering.runs.list')
        if type(parameters) is not dict or set(parameters) - {'after','limit'}:
            raise ApplicationError('INVALID_INPUT')
        after=parameters.get('after')
        limit=parameters.get('limit',128)
        try:
            if after is not None:
                validate_id(after)
            if type(limit) is not int or not 1 <= limit <= 256:
                raise ValueError
        except (ReferenceError,TypeError,ValueError):
            raise ApplicationError('INVALID_INPUT') from None
        methods=None if self.bindings is None else getattr(self.bindings,'methods',None)
        reader=None if methods is None else getattr(methods,'read_snapshot',None)
        if not callable(reader):
            raise ApplicationError('METHOD_RUN_READER_UNAVAILABLE')

        with self.factory.begin(context.scope,'read') as uow:
            rows=uow.workflow.list_run_rows(after=after,limit=limit)
            projections=[]
            for row in rows:
                run_id=row['run_id']
                method=MethodRunBindings._inputs(context,row)
                marker=uow.workflow.read(row['method_ref'])
                if marker != {k:v for k,v in row['inputs'].items() if k not in ('slots','rounds')}:
                    raise ApplicationError('WORK_BINDING_INVALID')
                projections.append((run_id,row,method,
                    uow.workflow.step_rows(run_id),uow.workflow.next_step_ordinal(run_id)))
            next_after=None
            if rows and len(rows)==limit:
                candidate=rows[-1]['run_id']
                if uow.workflow.list_run_rows(after=candidate,limit=1):
                    next_after=candidate

        runs=[]
        for run_id,row,method,steps,ordinal in projections:
            snapshot=reader(method)
            if snapshot is None:
                raise ApplicationError('METHOD_RUN_READER_UNAVAILABLE')
            program=MethodRunBindings._bound_program(snapshot,method,row)
            _check_rounds(program,row['inputs'])
            run=MethodRun.from_persisted(run_id,row,steps,program.workflow.outputs)
            runs.append({**run.to_dict(),'next_step_ordinal':ordinal,
                'review':{'availability':'unavailable'},
                'acceptance':{'availability':'unavailable'}})
        scope=asdict(context.scope)
        revision=Digest('sha256',hashlib.sha256(canonical_bytes(
            {'scope':scope,'runs':runs,'next_after':next_after})).hexdigest())
        return {'scope':scope,'revision':asdict(revision),'runs':tuple(runs),
                'next_after':next_after}

    def record_command_step(self,parameters,context,*,read_set=None):
        """Consume an actual original journal result; never dispatch or retry."""
        from ..contracts.commands import CommandKey, ReadSet, request_digest, read_set_projection, artifact_read_set_projection
        from .method_bridge import MethodBridge
        from ...methods.definitions.models.compiled import OperationNode
        from ...domain.common.models.values import Digest
        import hashlib
        op='engineering.work.record_command_step'
        value,reads,digest=self._input(op,parameters,context,read_set)
        try:
            validate_id(value['run_id']); validate_id(value['operation_request_id'])
            expected=Digest(**value['expected_row_digest'])
        except (ReferenceError,TypeError,ValueError):
            raise ApplicationError('INVALID_INPUT') from None
        replay=self._replay(op,context,digest)
        if replay is not None:
            return replay
        binding=self.bindings
        if binding is None or binding.source is None:
            raise ApplicationError('WORK_WAIT_AUTHORITY_UNAVAILABLE')
        with self.factory.begin(context.scope,'read') as uow:
            row=uow.workflow.run_row(value['run_id'])
        method=binding._inputs(context,row)
        with binding.methods.guard_method(context,method) as snapshot:
            program=binding._program(snapshot)
            _check_rounds(program,row['inputs'])
            if binding.registry_loader is None:
                raise ApplicationError('METHOD_CAPABILITY_CHANGED')
            selected_registry=registry_ref(binding.registry_loader())
            if row['registry_ref']!=selected_registry:
                raise ApplicationError('METHOD_CAPABILITY_CHANGED')
            if row['inputs']['compiled_plan_digest']!=program_plan_digest(program):
                raise ApplicationError('WORK_BINDING_INVALID')
            cursor=row['cursor']
            if (row['status']!='RUNNING' or type(cursor) is not int
                    or not 0<=cursor<len(program.workflow.steps)
                    or type(program.workflow.steps[cursor]) is not OperationNode):
                raise ApplicationError('WORK_OPERATION_UNAVAILABLE')
            node=program.workflow.steps[cursor]
            # Ordinary Facade commands only. External dispatch has its own
            # durable outcome owner and cannot be replaced by a journal guess.
            params=MethodBridge().operation_inputs(program,node.id,row['inputs']['slots'])
            source_guard=getattr(binding.source,'guard_step_completion',None)
            if not callable(source_guard):
                raise ApplicationError('WORK_COMPLETION_SOURCE_UNAVAILABLE')
            with source_guard(context,snapshot,node,{'run_id':value['run_id'],'row':row}) as invocation_reads:
                if type(invocation_reads) is not ReadSet or invocation_reads.scope!=context.scope:
                    raise ApplicationError('WORK_COMPLETION_SOURCE_INVALID')
                from ..api import EngineeringService
                expected_command=EngineeringService.command_request_digest(
                    node.operation,params,context,invocation_reads)
                def mutate(uow):
                    uow.engineering.check_read_set(invocation_reads)
                    if selected_registry != registry_ref(binding.registry_loader()):
                        raise ApplicationError('METHOD_CAPABILITY_CHANGED')
                    current=uow.workflow.run_row(value['run_id'])
                    if (run_wait_row_digest(current)!=expected or current!=row
                            or uow.workflow.next_step_ordinal(value['run_id'])!=value['expected_next_step_ordinal']):
                        raise ApplicationError('RUN_WAIT_CHANGED')
                    if uow.workflow.read(current['method_ref']) != {k:v for k,v in current['inputs'].items() if k not in ('slots','rounds')}:
                        raise ApplicationError('WORK_BINDING_INVALID')
                    entry=uow.commands.get(CommandKey(context.scope.realm_id,context.principal_id,value['operation_request_id']))
                    if (entry is None or entry.operation!=node.operation or entry.project_id!=context.scope.project_id
                            or entry.request_digest!=expected_command):
                        raise ApplicationError('WORK_COMMAND_RESULT_MISMATCH')
                    if any(uow.workflow.read(prior['receipt_ref']).get('original_command_key')==asdict(entry.key)
                           for prior in uow.workflow.step_rows(value['run_id']) if prior['receipt_ref'] is not None):
                        raise ApplicationError('WORK_COMMAND_ALREADY_CONSUMED')
                    if entry.state not in ('completed','rejected'):
                        raise ApplicationError('WORK_OPERATION_OUTCOME_UNKNOWN')
                    selected_outcome=entry.state
                    if entry.state=='completed' and node.result_routing is not None:
                        selected_outcome=_route_result(entry.result_bytes,node.result_routing)
                        transitions=[t.target for t in node.result_routing.outcomes.entries
                                     if t.outcome==selected_outcome]
                    else:
                        transitions=[t.target for t in node.outcomes.entries if t.outcome==selected_outcome]
                    if len(transitions)!=1 or transitions[0].wait is not None:
                        raise ApplicationError('WORK_TRANSITION_UNAVAILABLE')
                    return _advance_step(uow,current,program,node,run_id=value['run_id'],
                        next_ordinal=value['expected_next_step_ordinal'],state=entry.state,
                        selected_outcome=selected_outcome,transitions=transitions,receipt_facts={
                            'schema_version':'engineering-method-step-receipt/1','scope':asdict(context.scope),
                            'run_id':value['run_id'],'method_ref':asdict(method),
                            'compiled_plan_digest':program_plan_digest(program),
                            'original_command_key':asdict(entry.key),'original_operation_id':entry.operation_id,
                            'request_digest':asdict(entry.request_digest),'state':entry.state,
                            'result':entry.result_bytes.decode('utf-8')})
                return self._run(op,context,reads,digest,mutate)

    def bind_inputs(self,parameters,context,*,read_set=None):
        """Bind an explicitly submitted method-input revision to the original run.

        No head adoption, cursor advance, execution, reviewer role, or approval
        follows from this input selection. Exact source reads and the original
        row/ordinal CAS remain live through the write transaction.
        """
        op='engineering.work.bind_inputs'
        value,reads,digest=self._input(op,parameters,context,read_set)
        from ...domain.artifacts.ref_codec import decode_artifact_ref
        from ...domain.common.mechanisms.codec import decode_digest
        try:
            validate_id(value['run_id'])
            input_ref=decode_artifact_ref(value['input_ref'])
            expected=decode_digest(value['expected_row_digest'])
        except (ReferenceError,TypeError,ValueError,KeyError):
            raise ApplicationError('INVALID_INPUT') from None
        replay=self._replay(op,context,digest)
        if replay is not None:
            return replay
        binding=self.bindings
        if binding is None or not callable(getattr(binding.source,'guard_inputs',None)):
            raise ApplicationError('WORK_INPUT_SOURCE_UNAVAILABLE')
        with self.factory.begin(context.scope,'read') as uow:
            row=uow.workflow.run_row(value['run_id'])
            ordinal=uow.workflow.next_step_ordinal(value['run_id'])
        if (run_wait_row_digest(row) != expected
                or ordinal != value['expected_next_step_ordinal']):
            raise ApplicationError('RUN_WAIT_CHANGED')
        if row['status'] != 'WAITING_FOR_CONDITION':
            raise ApplicationError('RUN_NOT_WAITING')
        method=MethodRunBindings._inputs(context,row)
        with binding.methods.guard_method(context,method) as snapshot:
            program=MethodRunBindings._bound_program(snapshot,method,row)
            view={'run_id':value['run_id'],'row':_copy({**row,'method_ref':asdict(row['method_ref'])}),
                  'row_digest':expected,'next_step_ordinal':ordinal}
            with binding.source.guard_inputs(context,snapshot,view,input_ref) as seed:
                if (type(seed) is not WorkSeed or seed.read_set.scope != context.scope
                        or len(seed.slots) != 1 or not set(seed.slots) <= set(program.workflow.context_slots or ())):
                    raise ApplicationError('WORK_INPUT_INVALID')
                inputs={**row['inputs'],'slots':{**row['inputs']['slots'],**_copy(seed.slots)}}
                def mutate(uow):
                    current=uow.workflow.run_row(value['run_id'])
                    if (run_wait_row_digest(current) != expected
                            or uow.workflow.next_step_ordinal(value['run_id']) != ordinal):
                        raise ApplicationError('RUN_WAIT_CHANGED')
                    uow.engineering.check_read_set(seed.read_set)
                    uow.workflow.replace_run_inputs(run_id=value['run_id'],
                        expected_inputs=current['inputs'],inputs=inputs)
                    return {'run_id':value['run_id'],'status':current['status'],
                            'cursor':current['cursor'],'input_slots':sorted(seed.slots),'dispatched':False}
                return self._run(op,context,reads,digest,mutate)

    def start(self,parameters,context,*,read_set=None):
        op='engineering.work.start'
        value,reads,digest=self._input(op,parameters,context,read_set)
        try:
            validate_id(value['run_id'])
        except (ReferenceError,TypeError,ValueError):
            raise ApplicationError('INVALID_INPUT') from None
        replay=self._replay(op,context,digest)
        if replay is not None:
            return replay
        binding=self.bindings
        if binding is None or binding.source is None or binding.registry_loader is None:
            raise ApplicationError('WORK_WAIT_AUTHORITY_UNAVAILABLE')
        with binding.methods.guard_selected(context) as snapshot:
            program=binding._program(snapshot)
            nodes=[(i,n) for i,n in enumerate(program.workflow.steps) if n.id==program.workflow.entry]
            if len(nodes)!=1 or type(nodes[0][1]) is not WaitNode or nodes[0][1].event != WAIT_EVENT:
                raise ApplicationError('WORK_ENTRY_UNAVAILABLE')
            cursor,node=nodes[0]
            from ...domain.artifacts.method_binding import MethodRef
            from ...domain.common.models.values import Digest
            ref=snapshot.ref
            method=MethodRef(ref.method_id,ref.release_version,ref.schema_version,Digest('sha256',ref.snapshot_digest))
            with binding.source.guard_start(context,snapshot, run_id=value['run_id'],
                                            selection=value.get('selection')) as seed:
                if (type(seed) is not WorkSeed or seed.read_set.scope != context.scope
                        or not set(seed.slots) <= set(program.workflow.context_slots or ())):
                    raise ApplicationError('WORK_INPUT_INVALID')
                marker={'work_contract':WORK_CONTRACT,'scope':asdict(context.scope),
                    'method_ref':asdict(method),'compiled_plan_digest':program_plan_digest(program)}
                inputs={**marker,'slots':_copy(seed.slots)}
                if program.workflow.loops:
                    inputs['rounds']={loop.loop_id:1 for loop in program.workflow.loops}
                registry=registry_ref(binding.registry_loader())
                def mutate(uow):
                    # Reuse the original transaction/CAS owner before any Work
                    # write. Source observations cannot replace these checks.
                    uow.engineering.check_read_set(seed.read_set)
                    if registry != registry_ref(binding.registry_loader()):
                        raise ApplicationError('METHOD_CAPABILITY_CHANGED')
                    material=uow.workflow.write_material(kind='method',stable_id='compiled-work:'+value['run_id'],
                        revision=1,body=marker,generated=False)
                    now=utc_now()
                    uow.workflow.insert_run(run_id=value['run_id'],method_ref=material,registry_ref=registry,inputs=inputs,now=now)
                    uow.workflow.update_run(run_id=value['run_id'],status='WAITING_FOR_CONDITION',cursor=cursor,wait_reason=node.id,now=now)
                    return {'run_id':value['run_id'],'status':'WAITING_FOR_CONDITION','cursor':cursor,
                        'method_ref':asdict(method),'dispatched':False}
                return self._run(op,context,reads,digest,mutate)

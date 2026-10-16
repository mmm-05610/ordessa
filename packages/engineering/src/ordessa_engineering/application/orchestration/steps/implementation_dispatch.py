"""Original Engineering run/step attempt binds a package to one native operation.

Two COMMITs reserve the original attempt and its immutable budget. An additional
original approval/control write cut guards only the first actual native frame;
later revocation cannot recall in-flight bytes. Native lease gates remain live.
There is no distributed transaction or exactly-once claim. Reserved debits are
conservative and immutable: this owner never refunds or retries an unknown send.
"""
from contextlib import contextmanager,asynccontextmanager,ExitStack
import asyncio
from collections.abc import Mapping
from dataclasses import asdict
from uuid import uuid4
import hashlib

from ordessa_infrastructure.encoding import canonical_bytes,decode_json
from ...contracts.commands import CommandContext
from ...contracts.errors import ApplicationError
from ...contracts.execution_dispatch import EXECUTION_DISPATCH
from ....domain.changes.dispatch import DispatchBinding
from ....domain.changes.dispatch_codec import encode_dispatch,decode_dispatch
from ....domain.common.models.values import Digest,validate_id
from ....domain.common.models.refs import BlobRef
from ...usecases.packages.implementation import ImplementationUseCases

_SEND=EXECUTION_DISPATCH
_RECONCILE='engineering.implementation.reconcile'


def _digest(raw):return Digest('sha256',hashlib.sha256(raw).hexdigest())

def _data(value):
    if isinstance(value,Mapping):return {k:_data(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [_data(v) for v in value]
    return value



class ImplementationDispatch:
    def __init__(self,factory,access=None,*,approval_usecases=None,execution=None,selection=None,blobs=None,registry_loader=None,source_snapshots=None,history_sources=None,method_runs=None):
        if approval_usecases is not None and getattr(approval_usecases,'factory',None) is not factory:
            raise ApplicationError('AUTHORIZATION_AUTHORITY_MISMATCH')
        if blobs is not None and getattr(blobs,'authority_id',None)!=factory.authority_id:
            raise ApplicationError('BLOB_AUTHORITY_MISMATCH')
        self.factory,self.access,self.approvals,self.execution,self.selection,self.blobs=factory,access,approval_usecases,execution,selection,blobs
        self.registry_loader=registry_loader
        self.source_snapshots=source_snapshots
        self.history_sources=history_sources
        if method_runs is not None and getattr(method_runs,'factory',None) is not factory:
            raise ApplicationError('DISPATCH_WORK_BINDING_AUTHORITY_UNAVAILABLE')
        self.method_runs=method_runs

    def _access(self,context,operation):
        if type(context) is not CommandContext or self.access is None:raise ApplicationError('ACCESS_AUTHORITY_UNAVAILABLE')
        self.access.require(context,operation)

    @contextmanager
    def _guard_selection(self,context,package,unit_ref):
        guard=getattr(self.selection,'guard_selection',None)
        if not callable(guard):raise ApplicationError('DISPATCH_SELECTION_AUTHORITY_UNAVAILABLE')
        selected=guard(context,package,unit_ref)
        if not callable(getattr(selected,'__enter__',None)) or not callable(getattr(selected,'__exit__',None)):
            raise ApplicationError('DISPATCH_SELECTION_AUTHORITY_UNAVAILABLE')
        with selected as evidence:
            yield evidence

    @contextmanager
    def _guards(self,context,package,unit=None):
        if self.approvals is None:raise ApplicationError('IMPLEMENTATION_GRANT_AUTHORITY_UNAVAILABLE')
        with self.factory.begin(context.scope,'read') as uow:
            grant=uow.authorization.get_grant(package.payload.authorization_refs[0])
        with ExitStack() as stack:
            if unit is not None:
                # The selected package/Unit remains guarded across each
                # original COMMIT cut and the caller's native-write scope.
                stack.enter_context(self._guard_selection(context,package,unit))
            admission=self.approvals._admission()
            stack.enter_context(admission.guard_intent(context,grant.intent))
            stack.enter_context(admission.guard_evidence(context,grant.intent,grant.evidence))
            decisions=stack.enter_context(self.approvals._gates(context,grant.intent))
            if unit is not None:
                if self.source_snapshots is None:raise ApplicationError('DISPATCH_SOURCE_SNAPSHOT_AUTHORITY_UNAVAILABLE')
                snapshot=stack.enter_context(self.source_snapshots.guard_commit_snapshot(context,package,unit))
                required={'contract','sourceCut','permissionCut','observedAt','authorizedAt','authorityRevision',
                    'managementEpoch','unitRef','nodeRef','publicationRevision','profileRevision',
                    'preparationOperationRef','preparationOperationRevision','directoryBindingRef',
                    'localDirectory','queryOperationRef','queryInputDigest','currentThroughCommit',
                    'liveDispatchAuthorized','checkoutBaselineVerified'}
                if (not isinstance(snapshot,Mapping) or set(snapshot)!=required
                        or snapshot.get('contract')!='unit-live-source-snapshot/1'
                        or snapshot.get('sourceCut')!='observed-live-owner'
                        or snapshot.get('permissionCut')!='authorized-read-time'
                        or snapshot.get('currentThroughCommit') is not False
                        or snapshot.get('liveDispatchAuthorized') is not False
                        or snapshot.get('checkoutBaselineVerified') is not False
                        or canonical_bytes(_data(snapshot.get('unitRef')))!=canonical_bytes(_data(unit))):
                    raise ApplicationError('DISPATCH_SOURCE_SNAPSHOT_INVALID')
            yield grant,decisions

    def _work_package(self,uow,run_id,*,step_id=None,live=False,attempt=None,request=None,binding=None):
        from ..dispatch_method_run import resolve_method_run_package
        package=resolve_method_run_package(uow,run_id,self.method_runs,step_id=step_id,live=live,attempt=attempt)
        if request is not None:
            from ..dispatch_recipe import check_dispatch_recipe
            check_dispatch_recipe(uow,self.method_runs,package,request)
        if binding is not None:
            from ..dispatch_recipe import check_bound_dispatch_recipe
            check_bound_dispatch_recipe(uow,self.method_runs,package,binding)
        return package

    @contextmanager
    def _input_guards(self,context,package,unit,request):
        with ExitStack() as stack:
            if self.source_snapshots is not None:
                guard=getattr(self.source_snapshots,'guard_dispatch_input',None)
                if callable(guard):
                    stack.enter_context(guard(context,package,unit,request))
            yield stack.enter_context(self._guards(context,package,unit))

    @staticmethod
    def _existing(uow,run_id,step_id,attempt):
        try:return uow.dispatch.get(run_id,step_id,attempt,uow.scope)
        except ApplicationError as exc:
            if exc.code=='NOT_FOUND':return None
            raise

    @staticmethod
    def _view(row,reason=None):
        binding=decode_dispatch(row['binding_bytes'])
        return {'run_id':row['run_id'],'step_id':row['step_id'],'attempt':row['attempt'],
            'fence':row['dispatch_fence'],'version':row['dispatch_version'],
            'phase':row['dispatch_phase'],'execution_operation_ref':binding.execution_operation_ref,
            'binding_digest':asdict(binding.digest),'action_instances':list(binding.action_instances),
            'result_blob_ref':None if row['result_blob_json'] is None else decode_json(row['result_blob_json']),
            'engineering_completed':False,'accepted':False,'reason':reason}

    def dispatch_declared_work(self, identity, work_id, action_id, step_id, attempt,
                               unit_ref, params, actions, context, *, timeout=60):
        """Dispatch one declared Work step, refusing by the real missing item.

        The subject comes from the Work, never from a run row: a generation step
        acts on the already reviewed change, an implementation step on the frozen
        admitted package. Each precondition is checked in order against real
        state and refuses by name, so no run row, package or grant is ever stood
        in for a declared step.
        """
        self._access(context, _SEND)
        if self.execution is None or self.blobs is None:
            raise ApplicationError('DISPATCH_EXECUTION_AUTHORITY_UNAVAILABLE')
        if not callable(getattr(self.selection, 'guard_selection', None)):
            raise ApplicationError('DISPATCH_SELECTION_AUTHORITY_UNAVAILABLE')
        if (type(actions) is not tuple or not actions
                or len(set(actions)) != len(actions)
                or type(attempt) is not int or not 1 <= attempt <= 4096):
            raise ApplicationError('INVALID_ARGUMENT')
        for value in (work_id, action_id, step_id):
            validate_id(value)
        # The same platform rule the implementation line enforces: generation,
        # change application and acceptance are not dispatched as implementation
        # work. A declared generation step therefore has no dispatch here.
        if set(actions) & {'generate_package', 'apply_change', 'accept_artifact'}:
            raise ApplicationError('ACTION_NOT_AUTHORIZED')
        # An implementation step of a declared Work needs a frozen admitted
        # package to act on; the Work's own associations are the only source.
        with self.factory.begin(context.scope, 'read') as uow:
            binding = self._declared_work_subject(uow, work_id, action_id, step_id)
        if binding is None:
            raise ApplicationError('DISPATCH_DECLARED_WORK_SUBJECT_MATERIAL_UNAVAILABLE')
        raise ApplicationError('DISPATCH_DECLARED_WORK_GRANT_UNAVAILABLE')

    def _declared_work_subject(self, uow, work_id, action_id, step_id):
        """The declared step's subject, taken from this Work's own records.

        Returns a schema-2 binding when the Work already carries a subject this
        step may act on (a frozen package for implementation), otherwise None.
        Nothing is inferred from a run row or from a caller-supplied reference.
        """
        from ordessa_engineering.application.contracts.work_context import (
            WORK_CONTEXT_KIND, WORK_STABLE_ID_PREFIX, decode_work_binding)
        stable = f'{WORK_STABLE_ID_PREFIX}{work_id}'
        head = uow.workflow.head_ref(WORK_CONTEXT_KIND, stable)
        if head is None:
            return None
        work_binding = decode_work_binding(uow.workflow.read(head))
        packages = [association for association in work_binding.associations
                    if association.kind == 'package']
        if len(packages) != 1:
            return None
        return packages[0].ref

    def dispatch(self,run_id,step_id,attempt,unit_ref,params,actions,context,*,timeout=60):
        self._access(context,_SEND)
        if self.execution is None or self.blobs is None:raise ApplicationError('DISPATCH_EXECUTION_AUTHORITY_UNAVAILABLE')
        if not callable(getattr(self.selection,'guard_selection',None)):
            raise ApplicationError('DISPATCH_SELECTION_AUTHORITY_UNAVAILABLE')
        for value in (run_id,step_id):validate_id(value)
        if type(attempt) is not int or not 1<=attempt<=4096 or type(actions) is not tuple or not actions or len(set(actions))!=len(actions):raise ApplicationError('INVALID_ARGUMENT')
        request=decode_json(canonical_bytes({'run_id':run_id,'step_id':step_id,
            'attempt':attempt,'unit_ref':_data(unit_ref),'params':_data(params),
            'actions':list(actions),'timeout':timeout}))
        unit_bytes=canonical_bytes(_data(unit_ref))
        with self.factory.begin(context.scope,'read') as uow:
            package=self._work_package(uow,run_id,step_id=step_id)
            old=self._existing(uow,run_id,step_id,attempt)
            if old is None:
                self._work_package(uow,run_id,step_id=step_id,live=True,attempt=attempt,request=request)
        # A fresh recipe is now method/package checked before any input blob
        # or conservative action reservation. Replay retains its old binding.
        raw,prompt_digest=self.execution.freeze_input(unit_ref,request['params'])
        prompt=self.blobs.put_verified(raw,_digest(raw),'application/json')
        with self.factory.begin(context.scope,'read') as uow:
            if old is not None:
                binding=decode_dispatch(old['binding_bytes'])
                if (binding.package_ref!=package.ref or binding.unit_ref_bytes!=unit_bytes
                        or binding.prompt_ref!=prompt or binding.prompt_input_digest!=prompt_digest
                        or tuple(a for a,_ in binding.action_instances)!=actions):
                    raise ApplicationError('DISPATCH_ATTEMPT_CONFLICT')
                # No operation or consumption ID is minted on a retry, and no
                # presumed native absence is inferred from a refused query.
                return self._view(old,'RESERVED_REQUIRES_ORIGINAL_NEVER_SENT_PROOF' if old['dispatch_phase']=='reserved' else None)
            self._work_package(uow,run_id,step_id=step_id,live=True,attempt=attempt,request=request)
        with self._input_guards(context,package,unit_ref,request) as (grant,decisions):
            with self.factory.begin(context.scope) as uow:
                self._work_package(uow,run_id,step_id=step_id,live=True,attempt=attempt,request=request)
                ImplementationUseCases._resolve_package(uow,package,now=context.received_at)
                self.approvals._check_gates(uow,decisions)
                if not set(actions)<=set(package.payload.allowed_actions):raise ApplicationError('ACTION_NOT_AUTHORIZED')
                if set(actions)&{'generate_package','apply_change','accept_artifact'}:raise ApplicationError('ACTION_NOT_AUTHORIZED')
                if self._existing(uow,run_id,step_id,attempt) is not None:raise ApplicationError('DISPATCH_ATTEMPT_CONFLICT')
                operation=str(uuid4());instances=tuple((a,str(uuid4())) for a in actions)
                requirements=('submission',)+tuple(sorted(r.template_id+':'+str(r.template_version)+':sha256:'+r.digest.hex for r in package.payload.acceptance_requirements))
                control=uow.authorization.get_control(grant.ref)
                binding=DispatchBinding(context.scope,run_id,step_id,attempt,1,package.ref,grant.ref,grant.intent.digest,
                    control['version'],instances,unit_bytes,operation,prompt,prompt_digest,
                    self.execution.query_digest(unit_ref,operation,prompt_digest),requirements)
                for action,instance in instances:
                    uow.authorization.consume_action(grant.ref,action=action,action_instance_id=instance,target_digest=binding.digest,now=context.received_at)
                encoded=encode_dispatch(binding)
                row=uow.dispatch.reserve(run_id,step_id,attempt,context.scope,encoded,_digest(encoded),operation)
                uow.commit()
        # Only this fresh invocation owns the newly reserved first send. A crash
        # here leaves reserved visible with debit retained, not a replay token.
        with self._input_guards(context,package,unit_ref,request) as (_grant,decisions):
            with self.factory.begin(context.scope) as uow:
                self._work_package(uow,run_id,step_id=step_id,live=True,attempt=attempt,request=request)
                ImplementationUseCases._resolve_package(uow,package,now=context.received_at)
                self.approvals._check_gates(uow,decisions)
                if uow.authorization.get_control(binding.approval_ref)['version']!=binding.control_version:
                    raise ApplicationError('APPROVAL_CONTROL_CHANGED')
                row=uow.dispatch.transition(run_id,step_id,attempt,context.scope,expected_version=0,fence=1,phase='possibly_written')
                uow.commit()
        # Two business COMMITs do not grant continued send permission. The
        # trusted Unit factory must enter acquire_effect_write around its
        # actual bounded byte write, before its own writer/epoch lock.
        try:
            handoff=getattr(self.execution,'guard_effect_handoff',None)
            if not callable(handoff):raise ApplicationError('DISPATCH_EFFECT_HANDOFF_AUTHORITY_UNAVAILABLE')
            with handoff(context,binding,access=self.access,timeout=timeout):
                self.execution.send(binding,timeout=timeout)
        except Exception:
            # The handoff manager must first resume this exact admission. If
            # it was revoked while the native call waited, refuse to write an
            # UNKNOWN receipt under a stale caller lease; the durable
            # possibly_written phase remains conservative.
            self._access(context,_SEND)
            with self.factory.begin(context.scope) as uow:
                row=uow.dispatch.transition(run_id,step_id,attempt,context.scope,expected_version=row['dispatch_version'],fence=1,phase='unknown')
                uow.commit()
            return self._view(row,'NATIVE_SEND_OUTCOME_UNCONFIRMED')
        self._access(context,_SEND)
        return self._reconcile_receipt(run_id,step_id,attempt,context)

    @asynccontextmanager
    async def acquire_effect_write(self, context, binding, identity, deadline, *, handoff):
        """Original approval/control synchronization, on the actual SDK thread.

        No UoW/repository is transferred between threads. The fail-fast same
        connection transaction blocks legitimate revocation COMMITs while this
        manager surrounds only the bounded native write, never its response.
        """
        if type(binding) is not DispatchBinding or handoff is None or self.access is None:
            raise ApplicationError('DISPATCH_EFFECT_HANDOFF_UNAVAILABLE')
        consume=getattr(self.access,'consume_effect_write',None)
        if not callable(consume):raise ApplicationError('DISPATCH_EFFECT_HANDOFF_UNAVAILABLE')
        with consume(handoff,context,invocation_key=bytes.fromhex(binding.digest.hex),
                action_instances=binding.action_instances):
            async with self._acquire_effect_write_cut(context,binding,identity,deadline):
                yield

    @asynccontextmanager
    async def _acquire_effect_write_cut(self, context, binding, identity, deadline):
        from ...usecases.support.clock import utc_now
        self._access(context, _SEND)
        if (type(binding) is not DispatchBinding or binding.scope!=context.scope
                or not isinstance(identity,Mapping)
                or set(identity)!={'unitRef','operationRef','inputDigest','requestId','frameDigest'}
                or canonical_bytes(_data(identity['unitRef']))!=binding.unit_ref_bytes
                or identity['operationRef']!=binding.execution_operation_ref
                or identity['inputDigest']!='sha256:'+binding.prompt_input_digest.hex
                or type(identity['requestId']) not in (str,int) or identity['requestId']==''
                or type(identity['frameDigest']) is not str or not identity['frameDigest'].startswith('sha256:')
                or len(identity['frameDigest'])!=71
                or any(c not in '0123456789abcdef' for c in identity['frameDigest'][7:])):
            raise ApplicationError('DISPATCH_EFFECT_BINDING_MISMATCH')
        begin=getattr(self.factory,'begin_effect_cut',None)
        if not callable(begin):raise ApplicationError('DISPATCH_EFFECT_TRANSACTION_UNAVAILABLE')
        loop=asyncio.get_running_loop()
        if type(deadline) not in (int,float) or not loop.time()<deadline<=loop.time()+10:
            raise ApplicationError('DISPATCH_EFFECT_DEADLINE_INVALID')
        with self.factory.begin(context.scope,'read') as read:
            package=self._work_package(read,binding.run_id,step_id=binding.step_id,
                live=True,attempt=binding.attempt,binding=binding)
            request={'run_id':binding.run_id,'step_id':binding.step_id,'attempt':binding.attempt,
                'unit_ref':decode_json(binding.unit_ref_bytes),
                'params':decode_json(read.implementation.read_blob(binding.prompt_ref)),
                'actions':[action for action,_ in binding.action_instances],'timeout':None}
        with self._input_guards(context,package,decode_json(binding.unit_ref_bytes),request) as (grant,decisions):
            while True:
                if loop.time()>=deadline:raise ApplicationError('DISPATCH_EFFECT_TIMEOUT')
                uow=begin(context.scope)
                try:
                    uow.__enter__()
                    break
                except ApplicationError as exc:
                    if exc.code!='EFFECT_WRITE_BUSY':raise
                    await asyncio.sleep(min(.005,max(0,deadline-loop.time())))
            with ExitStack() as stack:
                stack.callback(uow.__exit__,None,None,None)
                # No await occurs until all original business predicates pass.
                package_now=self._work_package(uow,binding.run_id,step_id=binding.step_id,
                    live=True,attempt=binding.attempt,binding=binding)
                if package_now.ref!=binding.package_ref or package_now!=package:
                    raise ApplicationError('DISPATCH_RUN_BINDING_MISMATCH')
                now=utc_now()
                ImplementationUseCases._resolve_package(uow,package_now,now=now)
                self.approvals._check_gates(uow,decisions)
                control=uow.authorization.get_control(binding.approval_ref)
                if (grant.ref!=binding.approval_ref or grant.intent.digest!=binding.intent_digest
                        or control['state']!='granted' or control['version']!=binding.control_version):
                    raise ApplicationError('APPROVAL_CONTROL_CHANGED')
                if not grant.intent.not_before<=now<grant.intent.expires_at:
                    raise ApplicationError('AUTHORIZATION_EXPIRED')
                if not {action for action,_ in binding.action_instances}<=set(package_now.payload.allowed_actions):
                    raise ApplicationError('ACTION_NOT_AUTHORIZED')
                row=uow.dispatch.get(binding.run_id,binding.step_id,binding.attempt,binding.scope)
                if (row['binding_bytes']!=encode_dispatch(binding) or row['dispatch_fence']!=binding.fence
                        or row['dispatch_phase']!='possibly_written'):
                    raise ApplicationError('DISPATCH_EFFECT_BINDING_MISMATCH')
                uow.authorization.check_action_consumptions(binding.approval_ref,
                    intent_digest=binding.intent_digest,target_digest=binding.digest,
                    action_instances=binding.action_instances)
                if loop.time()>=deadline:raise ApplicationError('DISPATCH_EFFECT_TIMEOUT')
                yield
                # Empty commit releases the actual original write lock. A
                # failure after bytes were written must remain native unknown.
                uow.commit()

    def reconcile(self,run_id,step_id,attempt,context):
        self._access(context,_RECONCILE)
        return self._reconcile_receipt(run_id,step_id,attempt,context)

    def _reconcile_receipt(self,run_id,step_id,attempt,context):
        if self.execution is None or self.blobs is None:raise ApplicationError('DISPATCH_EXECUTION_AUTHORITY_UNAVAILABLE')
        with self.factory.begin(context.scope,'read') as uow:
            package=self._work_package(uow,run_id,step_id=step_id);row=uow.dispatch.get(run_id,step_id,attempt,context.scope)
            if row['dispatch_phase'] in {'reserved','completed','failed'}:return self._view(row)
            binding=decode_dispatch(row['binding_bytes'])
        if self.history_sources is None:raise ApplicationError('DISPATCH_HISTORY_SOURCE_AUTHORITY_UNAVAILABLE')
        # This is authorized history read-time provenance, not live selection
        # or an action Grant. The old strong selection port is not weakened.
        with ExitStack() as source_stack:
            guard=getattr(self.history_sources,'guard_dispatch_input',None)
            if callable(guard):
                with self.factory.begin(context.scope,'read') as read:
                    frozen_params=decode_json(read.implementation.read_blob(binding.prompt_ref))
                source_stack.enter_context(guard(context,package,decode_json(binding.unit_ref_bytes),
                    {'run_id':binding.run_id,'step_id':binding.step_id,'attempt':binding.attempt,
                     'unit_ref':decode_json(binding.unit_ref_bytes),'params':frozen_params,
                     'actions':[action for action,_ in binding.action_instances],
                     'timeout':None}))  # History queries impose no send timeout.
            source_stack.enter_context(self.history_sources.guard_history_read(
                context,package,decode_json(binding.unit_ref_bytes)))
            capture=self.execution.capture(binding)  # Authorized native cold read; never dispatch.
            # Capture's original function already checks full Unit/op/input/query.
            if capture.operation_ref!=binding.execution_operation_ref or capture.expected_prompt_digest!='sha256:'+binding.prompt_input_digest.hex or capture.query_digest!=binding.expected_query_digest:
                raise ApplicationError('DISPATCH_RECEIPT_BINDING_MISMATCH')
            native_phase=capture.state
            phase=native_phase if native_phase in {'completed','failed'} else 'unknown'
            with self.factory.begin(context.scope) as uow:
                self._work_package(uow,run_id,step_id=step_id)
                uow.implementation.read_blob(capture.blob_ref)
                current=uow.dispatch.get(run_id,step_id,attempt,context.scope)
                if current['dispatch_version']!=row['dispatch_version']:raise ApplicationError('DISPATCH_CHANGED')
                row=uow.dispatch.transition(run_id,step_id,attempt,context.scope,
                    expected_version=current['dispatch_version'],fence=binding.fence,phase=phase,result_blob_ref=capture.blob_ref)
                uow.commit()
        return self._view(row)


def resolve_dispatch_submission_binding(uow, submission, *, method_runs=None):
    """Same original write-UoW correlation, not file/test provenance or acceptance.

    Schema12 remains readable; new normal dispatch-bound Submission needs13.
    """
    try:
        row=uow.dispatch.by_operation(submission.execution_ref.operation_ref,uow.scope)
    except ApplicationError as exc:
        if exc.code in {'NOT_FOUND','DISPATCH_SCHEMA_REQUIRED'}:
            raise ApplicationError('SUBMISSION_DISPATCH_BINDING_UNAVAILABLE') from exc
        raise
    binding=decode_dispatch(row['binding_bytes'])
    execution=submission.execution_ref
    unit={'environmentNamespace':execution.environment_namespace,'unitId':execution.unit_id,
          'ownerProviderRef':decode_json(execution.owner_provider_ref_bytes),'sourceRevision':execution.source_revision}
    from ..dispatch_method_run import resolve_method_run_package,resolve_historical_method_run_package
    package=(resolve_historical_method_run_package(uow,binding.run_id,step_id=binding.step_id)
             if method_runs is None else resolve_method_run_package(uow,binding.run_id,method_runs,step_id=binding.step_id))
    if (binding.scope!=submission.scope or binding.package_ref!=submission.package_ref
            or package.ref!=submission.package_ref
            or submission.authorization_refs!=(binding.approval_ref,)
            or binding.unit_ref_bytes!=canonical_bytes(unit)
            or binding.prompt_input_digest!=execution.prompt_input_digest
            or row['dispatch_fence']!=binding.fence
            or row['dispatch_phase'] not in {'completed','failed','unknown'}
            or row['result_blob_json']!=canonical_bytes(asdict(execution.captured_observation_ref)).decode('utf-8')):
        raise ApplicationError('SUBMISSION_DISPATCH_BINDING_MISMATCH')
    return binding

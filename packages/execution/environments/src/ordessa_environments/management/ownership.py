"""Explicit subject-owned resource operations, without leases or Agent objects.

This ledger owns resource request idempotency. Protocol interactions belong to
consumers; forwarding their bytes does not create another protocol ledger.
"""
from dataclasses import dataclass
from contextlib import contextmanager
import asyncio
import threading
import hashlib
import json
import uuid

from ..definitions.contracts import ProcessRequest
from ..definitions.errors import EnvironmentOperationUnknown, EnvironmentRefused, ProcessStartFailed


def _text(value, name):
    if (type(value) is not str or not 0 < len(value) <= 512
            or any(ord(c) < 32 for c in value)):
        raise EnvironmentRefused(name + ' must be a bounded stable reference')
    return value


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


@dataclass(frozen=True)
class OwnerScope:
    """Reference to an existing authority subject; never a new business entity."""
    kind: str
    ref: str

    def __post_init__(self):
        if self.kind not in ('principal', 'project'):
            raise EnvironmentRefused('ownerScope kind must identify an existing principal or project')
        _text(self.ref, 'ownerScope ref')

    @property
    def storage_key(self):
        return _json({'kind': self.kind, 'ref': self.ref})

    def to_dict(self):
        return {'kind': self.kind, 'ref': self.ref}


class EnvironmentUseOperations:
    """Resource lifecycle owner over one manager's durable store and live views.

    authorize(scope, action, target, invocation) must validate the real current
    caller and return True. Serialized scope/ref is not a grant. The callback
    must be short and must not retain a broad guard across this operation.
    """
    def __init__(self, manager, *, authorize):
        if not callable(authorize):
            raise EnvironmentRefused('explicit current resource authorization required')
        self.manager, self.authorize = manager, authorize
        with manager.store.transaction() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS environment_use_requests (
                owner_scope TEXT NOT NULL, request_id TEXT NOT NULL,
                operation_id TEXT NOT NULL UNIQUE, action TEXT NOT NULL,
                target TEXT NOT NULL, input_digest TEXT NOT NULL,
                use_id TEXT NOT NULL, state TEXT NOT NULL, result TEXT,
                PRIMARY KEY(owner_scope, request_id))''')

    def _authorize(self, scope, action, target, invocation):
        if type(scope) is not OwnerScope:
            raise EnvironmentRefused('typed existing ownerScope required')
        _text(target, 'resource target')
        if self.authorize(scope, action, target, invocation) is not True:
            raise EnvironmentRefused('current resource permission unavailable or refused')

    def _begin(self, scope, request_id, action, target, inputs, *, use_id=None):
        _text(request_id, 'requestId')
        digest = 'sha256:' + hashlib.sha256(_json(inputs).encode()).hexdigest()
        with self.manager.store.transaction() as db:
            row = db.execute('SELECT * FROM environment_use_requests WHERE owner_scope=? AND request_id=?',
                             (scope.storage_key, request_id)).fetchone()
            if row is not None:
                if (row['action'], row['target'], row['input_digest']) != (action, target, digest):
                    raise EnvironmentRefused('requestId conflicts with its fixed resource input')
                return dict(row), False
            operation_id = 'environment-operation/' + uuid.uuid4().hex
            use_id = use_id or 'environment-use/' + uuid.uuid4().hex
            db.execute('INSERT INTO environment_use_requests VALUES (?,?,?,?,?,?,?,?,NULL)',
                       (scope.storage_key, request_id, operation_id, action, target, digest, use_id, 'reserved'))
            return dict(db.execute('SELECT * FROM environment_use_requests WHERE operation_id=?',
                                   (operation_id,)).fetchone()), True

    @staticmethod
    def _replay(row):
        if row['result'] is not None:
            return json.loads(row['result'])
        # A reserved row may have crossed the effect boundary. Never rerun it.
        return {'operationRef': row['operation_id'], 'useIdentity': row['use_id'],
                'status': 'unknown', 'code': 'ENVIRONMENTS_EFFECT_UNKNOWN'}

    def _finish(self, row, status, **data):
        result = {'operationRef': row['operation_id'], 'useIdentity': row['use_id'],
                  'status': status, **data}
        with self.manager.store.transaction() as db:
            changed = db.execute('UPDATE environment_use_requests SET state=?, result=? '
                                 "WHERE operation_id=? AND state='reserved'",
                                 (status, _json(result), row['operation_id'])).rowcount
            if changed != 1:
                raise EnvironmentOperationUnknown('resource result publication requires inspection',
                                                  identity=row['use_id'])
        return result

    def _owned(self, scope, use_id):
        with self.manager.store.transaction() as db:
            row = db.execute('SELECT * FROM environment_uses WHERE identity=?', (use_id,)).fetchone()
            if row is None or row['owner_id'] != scope.storage_key:
                raise EnvironmentRefused('Use does not belong to this ownerScope')
            return dict(row)

    def acquire(self, environment_identity, scope, *, request_id, sharing, invocation):
        self._authorize(scope, 'acquire', environment_identity, invocation)
        if type(sharing) is not bool:
            raise EnvironmentRefused('explicit boolean sharing required')
        row, first = self._begin(scope, request_id, 'acquire', environment_identity,
                                 {'environment': environment_identity, 'sharing': sharing})
        if not first:
            return self._replay(row)
        try:
            use = self.manager.get(environment_identity)._acquire(
                scope.storage_key, sharing=sharing, use_id=row['use_id'])
            with self.manager._view_lock:
                self.manager._owned_use_handles[use.identity] = use
        except EnvironmentRefused:
            return self._finish(row, 'refused', code='ENVIRONMENTS_ACQUIRE_REFUSED')
        except Exception:
            return self._finish(row, 'unknown', code='ENVIRONMENTS_EFFECT_UNKNOWN')
        return self._finish(row, 'completed', ownerScope=scope.to_dict(), environmentIdentity=environment_identity)

    def inspect(self, use_id, scope, *, invocation):
        self._authorize(scope, 'observe', use_id, invocation)
        row = self._owned(scope, use_id)
        return {'useIdentity': use_id, 'ownerScope': scope.to_dict(),
                'environmentIdentity': row['environment_id'], 'generation': row['generation'],
                'phase': row['phase'], 'pendingEffects': row['pending'],
                'liveHandleAvailable': use_id in self.manager._owned_use_handles,
                'lease': False}

    def release(self, use_id, scope, *, request_id, invocation):
        self._authorize(scope, 'release', use_id, invocation)
        owned = self._owned(scope, use_id)
        row, first = self._begin(scope, request_id, 'release', use_id, {'useIdentity': use_id}, use_id=use_id)
        if not first:
            return self._replay(row)
        if owned['phase'] == 'released':
            return self._finish(row, 'completed', resourcePreserved=True, alreadyReleased=True)
        with self.manager._view_lock:
            use = self.manager._owned_use_handles.get(use_id)
        if use is None:
            # Host restart does not prove the original owner/process died.
            return self._finish(row, 'pending', code='ENVIRONMENTS_ORIGINAL_HANDLE_UNAVAILABLE')
        try:
            facts = use.release()
        except EnvironmentRefused:
            return self._finish(row, 'pending', code='ENVIRONMENTS_USE_BUSY')
        except Exception:
            return self._finish(row, 'unknown', code='ENVIRONMENTS_RELEASE_UNKNOWN')
        return self._finish(row, 'completed', resourcePreserved=True, receipt=facts)

    def launch(self, use_id, scope, request, *, request_id, invocation):
        self._authorize(scope, 'launch', use_id, invocation)
        self._owned(scope, use_id)
        if type(request) is not ProcessRequest:
            raise EnvironmentRefused('exact process request required')
        # Only a digest is persisted: argv/environment can contain private inputs.
        row, first = self._begin(scope, request_id, 'launch', use_id,
                                 {'argv': request.argv, 'cwd': request.cwd, 'env': dict(request.env)}, use_id=use_id)
        if not first:
            return self._replay(row)
        with self.manager._view_lock:
            use = self.manager._owned_use_handles.get(use_id)
        if use is None:
            return self._finish(row, 'refused', code='ENVIRONMENTS_ORIGINAL_HANDLE_UNAVAILABLE')
        try:
            # Revalidate at the actual resource dispatch, after durable reservation.
            self._authorize(scope, 'launch', use_id, invocation)
            process = use.execution.start(request)
            with self.manager._view_lock:
                self.manager._owned_process_handles[(use_id, process.identity)] = process
        except (EnvironmentRefused, ProcessStartFailed):
            return self._finish(row, 'refused', code='ENVIRONMENTS_LAUNCH_REFUSED')
        except Exception:
            return self._finish(row, 'unknown', code='ENVIRONMENTS_LAUNCH_UNKNOWN')
        return self._finish(row, 'completed', processIdentity=process.identity)

    def process(self, use_id, process_id, scope, *, invocation):
        if type(scope) is not OwnerScope:
            raise EnvironmentRefused('typed existing ownerScope required')
        self._owned(scope, use_id)
        _text(process_id, 'process identity')
        return RestrictedProcess(self, use_id, process_id, scope, invocation)

    def drop_exited_process(self, use_id, process_id):
        """Drop a one-shot process handle whose exit the caller already observed.

        This is not process-release and it produces no receipt: it is only valid
        after the same command observed the original exit (for example a
        one-shot exec, which owns no exported endpoint). Providers that cannot
        observe per-process state still must not retain the handle forever.
        """
        _text(process_id, 'process identity')
        with self.manager._view_lock:
            return self.manager._owned_process_handles.pop((use_id, process_id), None)

    def process_release(self, use_id, process_id, scope, *, request_id, invocation):
        """Release one ORIGINAL process transport only after observed exit.

        This is not termination and not Use release: a running/unknown process
        is refused before any transport mutation, and the Use keeps its own
        explicit release. The receipt claims no exit.
        """
        if type(scope) is not OwnerScope:
            raise EnvironmentRefused('typed existing ownerScope required')
        self._authorize(scope, 'detach', use_id, invocation)
        self._owned(scope, use_id)
        _text(process_id, 'process identity')
        _text(request_id, 'requestId')
        row, first = self._begin(scope, request_id, 'process-release', process_id,
                                 {'useIdentity': use_id, 'processIdentity': process_id},
                                 use_id=use_id)
        if not first:
            return self._replay(row)
        with self.manager._view_lock:
            process = self.manager._owned_process_handles.get((use_id, process_id))
        if process is None:
            return self._finish(row, 'refused', code='ENVIRONMENTS_ORIGINAL_HANDLE_UNAVAILABLE')
        try:
            self._authorize(scope, 'detach', use_id, invocation)
            observation = process.observe()
            if observation.state != 'exited':
                return self._finish(row, 'refused', code='ENVIRONMENTS_PROCESS_NOT_EXITED')
            facts = process.release()
            with self.manager._view_lock:
                self.manager._owned_process_handles.pop((use_id, process_id), None)
        except EnvironmentRefused:
            return self._finish(row, 'refused', code='ENVIRONMENTS_PROCESS_RELEASE_REFUSED')
        except Exception:
            return self._finish(row, 'unknown', code='ENVIRONMENTS_PROCESS_RELEASE_UNKNOWN')
        return self._finish(row, 'completed', resourcePreserved=True,
                            receipt=dict(facts), exitClaimed=False)

    def _process(self, view, action):
        self._authorize(view.scope, action, view.use_id, view.invocation)
        self._owned(view.scope, view.use_id)
        with self.manager._view_lock:
            process = self.manager._owned_process_handles.get((view.use_id, view.process_id))
        if process is None:
            raise EnvironmentRefused('original process endpoint unavailable; reattach unsupported')
        return process

    def _effect_guard(self, view, action, process, guard_effect):
        if not callable(guard_effect):
            raise EnvironmentRefused('mandatory synchronous lifecycle guard required')
        try:task=asyncio.current_task()
        except RuntimeError:task=None
        thread=threading.get_ident();state={'entered':False,'dispatched':False}
        @contextmanager
        def physical_cut():
            try:current=asyncio.current_task()
            except RuntimeError:current=None
            if state['entered'] or current is not task or threading.get_ident()!=thread:
                raise EnvironmentRefused('lifecycle physical cut is single-use and task/thread bound')
            state['entered']=True
            if self._process(view,action) is not process:
                raise EnvironmentRefused('original process identity changed')
            with guard_effect():
                if self._process(view,action) is not process:
                    raise EnvironmentRefused('original process identity changed')
                state['dispatched']=True
                yield
        return physical_cut,state

    async def terminate(self, view, *, request_id, force=False):
        return await self._terminate(view,request_id=request_id,force=force)

    async def terminate_guarded(self, view, *, request_id, force=False, guard_effect):
        if not callable(guard_effect):
            raise EnvironmentRefused('mandatory synchronous lifecycle guard required')
        return await self._terminate(view,request_id=request_id,force=force,guard_effect=guard_effect)

    async def _terminate(self, view, *, request_id, force=False, guard_effect=None):
        process=self._process(view,'terminate')
        if type(force) is not bool:raise EnvironmentRefused('explicit boolean force required')
        guarded=guard_effect is not None
        if guarded and (not callable(getattr(process,'cancel_guarded',None))
                        or not getattr(process,'guarded_termination_supported',True)):
            raise EnvironmentRefused('original provider has no guarded termination')
        row,first=self._begin(view.scope,request_id,'terminate',view.process_id,
            {'useIdentity':view.use_id,'force':force},use_id=view.use_id)
        if not first:return self._replay(row)
        state={'dispatched':False}
        try:
            self._authorize(view.scope,'terminate',view.use_id,view.invocation)
            if guarded:
                cut,state=self._effect_guard(view,'terminate',process,guard_effect)
                result=await process.cancel_guarded(force=force,guard_effect=cut)
                if not state['dispatched']:raise EnvironmentRefused('provider did not enter physical termination cut')
            else:
                state['dispatched']=True
                result=await process.cancel(force=force)
        except BaseException as error:
            result=self._finish(row,'unknown' if state['dispatched'] else 'refused',
                code='ENVIRONMENTS_TERMINATE_UNKNOWN' if state['dispatched'] else 'ENVIRONMENTS_TERMINATE_REFUSED')
            if isinstance(error,(asyncio.CancelledError,KeyboardInterrupt,SystemExit)):raise
            return result
        status='unknown' if result.outcome=='unknown' else 'completed'
        return self._finish(row,status,cancellation=result.outcome,processState=result.observation.state)

    def detach(self, view, *, request_id):
        return self._detach(view,request_id=request_id)

    def detach_guarded(self, view, *, request_id, guard_effect):
        if not callable(guard_effect):
            raise EnvironmentRefused('mandatory synchronous lifecycle guard required')
        return self._detach(view,request_id=request_id,guard_effect=guard_effect)

    def _detach(self, view, *, request_id, guard_effect=None):
        process=self._process(view,'detach');guarded=guard_effect is not None
        if guarded and (not callable(getattr(process,'release_guarded',None))
                        or not getattr(process,'guarded_detach_supported',True)):
            raise EnvironmentRefused('original provider has no guarded detach')
        row,first=self._begin(view.scope,request_id,'detach',view.process_id,
            {'useIdentity':view.use_id},use_id=view.use_id)
        if not first:return self._replay(row)
        state={'dispatched':False}
        try:
            self._authorize(view.scope,'detach',view.use_id,view.invocation)
            if guarded:
                cut,state=self._effect_guard(view,'detach',process,guard_effect)
                facts=process.release_guarded(guard_effect=cut)
                if not state['dispatched']:raise EnvironmentRefused('provider did not enter physical detach cut')
            else:
                state['dispatched']=True;facts=process.release()
        except BaseException as error:
            result=self._finish(row,'unknown' if state['dispatched'] else 'refused',
                code='ENVIRONMENTS_DETACH_UNKNOWN' if state['dispatched'] else 'ENVIRONMENTS_DETACH_REFUSED')
            if isinstance(error,(asyncio.CancelledError,KeyboardInterrupt,SystemExit)):raise
            return result
        return self._finish(row,'completed',receipt=dict(facts),exitClaimed=False)


class RestrictedProcess:
    """No raw handles. Every operation independently checks current permission."""
    def __init__(self, operations, use_id, process_id, scope, invocation):
        self._operations = operations
        self.use_id, self.process_id = use_id, process_id
        self.scope, self.invocation = scope, invocation

    def observe(self):
        return self._operations._process(self, 'observe').observe()

    async def wait_exit(self, *, timeout=None):
        return await self._operations._process(self, 'observe').wait_exit(timeout=timeout)

    async def read_stdout(self, max_bytes=65536, *, timeout=None):
        return await self._operations._process(self, 'communicate').read_stdout(max_bytes, timeout=timeout)

    async def read_stderr(self, max_bytes=65536, *, timeout=None):
        return await self._operations._process(self, 'communicate').read_stderr(max_bytes, timeout=timeout)

    async def write_stdin(self, data, *, timeout=None):
        return await self._operations._process(self, 'communicate').write_stdin(data, timeout=timeout)

    async def close_stdin(self):
        return await self._operations._process(self, 'communicate').close_stdin()

    async def terminate(self, *, request_id, force=False):
        return await self._operations.terminate(self, request_id=request_id, force=force)

    def detach(self, *, request_id):
        return self._operations.detach(self, request_id=request_id)

    async def terminate_guarded(self, *, request_id, force=False, guard_effect):
        return await self._operations.terminate_guarded(self,request_id=request_id,force=force,guard_effect=guard_effect)

    def detach_guarded(self, *, request_id, guard_effect):
        return self._operations.detach_guarded(self,request_id=request_id,guard_effect=guard_effect)

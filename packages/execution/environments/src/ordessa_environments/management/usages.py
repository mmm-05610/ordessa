"""Use handles with persistent generation gates and explicit process ownership."""
from contextlib import contextmanager
from threading import RLock

from ..definitions.errors import EnvironmentOperationUnknown, EnvironmentRefused


class _GuardedView:
    def __init__(self, use, target, validate=None, effect_methods=None):
        self._use, self._target = use, target
        self._validate = validate
        self._effect_methods = effect_methods

    def _check(self):
        self._use._check()
        if self._validate is not None:
            self._validate()

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        self._check()
        value = getattr(self._target, name)
        if not callable(value):
            return value
        def call(*args, **kwargs):
            if self._effect_methods is None or name in self._effect_methods:
                with self._use._effect():
                    self._check()
                    return value(*args, **kwargs)
            try:
                self._check()
                result = value(*args, **kwargs)
                self._check()
                return result
            except EnvironmentOperationUnknown:
                self._use._store.fence_use(self._use.identity)
                raise
        return call


class _ProcessView:
    """Sole managed ProcessHandle; no raw pipe/Popen forwarding."""
    def __init__(self,use,process):
        self._use,self._target=use,process
        self._released=False
        self._release_receipt=None

    @property
    def identity(self):return self._target.identity

    @property
    def generation(self):return self._use.generation

    def _check(self,*,io=False):
        self._use._store.check_use(self._use.identity,allow_unknown=not io)
        if io and self._released:raise EnvironmentRefused('process transport was released')

    async def _call(self,name,*args,native=False,recovery=False,**kwargs):
        self._check(io=not recovery)
        unknown=False
        if native:self._use._store.begin_use_effect(self._use.identity,allow_unknown=recovery)
        try:
            result=await getattr(self._target,name)(*args,**kwargs)
            if getattr(result,'outcome',None)=='unknown' or getattr(result,'state',None)=='unknown':
                unknown=True
            self._check(io=not recovery)
            return result
        except EnvironmentOperationUnknown:
            unknown=True
            raise
        finally:
            if native:self._use._store.end_use_effect(self._use.identity,unknown=unknown)
            elif unknown:self._use._store.fence_use(self._use.identity)

    async def read_stdout(self,max_bytes=65536,*,timeout=None):
        return await self._call('read_stdout',max_bytes,timeout=timeout)

    async def read_stderr(self,max_bytes=65536,*,timeout=None):
        return await self._call('read_stderr',max_bytes,timeout=timeout)

    async def write_stdin(self,data,*,timeout=None):
        return await self._call('write_stdin',data,timeout=timeout,native=True)

    @property
    def guarded_write_supported(self):
        self._check(io=True)
        return callable(getattr(self._target, 'write_stdin_guarded', None))

    async def write_stdin_guarded(self,data,*,timeout=None,write_guard):
        if not self.guarded_write_supported:
            raise EnvironmentRefused('provider physical guarded writer unavailable')
        return await self._call('write_stdin_guarded',data,timeout=timeout,
                                write_guard=write_guard,native=True)

    async def close_stdin(self):
        return await self._call('close_stdin',native=True)

    def observe(self):
        self._check()
        return self._target.observe()

    async def wait_exit(self,*,timeout=None):
        return await self._call('wait_exit',timeout=timeout,recovery=True)

    async def cancel(self,*,force=False):
        return await self._call('cancel',force=force,native=True,recovery=True)

    @property
    def guarded_termination_supported(self):
        self._check()
        return callable(getattr(self._target,'cancel_guarded',None))

    @property
    def guarded_detach_supported(self):
        self._check()
        return callable(getattr(self._target,'release_guarded',None))

    async def cancel_guarded(self,*,force=False,guard_effect):
        if not callable(guard_effect) or not callable(getattr(self._target,'cancel_guarded',None)):
            raise EnvironmentRefused('provider physical guarded termination unavailable')
        return await self._call('cancel_guarded',force=force,guard_effect=guard_effect,
                                native=True,recovery=True)

    def release_guarded(self,*,guard_effect):
        if not callable(guard_effect) or not callable(getattr(self._target,'release_guarded',None)):
            raise EnvironmentRefused('provider physical guarded detach unavailable')
        return self._release(guard_effect=guard_effect)

    def release(self):
        return self._release()

    def _release(self,*,guard_effect=None):
        if self._release_receipt is not None:
            if guard_effect is not None:
                # A separate request still crosses its own authority/claim cut;
                # the cached receipt cannot authorize or imply a fresh mutation.
                with guard_effect():
                    self._check()
                    return dict(self._release_receipt)
            return dict(self._release_receipt)
        self._check()
        self._use._store.begin_use_effect(self._use.identity,allow_unknown=True)
        unknown=False
        try:
            facts=(self._target.release() if guard_effect is None else
                   self._target.release_guarded(guard_effect=guard_effect))
            self._released=True
            unknown=self._target.observe().state=='unknown'
            self._release_receipt=dict(facts)
            return dict(facts)
        except EnvironmentOperationUnknown:
            unknown=True
            raise
        finally:
            self._use._store.end_use_effect(self._use.identity,unknown=unknown)


class _ExecutionView:
    def __init__(self, use):
        self._use = use

    def start(self, request):
        with self._use._effect():
            process = self._use._backend.execution.start(request)
            view = _ProcessView(self._use, process)
            self._use._processes.append(view)
            return view


class EnvironmentUse:
    """A recorded use, not a timed lease or an isolation boundary.

    Creator explicitly releases every process first. Use release never stops,
    deletes, guesses exit or removes files. A cold manager cannot fabricate the
    live handle required to release a previous owner's recorded use.
    """
    def __init__(self, store, environment_id, identity, generation, backend, capabilities):
        self._store, self.environment_id = store, environment_id
        self._identity, self._generation = identity, generation
        self._backend, self._capabilities = backend, capabilities
        self._lock = RLock()
        self._processes = []
        self._untracked_unknown = False
        self._release_receipt = None
        self._files, self._execution = _GuardedView(self, backend.files), _ExecutionView(self)

    @property
    def identity(self):
        return self._identity

    @property
    def generation(self):
        return self._generation

    @property
    def capabilities(self):
        self._check()
        return self._capabilities

    @property
    def files(self):
        self._check()
        return self._files

    @property
    def execution(self):
        self._check()
        return self._execution

    def _check(self):
        self._store.check_use(self.identity)

    def check(self, environment_identity, generation, *, allow_unknown=False):
        """Publicly revalidate this exact live use against its fixed instance.

        Cleanup may inspect an existing unknown use, but this check never
        manufactures a handle or changes the use's recorded state.
        """
        if (type(allow_unknown) is not bool
                or environment_identity != self.environment_id
                or type(generation) is not int or generation != self.generation):
            raise EnvironmentRefused('Environment Use identity or generation differs')
        self._store.check_use(self.identity, allow_unknown=allow_unknown)
        return True

    @contextmanager
    def _effect(self):
        with self._lock:
            self._store.begin_use_effect(self.identity)
            unknown = False
            try:
                yield
            except EnvironmentOperationUnknown:
                unknown = True
                self._untracked_unknown = True
                raise
            finally:
                self._store.end_use_effect(self.identity, unknown=unknown)

    def release(self):
        with self._lock:
            if self._release_receipt is not None:return dict(self._release_receipt)
            self._store.check_use(self.identity,allow_unknown=True)
            if any(not process._released or process._target.observe().state!='exited' for process in self._processes):
                raise EnvironmentRefused('creator must confirm process exit and explicitly release each process transport')
            if self._untracked_unknown:
                raise EnvironmentRefused('untracked file/helper effect still has unknown outcome')
            # Atomic release admission across managers, also covering awaited
            # native writes. Do not hold a threading lock across an await.
            # Only this existing live Use's original process handles may
            # discharge a process-only hold, and only after actual exit. Cold
            # manager rows never reconstruct those handles or facts.
            self._store.begin_use_release(self.identity,allow_unknown=bool(self._processes))
            try:
                facts=self._backend.release()
            except Exception as error:
                self._store.finish_use_release(self.identity,success=False,unknown=isinstance(error,EnvironmentOperationUnknown))
                raise
            self._store.finish_use_release(self.identity,success=True)
            self._release_receipt={'useIdentity':self.identity,'environmentIdentity':self.environment_id,
                'generation':self.generation,'resourcePreserved':True,'providerFacts':dict(facts)}
            return dict(self._release_receipt)

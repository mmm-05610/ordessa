"""Single-use process input on the original fixed Unit and borrowed Environment.

The host supplies an input source; Units owns exact prepared-launch admission.
No credential persistence, independent spawn, or authorization is created here.
"""
from collections.abc import Mapping
import re
from threading import RLock
from ordessa_environments import EnvironmentRefused, EnvironmentOperationUnknown, ProcessRequest
from ordessa_units.management import UnitInstance

class _TransientEnvironment(Mapping):
    def __init__(self, baseline, name, secret):
        self._baseline, self._name, self._secret = baseline, name, secret
    def __iter__(self):
        return iter((*self._baseline, self._name))
    def __len__(self):
        return len(self._baseline) + 1
    def __getitem__(self, key):
        return self._secret.decode('ascii') if key == self._name else self._baseline[key]
    def __repr__(self):
        return '<temporary-process-environment values=redacted>'


class UnitProcessInput:
    """A product input binding, never an authorization Grant or a secret store."""
    def __init__(self, *, instance, agent_id, sharing, source, admitted_launch, check_start,
                 variable_name='OPENCODE_API_KEY'):
        if (instance.snapshot.provider_id != 'local' or type(sharing) is not bool
                or not isinstance(agent_id, str) or not agent_id
                or not isinstance(variable_name, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', variable_name)
                or not callable(admitted_launch) or not callable(check_start)
                or not callable(getattr(source, 'read', None))):
            raise EnvironmentRefused('Explicit local process capability binding required')
        self._instance, self._agent_id, self._sharing = instance, agent_id, sharing
        self._source, self._launch, self._check = source, admitted_launch, check_start
        self._name = variable_name
        self._lock, self._consumed, self._closed, self._use = RLock(), False, False, None

    def __repr__(self):
        return '<UnitProcessInput single-use local values=redacted>'

    @property
    def identity(self):
        return self._instance.identity

    @property
    def snapshot(self):
        return self._instance.snapshot

    def acquire(self, owner_id, *, sharing):
        with self._lock:
            if self._closed or self._use is not None or owner_id != self._agent_id or sharing is not self._sharing:
                raise EnvironmentRefused('Process capability acquisition differs from fixed Unit')
            use = self._instance.acquire(owner_id, sharing=sharing)
            self._use = _CapabilityUse(self, use)
            return self._use

    def close(self):
        with self._lock:
            self._closed = True
            self._source = None

    def _start(self, use, request):
        with self._lock:
            if self._closed or self._consumed or self._use is not use:
                raise EnvironmentRefused('Process capability unavailable; never repeat an unknown launch')
            expected = self._launch()
            if (type(request) is not ProcessRequest or type(expected) is not ProcessRequest
                    or request.argv != expected.argv or request.cwd != expected.cwd
                    or dict(request.env) != dict(expected.env) or self._name in request.env):
                raise EnvironmentRefused('Process capability does not match exact admitted launch')
            # Original Unit/start authority remains the permission authority.
            self._check()
            self._consumed = True  # Even a lost spawn receipt must never replay.
            secret = self._source.read()
            try:
                if type(secret) is not bytearray or not secret or any(c < 33 or c > 126 for c in secret):
                    raise EnvironmentRefused('Temporary model input is invalid')
                transient = _TransientEnvironment(dict(request.env), self._name, secret)
                enriched = ProcessRequest(request.argv, request.cwd, transient)
                self._check()  # Recheck immediately before existing guarded Use.spawn.
                try:
                    return use._original.execution.start(enriched)
                except EnvironmentRefused:
                    raise EnvironmentRefused('Bound process start was refused') from None
                except Exception:
                    # Do not forward a provider exception containing request
                    # environment values. Retain uncertainty, never resend.
                    raise EnvironmentOperationUnknown('Bound process start outcome requires original Unit reconciliation',
                        identity=self.identity) from None
            finally:
                if type(secret) is bytearray:
                    secret[:] = b'\0' * len(secret)
                self._source = None


class _CapabilityUse:
    def __init__(self, capability, original):
        self._capability, self._original = capability, original
    @property
    def identity(self): return self._original.identity
    @property
    def environment_id(self): return self._original.environment_id
    @property
    def generation(self): return self._original.generation
    def check(self, environment_identity, generation, *, allow_unknown=False):
        return self._original.check(environment_identity, generation, allow_unknown=allow_unknown)
    @property
    def capabilities(self): return self._original.capabilities
    @property
    def files(self): return self._original.files
    @property
    def execution(self): return self
    def start(self, request): return self._capability._start(self, request)
    def release(self):
        self._capability.close()
        return self._original.release()


class UnitProcessInputBinding:
    def __init__(self, *, instance, agent_id, sharing, input_source, variable_name='OPENCODE_API_KEY'):
        self._unit = self._ref = self._context = None
        self.capability = UnitProcessInput(instance=instance, agent_id=agent_id, sharing=sharing,
            source=input_source, admitted_launch=self._admitted_launch,
            check_start=self._check_start, variable_name=variable_name)
        self._agent_id = agent_id

    def attach(self, unit):
        if (self._unit is not None or type(unit) is not UnitInstance or unit.agent_id != self._agent_id
                or unit.channel_factory.instance is not self.capability):
            raise EnvironmentRefused('Exact fixed Unit binding required')
        self._unit = unit

    def fix_start(self, prepared, original_context):
        if self._context is not None or self._unit is None or self._unit.prepared_agent is None:
            raise EnvironmentRefused('Original prepared Unit and one fixed start invocation required')
        self._ref = prepared['unitRef']
        self._context = original_context

    def _admitted_launch(self):
        if self._unit is None or self._unit.prepared_agent is None or self._context is None:
            raise EnvironmentRefused('Fixed materialized launch is unavailable')
        spec = self._unit.channel_factory.prepared_agent.harness.launch_spec
        return ProcessRequest.build(spec.argv, cwd=spec.cwd, env=spec.env)

    def _check_start(self):
        if self._unit is None or self._ref is None or self._context is None:
            raise EnvironmentRefused('Original start invocation is unavailable')
        self._unit._current_start(self._unit._unit_record(self._ref), self._context)

    def close(self):
        self.capability.close()
        self._context = None


__all__ = ["UnitProcessInput", "UnitProcessInputBinding"]

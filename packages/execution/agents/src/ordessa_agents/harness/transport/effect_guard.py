"""Trusted per-operation admission, held through one bounded async byte write.

The deployment supplies a cooperative async context manager, sharing its real
revoke writer's synchronization. This carrier grants nothing on its own and
cannot authenticate an empty/test guard as production permission.
"""
import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
import hashlib
import json
import math

from ordessa_infrastructure.encoding.immutable_json import safe_json, sealed_mapping

# Preserve the finite native prompt capacity at the immutable write seam. This
# carrier grants no capacity: the selected Unit Records owner preflights it.
_MAX_PROMPT_BYTES = 589824


class EffectWriteRefused(RuntimeError):
    code = 'EFFECT_WRITE_REFUSED'


@dataclass(frozen=True)
class EffectWriteGuard:
    unit_ref: object
    operation_ref: str
    input_digest: str
    params: object
    acquire: object
    timeout: float = 2.0
    release_timeout: float = 1.0

    def __post_init__(self):
        if (not callable(self.acquire) or type(self.operation_ref) is not str
                or not self.operation_ref or len(self.operation_ref) > 256
                or any(ord(c) < 32 for c in self.operation_ref)
                or type(self.input_digest) is not str or len(self.input_digest) != 71
                or not self.input_digest.startswith('sha256:')
                or any(c not in '0123456789abcdef' for c in self.input_digest[7:])):
            raise EffectWriteRefused('fixed operation write guard required')
        for value in (self.timeout, self.release_timeout):
            if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 10:
                raise EffectWriteRefused('bounded write and release budgets required')
        if set(self.unit_ref) != {'environmentNamespace', 'unitId', 'ownerProviderRef', 'sourceRevision'}:
            raise EffectWriteRefused('complete Unit write binding required')
        object.__setattr__(self, 'unit_ref', sealed_mapping(self.unit_ref))
        object.__setattr__(self, 'params', sealed_mapping(self.params, max_bytes=_MAX_PROMPT_BYTES))

    def matches(self, unit_ref, operation_ref, input_digest, params):
        return (safe_json(unit_ref) == safe_json(self.unit_ref) and operation_ref == self.operation_ref
                and input_digest == self.input_digest
                and safe_json(params, max_bytes=_MAX_PROMPT_BYTES)
                    == safe_json(self.params, max_bytes=_MAX_PROMPT_BYTES))

    @asynccontextmanager
    async def hold(self, frame):
        raw = json.loads(frame)
        if (raw.get('method') != 'session/prompt'
                or safe_json(raw.get('params'), max_bytes=_MAX_PROMPT_BYTES)
                    != safe_json(self.params, max_bytes=_MAX_PROMPT_BYTES)):
            raise EffectWriteRefused('actual frame differs from fixed operation')
        identity = sealed_mapping({'unitRef': self.unit_ref, 'operationRef': self.operation_ref,
            'inputDigest': self.input_digest, 'requestId': raw['id'],
            'frameDigest': 'sha256:' + hashlib.sha256(frame).hexdigest()})
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self.timeout
        manager = self.acquire(identity, deadline)
        if not callable(getattr(manager, '__aenter__', None)) or not callable(getattr(manager, '__aexit__', None)):
            raise EffectWriteRefused('cooperative async write guard required')
        entered = False
        primary = None
        try:
            # Acquisition and byte write share ONE deadline. __aenter__ must
            # clean up its own partial acquisition if cancelled or refused.
            await asyncio.wait_for(manager.__aenter__(), max(0, deadline-loop.time()))
            entered = True
            yield deadline
        except BaseException as error:
            primary = error
            raise
        finally:
            if entered:
                # Cleanup must not be skipped by cancellation of the send.
                # The provider must release cooperatively within this budget;
                # errors/timeout are propagated, never a success receipt.
                cleanup = asyncio.create_task(asyncio.wait_for(manager.__aexit__(
                    type(primary) if primary else None, primary,
                    primary.__traceback__ if primary else None), self.release_timeout))
                cancelled = False
                while not cleanup.done():
                    try:
                        await asyncio.shield(cleanup)
                    except asyncio.CancelledError:
                        cancelled = True
                cleanup.result()  # ignore suppression: an error must stay an error
                if cancelled and primary is None:
                    raise asyncio.CancelledError

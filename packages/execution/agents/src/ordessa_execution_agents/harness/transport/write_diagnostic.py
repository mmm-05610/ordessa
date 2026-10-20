"""Facts observed at this transport's write seam; never provider completion."""
from dataclasses import asdict, dataclass, replace
import hashlib

from ordessa_infrastructure.encoding.immutable_json import safe_json


_ATTRIBUTE = '_ordessa_native_write_boundary'


@dataclass(frozen=True)
class _NativeWriteBoundary:
    contract: str
    phase: str
    frame_bytes: int
    before_write: str
    write_stdin: str
    acknowledged_bytes: int | None
    operation_ref: str | None
    input_digest: str | None
    unit_ref_digest: str | None
    frame_digest: str


class NativeWriteProgress:
    def __init__(self, data, guard, observer=None):
        if observer is not None and not callable(observer):
            raise TypeError('Native write diagnostic observer must be callable')
        self.observer = observer
        self.phase = 'writer_admission'
        self.frame_bytes = len(data)
        self.before_write = 'not_entered'
        self.write_stdin = 'not_entered'
        self.acknowledged_bytes = None
        self.operation_ref = None if guard is None else guard.operation_ref
        self.input_digest = None if guard is None else guard.input_digest
        self.unit_ref_digest = (None if guard is None else 'sha256:' + hashlib.sha256(
            safe_json(guard.unit_ref).encode()).hexdigest())
        self.frame_digest = 'sha256:' + hashlib.sha256(data).hexdigest()

    def snapshot(self):
        return _NativeWriteBoundary('native-write-boundary/1', self.phase,
            self.frame_bytes, self.before_write, self.write_stdin,
            self.acknowledged_bytes, self.operation_ref, self.input_digest,
            self.unit_ref_digest, self.frame_digest)

    def mark(self, **values):
        for name, value in values.items():
            setattr(self, name, value)
        if self.observer is not None:
            self.observer(self.snapshot())

    def attach(self, error):
        # Preserve the original exception class and chain. No message, args,
        # payload, stderr, paths or local variables are copied into evidence.
        try:
            BaseException.__setattr__(error, _ATTRIBUTE, self.snapshot())
        except (AttributeError, TypeError):
            # A non-extensible exception remains the original refusal. Its
            # consumer must report boundary evidence as unavailable.
            pass


def attach_native_write_failure(error, snapshot, *, response_wait=False):
    """Attach this request's opaque transport snapshot after a response failure.

    No plain mapping can manufacture this evidence. A full local write return
    is only an acknowledgment from ProcessHandle, never provider completion.
    """
    if not isinstance(error, BaseException) or type(snapshot) is not _NativeWriteBoundary:
        return False
    if native_write_failure(error) is not None:
        return True
    if (response_wait and snapshot.write_stdin == 'returned'
            and snapshot.acknowledged_bytes == snapshot.frame_bytes):
        snapshot = replace(snapshot, phase='response_wait')
    try:
        BaseException.__setattr__(error, _ATTRIBUTE, snapshot)
    except (AttributeError, TypeError):
        return False
    return True


def native_write_failure(error):
    """Return a detached trusted seam snapshot from a bounded exception chain.

    An absent snapshot says nothing about whether a write happened. A write
    call that raised also says nothing about how many bytes its peer received.
    """
    seen = set()
    for _ in range(8):
        if not isinstance(error, BaseException) or id(error) in seen:
            break
        seen.add(id(error))
        try:
            value = BaseException.__getattribute__(error, _ATTRIBUTE)
        except (AttributeError, TypeError):
            value = None
        if type(value) is _NativeWriteBoundary:
            return asdict(value)
        cause = BaseException.__getattribute__(error, '__cause__')
        error = cause if cause is not None else BaseException.__getattribute__(error, '__context__')
    return None

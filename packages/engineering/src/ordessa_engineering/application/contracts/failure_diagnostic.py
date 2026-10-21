"""Bounded dispatch failure facts, excluding exception messages and payloads."""
from dataclasses import dataclass
import re

from ordessa_infrastructure.encoding import canonical_bytes, decode_json


FAILURE_MEDIA_TYPE = 'application/vnd.ordessa.dispatch-failure+json'
# Closed stage set. `pre_send` covers a refusal after the debit COMMIT but
# before any native frame was authorized; `reconcile` covers a cold read that
# could not confirm the original attempt. Neither stage asserts a write.
_STAGES = {'pre_send', 'handoff_enter', 'native_send', 'handoff_exit', 'reconcile'}
_TOKEN = re.compile(r'[A-Za-z_][A-Za-z0-9_.<>]{0,95}\Z')
_CODE = re.compile(r'[A-Z][A-Z0-9_]{0,95}\Z')
_DIGEST = re.compile(r'sha256:[0-9a-f]{64}\Z')


def _token(value):
    return value if type(value) is str and _TOKEN.fullmatch(value) else 'redacted'


def _chain(error):
    result, seen = [], set()
    relation = 'raised'
    while isinstance(error, BaseException) and id(error) not in seen and len(result) < 6:
        seen.add(id(error))
        cls = type(error)
        code = None
        if cls.__module__.startswith(('ordessa_', 'ordessa_server_plugin_api')):
            attributes = BaseException.__getattribute__(error, '__dict__')
            candidate = attributes.get('code', vars(cls).get('code'))
            if type(candidate) is str and _CODE.fullmatch(candidate):
                code = candidate
        frames = []
        trace = BaseException.__getattribute__(error, '__traceback__')
        while trace is not None:
            frame = trace.tb_frame
            frames.append({'module': _token(frame.f_globals.get('__name__')),
                'function': _token(frame.f_code.co_name), 'line': trace.tb_lineno})
            frames = frames[-3:]
            trace = trace.tb_next
        result.append({'relation': relation, 'type': _token(cls.__module__ + '.' + cls.__qualname__),
                       'code': code, 'frames': frames})
        cause = BaseException.__getattribute__(error, '__cause__')
        relation = 'cause' if cause is not None else 'context'
        error = (cause if cause is not None else None
                 if BaseException.__getattribute__(error, '__suppress_context__')
                 else BaseException.__getattribute__(error, '__context__'))
    return {'exception_chain': result, 'chain_truncated': error is not None}


def _validate_chain(value):
    if (type(value) is not dict or set(value) != {'exception_chain', 'chain_truncated'}
            or type(value['chain_truncated']) is not bool
            or type(value['exception_chain']) is not list
            or not 1 <= len(value['exception_chain']) <= 6):
        raise ValueError('Invalid failure diagnostic chain')
    for node in value['exception_chain']:
        if (type(node) is not dict or set(node) != {'relation', 'type', 'code', 'frames'}
                or node['relation'] not in {'raised', 'cause', 'context'}
                or type(node['type']) is not str or not _TOKEN.fullmatch(node['type'])
                or node['code'] is not None and (type(node['code']) is not str or not _CODE.fullmatch(node['code']))
                or type(node['frames']) is not list or len(node['frames']) > 3):
            raise ValueError('Invalid failure diagnostic node')
        for frame in node['frames']:
            if (type(frame) is not dict or set(frame) != {'module', 'function', 'line'}
                    or any(type(frame[name]) is not str or not _TOKEN.fullmatch(frame[name])
                           for name in ('module', 'function'))
                    or type(frame['line']) is not int or not 0 < frame['line'] < 10000000):
                raise ValueError('Invalid failure diagnostic frame')


def _validate_native(value):
    if value is None:
        return
    fields = {'contract', 'phase', 'frame_bytes', 'before_write', 'write_stdin',
        'acknowledged_bytes', 'operation_ref', 'input_digest', 'unit_ref_digest', 'frame_digest'}
    if (type(value) is not dict or set(value) != fields
            or value['contract'] != 'native-write-boundary/1'
            or value['phase'] not in {'effect_guard_acquire', 'writer_lock_acquire', 'writer_admission',
                                    'before_write', 'write_stdin', 'write_acknowledged', 'guard_release',
                                    'response_wait'}
            or type(value['frame_bytes']) is not int or not 0 <= value['frame_bytes'] <= 16 * 1024 * 1024
            or value['before_write'] not in {'not_entered', 'entered', 'completed'}
            or value['write_stdin'] not in {'not_entered', 'entered', 'returned'}
            or value['acknowledged_bytes'] is not None and (type(value['acknowledged_bytes']) is not int
                or not 0 <= value['acknowledged_bytes'] <= value['frame_bytes'])
            or type(value['frame_digest']) is not str or not _DIGEST.fullmatch(value['frame_digest'])):
        raise ValueError('Invalid native write diagnostic')
    for name in ('input_digest', 'unit_ref_digest'):
        if value[name] is not None and (type(value[name]) is not str or not _DIGEST.fullmatch(value[name])):
            raise ValueError('Invalid native write binding')
    operation = value['operation_ref']
    if operation is not None and (type(operation) is not str or not 1 <= len(operation) <= 256
            or any(ord(char) < 32 for char in operation)):
        raise ValueError('Invalid native operation binding')
    if value['acknowledged_bytes'] is not None and value['write_stdin'] != 'returned':
        raise ValueError('Invalid native write acknowledgment')


@dataclass(frozen=True)
class FailureDiagnostic:
    """Validated immutable bytes; callers cannot add arbitrary log fields."""
    encoded: bytes

    def __post_init__(self):
        if type(self.encoded) is not bytes or len(self.encoded) > 16384:
            raise ValueError('Failure diagnostic exceeds bounded contract')
        value = decode_json(self.encoded)
        if (type(value) is not dict or set(value) != {'contract', 'stage', 'exception_chain',
                'chain_truncated', 'native_write', 'recording_failure'}
                or value['contract'] != 'engineering-dispatch-failure/1' or value['stage'] not in _STAGES):
            raise ValueError('Invalid failure diagnostic contract')
        _validate_chain({key: value[key] for key in ('exception_chain', 'chain_truncated')})
        _validate_native(value['native_write'])
        if value['recording_failure'] is not None:
            _validate_chain(value['recording_failure'])
        if canonical_bytes(value) != self.encoded:
            raise ValueError('Noncanonical failure diagnostic')

    @classmethod
    def capture(cls, error, stage, native_write=None):
        return cls.from_record({'contract': 'engineering-dispatch-failure/1', 'stage': stage,
            **_chain(error), 'native_write': native_write, 'recording_failure': None})

    @classmethod
    def from_record(cls, value):
        return cls(canonical_bytes(value))

    def to_dict(self):
        return decode_json(self.encoded)

    def with_recording_failure(self, error):
        """Append secondary failures; each ``raised`` starts a separate chain.

        Nodes retain occurrence order within one bounded array. This is not
        an assertion that one independent recording failure caused another.
        """
        value = self.to_dict()
        additional = _chain(error)
        previous = value['recording_failure']
        if previous is not None:
            # Keep failures in occurrence order; a later storage refusal must
            # not erase the failure that prevented native-boundary capture.
            nodes = previous['exception_chain'] + additional['exception_chain']
            additional = {'exception_chain': nodes[:6], 'chain_truncated': (
                previous['chain_truncated'] or additional['chain_truncated'] or len(nodes) > 6)}
        return self.from_record(dict(value, recording_failure=additional))

"""Reply capture for an ACP reverse request handled by an injected callback."""

from contextvars import ContextVar
from contextlib import contextmanager

_reply = ContextVar("acp_callback_reply", default=None)


@contextmanager
def capture_sdk_reply(request_id):
    """Capture a callback outcome for the matching original request id."""
    captured = {}
    token = _reply.set((request_id, captured))
    try:
        yield captured
    finally:
        _reply.reset(token)


def reply_result(request_id, result):
    captured = _matching_reply(request_id)
    captured["result"] = result


def reply_error(request_id, *, code, message, data=None):
    captured = _matching_reply(request_id)
    captured["error"] = {"code": code, "message": message, "data": data}


def _matching_reply(request_id):
    active = _reply.get()
    if active is None or active[0] != request_id:
        raise RuntimeError("Reply requires the original SDK callback request")
    return active[1]

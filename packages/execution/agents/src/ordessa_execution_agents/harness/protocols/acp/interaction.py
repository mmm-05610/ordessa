"""Dispatch ACP reverse requests to a caller-owned callback."""

from acp.exceptions import RequestError
from ordessa_infrastructure.process.framing import Message

from .callbacks import capture_sdk_reply


def invoke_bound_callback(raw_request, callback):
    """Invoke the injected callback once and return its captured SDK result."""
    if not callable(callback):
        raise RequestError(-32601, "Bound ACP callback unavailable")
    request_id = raw_request.get("id")
    if request_id is None:
        raise RequestError(-32600, "ACP reverse request has no id")
    with capture_sdk_reply(request_id) as captured:
        callback(Message(raw=raw_request))
    if "error" in captured:
        error = captured["error"]
        raise RequestError(error["code"], error["message"], error.get("data"))
    if "result" not in captured:
        raise RequestError(-32603, "Original callback outcome unknown; no replay")
    return captured["result"]

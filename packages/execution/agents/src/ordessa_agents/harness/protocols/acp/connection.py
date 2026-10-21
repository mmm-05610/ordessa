"""Official ACP SDK connection construction for an injected byte transport."""

from acp.connection import Connection


def open_sdk_connection(handler, transport, observer):
    """Bind protocol dispatch, transport IO and protocol observation once."""
    if not callable(handler) or not callable(observer):
        raise TypeError("ACP handler and observer must be callable")
    if not callable(getattr(transport, "send", None)) or not callable(
        getattr(transport, "receive", None)
    ):
        raise TypeError("ACP transport must provide send and receive")
    return Connection(handler, transport, observers=[observer])

"""The Server's internal typed error — published, because every plugin raises it.

`ServerError` is not a host internal: it is the vocabulary a plugin uses to
state *why* an operation refused, and the composition that hosts it projects it
onto the wire family set (`server_plugin_api.wire_errors.WireError`). Before
T014-S2c the class lived in `ordessa_server.errors` and every plugin imported
it from there, which is exactly the AGENTS rule-3 breach this slice closes: a
plugin may import platform contracts, never host internals.

The name keeps its historical spelling because its `code` values are the
frozen internal codes of the wire/1 contract (`INVALID_REQUEST`'s family
answers depend on them); moving the definition must not rename a single code.
Nothing here projects anything: resolution onto a wire family is
`wire_errors`' job, and the *composition's* contributed rows are resolved
there through a resolver the host injects — never from this module.
"""
from __future__ import annotations


class ServerError(RuntimeError):
    def __init__(self, code: str, message: str, *, status: int, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
        self.retryable = retryable


def unavailable(code: str, message: str) -> ServerError:
    return ServerError(code, message, status=503, retryable=True)

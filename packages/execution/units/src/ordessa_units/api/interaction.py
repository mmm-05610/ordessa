"""Unit identity binding around native ACP payloads, results and events."""
from collections.abc import Mapping

from ordessa_units.errors import UnitApiRefused, UnitReconnectUnavailable


class UnitInteraction:
    def __init__(self, unit, connection):
        self._unit, self._connection = unit, connection
        self._disconnected = False

    def _require_connected(self):
        if self._disconnected:
            raise UnitReconnectUnavailable('Original writer disconnected; a new Unit is required')

    def request(self, method, params, *, timeout=60):
        self._require_connected()
        if not isinstance(method, str) or not isinstance(params, Mapping):
            raise UnitApiRefused('Native ACP method and params mapping required')
        if method in ('initialize', 'session/new', 'session/load', 'session/cancel'):
            raise UnitApiRefused('Unit owns session creation; use cancel for its notification')
        if method == 'session/set_config_option':
            raise UnitApiRefused('Configuration changes require the original configuration authority')
        return self._unit._assembly.request(self._unit, self._connection, method, params, timeout)

    def prompt(self, params, *, timeout=60, operation_ref=None):
        """Send a prompt, optionally fixing its original durable operation identity.

        The operation reference belongs to the original Unit journal, not the
        native ACP params. Reusing it is deliberately left to the original
        records owner, which refuses a second dispatch and supports exact
        authorized receipt queries.
        """
        self._require_connected()
        if not isinstance(params, Mapping):
            raise UnitApiRefused('Native ACP method and params mapping required')
        return self._unit._assembly.request(
            self._unit, self._connection, 'session/prompt', params, timeout,
            operation_ref=operation_ref)

    def cancel(self):
        self._require_connected()
        return self._unit._assembly.cancel(self._unit, self._connection)

    def submit_input(self, request, captured_ref, *, timeout=60):
        """Submit an original managed capture; no caller-supplied ACP payload."""
        self._require_connected()
        return self._unit._assembly.submit_input(
            self._unit, self._connection, request, captured_ref, timeout=timeout)

    def next_event(self, *, timeout=10):
        self._require_connected()
        return self._connection.next_event(timeout=timeout).raw

    def disconnect(self):
        if not self._disconnected:
            self._connection.close()
            self._disconnected = True

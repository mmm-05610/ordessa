"""Unit identity binding around native ACP payloads, results and events."""
from collections.abc import Mapping

from .errors import UnitApiRefused, UnitReconnectUnavailable


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

    def prompt(self, params, *, timeout=60):
        return self.request('session/prompt', params, timeout=timeout)

    def cancel(self):
        self._require_connected()
        return self._unit._assembly.cancel(self._unit, self._connection)

    def next_event(self, *, timeout=10):
        self._require_connected()
        return self._connection.next_event(timeout=timeout).raw

    def disconnect(self):
        if not self._disconnected:
            self._connection.close()
            self._disconnected = True

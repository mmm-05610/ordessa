"""Bounded public refusal categories, without native logs or secret values."""


class UnitApiRefused(RuntimeError):
    code = 'UNIT_API_REFUSED'


class UnitReconnectUnavailable(UnitApiRefused):
    code = 'UNIT_RECONNECT_UNAVAILABLE'

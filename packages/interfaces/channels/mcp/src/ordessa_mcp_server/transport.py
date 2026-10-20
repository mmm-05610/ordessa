"""MCP->Ordessa transport: a thin adapter over the shared stdlib wire client.

The shared client ``ordessa_system_access_client`` owns the bounded wire/1
transport (loopback/TLS endpoint validation, explicit redirect refusal, a
proxy-free opener, size/timeout limits, strict JSON parsing, and error messages
that never carry a response body). This module adds only the MCP-side posture
that differs, so there is no second HTTP path to drift:

* the token is read from the MCP process environment and refused locally when
  absent (the shared client's ``load_service`` reads it from a config file);
* the shared ``ClientError`` (a code plus a CLI exit code) is mapped to the
  local ``TransportRefused`` so the MCP tool layer never leaks that taxonomy.
"""
from __future__ import annotations

import uuid

from ordessa_system_access_client import (
    MAX_BYTES, METHOD_PATTERN, ClientError, Service, WireClient, core_schema,
)
from ordessa_system_access_client import validate_endpoint as _validate_endpoint
from ordessa_system_access_client import validate_method as _validate_method


class TransportRefused(Exception):
    """A locally refused MCP->Ordessa call; never carries a response body."""


def effectful(method):
    """Effectfulness from the published method metadata.

    A known method uses its declared ``effectful`` flag; an **unknown** method is
    treated as possibly-effectful, so a lost response is reported as
    ``OUTCOME_UNKNOWN`` (never as a safe/retryable observation failure).
    """
    for version in ("agent-assembly/3", "agent-assembly/1"):
        definition = core_schema(version)["schema"]["methods"].get(method)
        if definition is not None:
            return bool(definition["effectful"])
    return True


def validate_method(method):
    """Adapt the shared method validator to the MCP refusal type."""
    try:
        return _validate_method(method)
    except ClientError:
        raise TransportRefused("method is not a wire/1 method name") from None


def validate_endpoint(endpoint):
    """Adapt the shared endpoint validator to the MCP refusal type."""
    try:
        _validate_endpoint(endpoint)
    except ValueError:
        raise TransportRefused(
            "endpoint must be a bare http(s) origin without userinfo, query or fragment") from None
    return endpoint


def wire_call(endpoint, token, method, params=None, *, timeout=15):
    """One real wire/1 call through the shared client.

    The envelope request id is unique per logical call (never a fixed string),
    so two different calls can never be conflated; a caller that retries a write
    must reuse its own ``requestId`` parameter — this adapter never retries.
    """
    base = validate_endpoint(endpoint)
    validate_method(method)
    if not token or any(ord(char) < 33 or ord(char) > 126 for char in token):
        raise TransportRefused("a valid bearer token is required (set ORDESSA_MCP_TOKEN)")
    service = Service("ordessa-mcp", base, token)
    try:
        return WireClient(service, timeout=timeout).call(
            method, params or {}, uuid.uuid4().hex, effectful=effectful(method))
    except ClientError as error:
        raise TransportRefused(f"Ordessa refused the call ({error.code})") from None


__all__ = ["MAX_BYTES", "METHOD_PATTERN", "TransportRefused", "effectful", "validate_endpoint",
           "validate_method", "wire_call"]

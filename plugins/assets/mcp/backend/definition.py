"""MCP definitions: legacy-faithful canonicalisation plus the typed v2 model.

Two canonical rules live side by side and never overwrite each other:

* the legacy rule (verbatim from ``SC/assets/mcp.py``) — env/header values
  collapse to bare credential-reference strings; it still validates and
  digests the old ``server.json`` files byte-for-byte (FR-12);
* the v2 rule for new saves — every env/header value is typed as
  ``{"literal": str}`` or ``{"secretRef": id}``; a plain string in a value
  position is a typed refusal before anything reaches storage.

Digests are always taken over ``json.dumps(canonical, sort_keys=True,
separators=(",", ":"))`` with the ``sha256:`` prefix, identical to the legacy
:func:`definition_digest`, so an old revision keeps verifying under its old
digest and is never silently recomputed under a new one.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Union

from .errors import (
    MCP_CREDENTIAL_REFERENCE_REQUIRED,
    MCP_DEFINITION_INVALID,
    MCP_NAME_INVALID,
    MCP_TRANSPORT_UNSUPPORTED,
    McpError,
)

_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
_TRANSPORTS = ("stdio", "remote")
_MAX_LITERAL_LENGTH = 4096

# -- legacy canonical (verbatim semantics from SC/assets/mcp.py) ---------------


def _credential_references(values: Any, field: str) -> dict:
    if values is None:
        return {}
    if not isinstance(values, Mapping) or len(values) > 32:
        raise McpError(MCP_DEFINITION_INVALID, f"{field} must be a small mapping")
    references: dict = {}
    for key, value in values.items():
        if not isinstance(key, str) or not key or len(key) > 64:
            raise McpError(MCP_DEFINITION_INVALID, f"{field} keys must be short strings")
        if (not isinstance(value, Mapping) or set(value) != {"credentialRef"}
                or not isinstance(value.get("credentialRef"), str)
                or not value["credentialRef"]):
            raise McpError(
                MCP_CREDENTIAL_REFERENCE_REQUIRED,
                f"{field}.{key} must be {{'credentialRef': '<id>'}} - values are "
                "references, never literals",
            )
        references[key] = value["credentialRef"]
    return references


def canonical_definition(definition: Mapping[str, Any]) -> dict:
    """Validate one legacy-shaped server definition; return its canonical form.

    Byte-for-byte the old store's rule: same inputs, same output dict, same
    codes and messages, so migrated revisions digest identically.
    """
    if not isinstance(definition, Mapping):
        raise McpError(MCP_DEFINITION_INVALID, "a server definition is an object")
    allowed = {"name", "transport"}
    if set(definition) - allowed:
        raise McpError(
            MCP_DEFINITION_INVALID,
            f"unknown definition fields: {sorted(set(definition) - allowed)}",
        )
    name = definition.get("name")
    if not isinstance(name, str) or _NAME.fullmatch(name) is None:
        raise McpError(MCP_NAME_INVALID, "name must be a lowercase slug")
    transport = definition.get("transport")
    if not isinstance(transport, Mapping) or len(transport) != 1:
        raise McpError(MCP_DEFINITION_INVALID, "transport names exactly one of stdio/remote")
    kind = next(iter(transport))
    body = transport[kind]
    if kind not in _TRANSPORTS or not isinstance(body, Mapping):
        raise McpError(MCP_TRANSPORT_UNSUPPORTED, f"unsupported transport {kind!r}")
    if kind == "stdio":
        if set(body) - {"command", "args", "env"}:
            raise McpError(MCP_DEFINITION_INVALID, "stdio carries command/args/env only")
        command = body.get("command")
        if not isinstance(command, str) or not command.startswith("/") or "\x00" in command:
            raise McpError(MCP_DEFINITION_INVALID, "command must be an absolute path")
        args = body.get("args", [])
        if (not isinstance(args, list) or len(args) > 64
                or any(not isinstance(item, str) or "\x00" in item for item in args)):
            raise McpError(MCP_DEFINITION_INVALID, "args must be a small string list")
        return {
            "name": name,
            "transport": {"stdio": {
                "command": command,
                "args": list(args),
                "env": _credential_references(body.get("env"), "env"),
            }},
        }
    url = body.get("url")
    if (not isinstance(url, str) or len(url) > 512 or "\x00" in url
            or not (url.startswith("https://") or url.startswith("http://127.0.0.1"))):
        raise McpError(
            MCP_DEFINITION_INVALID,
            "a remote server needs an https (or loopback http) url",
        )
    return {
        "name": name,
        "transport": {"remote": {
            "url": url,
            "headers": _credential_references(body.get("headers"), "headers"),
        }},
    }


def definition_digest(canonical: Mapping[str, Any]) -> str:
    encoded = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


# -- typed v2 values ------------------------------------------------------------


@dataclass(frozen=True)
class Literal:
    value: str


@dataclass(frozen=True)
class SecretRef:
    credential_id: str


Value = Union[Literal, SecretRef]


def _typed_references(values: Any, field: str) -> dict:
    if values is None:
        return {}
    if not isinstance(values, Mapping) or len(values) > 32:
        raise McpError(MCP_DEFINITION_INVALID, f"{field} must be a small mapping")
    references: dict = {}
    for key, value in values.items():
        if not isinstance(key, str) or not key or len(key) > 64:
            raise McpError(MCP_DEFINITION_INVALID, f"{field} keys must be short strings")
        if not isinstance(value, Mapping) or len(value) != 1:
            raise McpError(
                MCP_DEFINITION_INVALID,
                f"{field}.{key} must be {{'literal': '<value>'}} or "
                "{{'secretRef': '<id>'}} - values are typed, never bare strings",
            )
        only_key = next(iter(value))
        payload = value[only_key]
        if only_key == "secretRef":
            if not isinstance(payload, str) or not payload:
                raise McpError(
                    MCP_DEFINITION_INVALID, f"{field}.{key} secretRef must be a non-empty string")
            references[key] = {"secretRef": payload}
        elif only_key == "literal":
            if (not isinstance(payload, str) or "\x00" in payload
                    or len(payload) > _MAX_LITERAL_LENGTH):
                raise McpError(
                    MCP_DEFINITION_INVALID,
                    f"{field}.{key} literal must be a short NUL-free string",
                )
            references[key] = {"literal": payload}
        elif only_key == "credentialRef":
            if not isinstance(payload, str) or not payload:
                raise McpError(
                    MCP_DEFINITION_INVALID, f"{field}.{key} credentialRef must be a non-empty string")
            references[key] = {"secretRef": payload}
        else:
            raise McpError(
                MCP_DEFINITION_INVALID,
                f"{field}.{key} has unknown value shape {sorted(value)}",
            )
    return references


def canonical_definition_v2(definition: Mapping[str, Any]) -> dict:
    """Validate one v2 server definition; return its canonical form.

    Same top-level shape and same refusal codes as the legacy rule; the only
    difference is that env/header values stay typed (``literal``/``secretRef``)
    instead of collapsing to bare reference strings.
    """
    if not isinstance(definition, Mapping):
        raise McpError(MCP_DEFINITION_INVALID, "a server definition is an object")
    allowed = {"name", "transport"}
    if set(definition) - allowed:
        raise McpError(
            MCP_DEFINITION_INVALID,
            f"unknown definition fields: {sorted(set(definition) - allowed)}",
        )
    name = definition.get("name")
    if not isinstance(name, str) or _NAME.fullmatch(name) is None:
        raise McpError(MCP_NAME_INVALID, "name must be a lowercase slug")
    transport = definition.get("transport")
    if not isinstance(transport, Mapping) or len(transport) != 1:
        raise McpError(MCP_DEFINITION_INVALID, "transport names exactly one of stdio/remote")
    kind = next(iter(transport))
    body = transport[kind]
    if kind not in _TRANSPORTS or not isinstance(body, Mapping):
        raise McpError(MCP_TRANSPORT_UNSUPPORTED, f"unsupported transport {kind!r}")
    if kind == "stdio":
        if set(body) - {"command", "args", "env"}:
            raise McpError(MCP_DEFINITION_INVALID, "stdio carries command/args/env only")
        command = body.get("command")
        if not isinstance(command, str) or not command.startswith("/") or "\x00" in command:
            raise McpError(MCP_DEFINITION_INVALID, "command must be an absolute path")
        args = body.get("args", [])
        if (not isinstance(args, list) or len(args) > 64
                or any(not isinstance(item, str) or "\x00" in item for item in args)):
            raise McpError(MCP_DEFINITION_INVALID, "args must be a small string list")
        return {
            "name": name,
            "transport": {"stdio": {
                "command": command,
                "args": list(args),
                "env": _typed_references(body.get("env"), "env"),
            }},
        }
    url = body.get("url")
    if (not isinstance(url, str) or len(url) > 512 or "\x00" in url
            or not (url.startswith("https://") or url.startswith("http://127.0.0.1"))):
        raise McpError(
            MCP_DEFINITION_INVALID,
            "a remote server needs an https (or loopback http) url",
        )
    return {
        "name": name,
        "transport": {"remote": {
            "url": url,
            "headers": _typed_references(body.get("headers"), "headers"),
        }},
    }


# -- in-memory entities (docs/design/mcp/data-model.md) -------------------------


@dataclass(frozen=True)
class StdioTransport:
    executable_ref: str
    argv: tuple
    env: Mapping[str, Value]


@dataclass(frozen=True)
class RemoteTransport:
    url: str
    headers: Mapping[str, Value]


@dataclass(frozen=True)
class ApprovalRecord:
    actor: str
    approved_at: str


@dataclass(frozen=True)
class McpDefinition:
    server_scope: str
    definition_id: str
    native_name: str
    transport: str
    archived: bool
    latest_revision: int


@dataclass(frozen=True)
class McpRevision:
    definition_id: str
    revision: int
    canonical_digest: str
    canonical: Mapping[str, Any]
    canonical_shape: str  # "legacy" | "v2"
    source: Optional[str]
    created_at: str
    approval: Optional[ApprovalRecord]
    transport: Union[StdioTransport, RemoteTransport]
    migration: Optional[Mapping[str, Any]]


def _to_value(raw: Any) -> Value:
    if isinstance(raw, Mapping):
        if set(raw) == {"secretRef"}:
            return SecretRef(str(raw["secretRef"]))
        if set(raw) == {"literal"}:
            return Literal(str(raw["literal"]))
        raise McpError(MCP_DEFINITION_INVALID, "stored value shape is unknown")
    if isinstance(raw, str):
        return SecretRef(raw)
    raise McpError(MCP_DEFINITION_INVALID, "stored value must be a string or a typed object")


def revision_model(
    *, definition_id: str, revision: int, canonical: Mapping[str, Any],
    canonical_digest: str, shape: str, source: Optional[str], created_at: str,
    approval: Optional[ApprovalRecord],
) -> McpRevision:
    """Normalise one stored canonical dict (legacy or v2) into the v2 model.

    Legacy ``credentialRef`` collapses were lossy on disk (a bare reference
    string); reading restores it as :class:`SecretRef` with an explicit
    migration note - the stored digest is kept, never recomputed.
    """
    transport_body = canonical["transport"]
    kind = next(iter(transport_body))
    body = transport_body[kind]
    migration = None
    if kind == "stdio":
        env = {name: _to_value(value) for name, value in body.get("env", {}).items()}
        transport: Union[StdioTransport, RemoteTransport] = StdioTransport(
            executable_ref=body["command"], argv=tuple(body.get("args", [])), env=env)
    else:
        headers = {name: _to_value(value) for name, value in body.get("headers", {}).items()}
        transport = RemoteTransport(url=body["url"], headers=headers)
    if shape == "legacy":
        migration = {
            "legacy_digest": canonical_digest,
            "recomputed": False,
            "rule": "bare env/header strings are credential references "
                    "(legacy {'credentialRef': id} collapse); restored as SecretRef",
        }
    return McpRevision(
        definition_id=definition_id, revision=revision, canonical_digest=canonical_digest,
        canonical=canonical, canonical_shape=shape, source=source, created_at=created_at,
        approval=approval, transport=transport, migration=migration,
    )

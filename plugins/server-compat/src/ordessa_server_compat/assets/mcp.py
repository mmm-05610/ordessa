"""Order 58: the MCP server asset - one standard definition, one revision.

The stored form is the *standard* one the MCP ecosystem already speaks, and
nothing family-specific lives here: a server is either stdio
(``{command, args, env}``) or remote (``{url, headers}``), and the per-family
translation into a file location and key spelling is the adapter's job
(``rendering.py``). Two rules are the store's own:

* **credentials are references, never values**: every ``env`` / ``headers``
  entry must be ``{"credentialRef": "<credential id>"}``. A plain string is a
  typed refusal - the store has no way to tell a secret from a constant, and
  guessing is how a secret ends up in a file;
* **content addressing**: the definition is canonicalised (sorted keys, no
  whitespace games) before it is written, and the digest is taken over exactly
  those bytes, so a materialised projection can be verified against it.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Mapping

_NAME = re.compile(r"[a-z0-9][a-z0-9._-]{0,63}\Z")
_TRANSPORTS = ("stdio", "remote")


class McpAssetError(RuntimeError):
    """A typed refusal of one MCP server install or read."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def _credential_references(values: Any, field: str) -> dict[str, str]:
    if values is None:
        return {}
    if not isinstance(values, Mapping) or len(values) > 32:
        raise McpAssetError("MCP_DEFINITION_INVALID", f"{field} must be a small mapping")
    references: dict[str, str] = {}
    for key, value in values.items():
        if not isinstance(key, str) or not key or len(key) > 64:
            raise McpAssetError("MCP_DEFINITION_INVALID", f"{field} keys must be short strings")
        if (not isinstance(value, Mapping) or set(value) != {"credentialRef"}
                or not isinstance(value.get("credentialRef"), str)
                or not value["credentialRef"]):
            raise McpAssetError(
                "MCP_CREDENTIAL_REFERENCE_REQUIRED",
                f"{field}.{key} must be {{'credentialRef': '<id>'}} - values are "
                "references, never literals",
            )
        references[key] = value["credentialRef"]
    return references


def canonical_definition(definition: Mapping[str, Any]) -> dict[str, Any]:
    """Validate one standard server definition and return its canonical form.

    Raises :class:`McpAssetError` with a code per distinct rule; the canonical
    form is what the digest is taken over and what a projection renders from.
    """
    if not isinstance(definition, Mapping):
        raise McpAssetError("MCP_DEFINITION_INVALID", "a server definition is an object")
    allowed = {"name", "transport"}
    if set(definition) - allowed:
        raise McpAssetError(
            "MCP_DEFINITION_INVALID",
            f"unknown definition fields: {sorted(set(definition) - allowed)}",
        )
    name = definition.get("name")
    if not isinstance(name, str) or _NAME.fullmatch(name) is None:
        raise McpAssetError("MCP_NAME_INVALID", "name must be a lowercase slug")
    transport = definition.get("transport")
    if not isinstance(transport, Mapping) or len(transport) != 1:
        raise McpAssetError(
            "MCP_DEFINITION_INVALID", "transport names exactly one of stdio/remote",
        )
    kind = next(iter(transport))
    body = transport[kind]
    if kind not in _TRANSPORTS or not isinstance(body, Mapping):
        raise McpAssetError("MCP_TRANSPORT_UNSUPPORTED", f"unsupported transport {kind!r}")
    if kind == "stdio":
        if set(body) - {"command", "args", "env"}:
            raise McpAssetError("MCP_DEFINITION_INVALID", "stdio carries command/args/env only")
        command = body.get("command")
        if not isinstance(command, str) or not command.startswith("/") or "\x00" in command:
            raise McpAssetError(
                "MCP_DEFINITION_INVALID", "command must be an absolute path",
            )
        args = body.get("args", [])
        if (not isinstance(args, list) or len(args) > 64
                or any(not isinstance(item, str) or "\x00" in item for item in args)):
            raise McpAssetError("MCP_DEFINITION_INVALID", "args must be a small string list")
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
        raise McpAssetError(
            "MCP_DEFINITION_INVALID",
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


class McpAssetStore:
    """Install MCP server definitions as revisions under one assets root."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def revision_dir(self, asset_id: str, revision: int) -> Path:
        return self.root / "mcp" / asset_id / str(revision)

    def install(self, definition: Mapping[str, Any], *, asset_id: str, revision: int) -> dict[str, Any]:
        canonical = canonical_definition(definition)
        payload = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
        destination = self.revision_dir(asset_id, revision)
        if destination.exists():
            raise McpAssetError(
                "MCP_REVISION_EXISTS", f"revision {revision} of {asset_id} already exists",
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(prefix="mcp-staging-", dir=str(destination.parent)))
        try:
            (staging / "server.json").write_bytes(payload)
            os.chmod(staging / "server.json", 0o644)
            os.rename(staging, destination)
        except BaseException:
            import shutil

            shutil.rmtree(staging, ignore_errors=True)
            raise
        return {
            "asset_id": asset_id,
            "kind": "mcp",
            "revision": revision,
            "digest": definition_digest(canonical),
            "name": canonical["name"],
            "transport": next(iter(canonical["transport"])),
        }

    def read(self, *, asset_id: str, revision: int) -> dict[str, Any]:
        path = self.revision_dir(asset_id, revision) / "server.json"
        if not path.is_file():
            raise McpAssetError("MCP_ASSET_MISSING", "the MCP revision is not installed")
        return json.loads(path.read_text(encoding="utf-8"))

    def verify(self, *, asset_id: str, revision: int, expected_digest: str) -> bool:
        return definition_digest(self.read(asset_id=asset_id, revision=revision)) == expected_digest

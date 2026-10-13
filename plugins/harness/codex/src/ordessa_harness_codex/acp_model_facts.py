"""Historical Codex ACP model facts, not app-server compatibility or admission.

Provenance: former Harness model/common.py at 6af84df2a4 and native family
pins at 96fef2db47. Current independent app-server pin remains 0.157.1.
"""
from __future__ import annotations
import hashlib
import json
import re
from typing import Any

CANONICAL_PROTOCOLS = ("openai-chat", "openai-responses", "anthropic-messages", "gemini-generate")
DIALECT = {"openai-responses": ("wire_api", "responses"), "openai-chat": ("wire_api", "chat")}
VERSION_RANGE = ("1.0", "2.0")
RANGE_STRINGS = {"codex": ">=1.0 <2.0"}
NATIVE_TARGET = {"codex": "config.toml"}
CODEX_EFFORT_FIELD = "model_reasoning_effort"
CODEX_EFFORT_VALUES = ("low", "medium", "high", "xhigh", "max")
CODEX_DEEPSEEK_EFFORT_VALUES = ("low", "high", "max")


class ProtocolUnsupported(Exception):
    """No first-hand Codex ACP field for the supplied protocol."""


def translate_protocol(harness, protocol):
    if protocol not in CANONICAL_PROTOCOLS:
        raise ProtocolUnsupported(f"{protocol!r} is not a canonical protocol")
    dialect = DIALECT.get(protocol) if harness == "codex" else None
    if dialect is None:
        raise ProtocolUnsupported(f"{harness} has no first-hand native field for protocol {protocol!r}")
    return dialect

def codex_effort_values(provider_family: str | None) -> tuple[str, ...]:
    """The pinned effort vocabulary for one codex provider family."""
    if provider_family == "deepseek":
        return CODEX_DEEPSEEK_EFFORT_VALUES
    return CODEX_EFFORT_VALUES


def digest_label(request: Any) -> str:
    """A stable short content digest for a MountContent reference (the content
    itself stays with the harness; only the label identifies it)."""
    payload = json.dumps([
        request.provider_name, request.endpoint, request.protocol, request.model_id,
    ], sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def render_codex_provider_section(*, provider: str, base_url: str, protocol: str) -> str:
    """The ``[model_providers.<id>]`` TOML block, byte-stable (same input ->
    same bytes). provenance: ``ordessa_server_product.native_materialization
    .render_codex_provider_section`` @ 96fef2db47; endpoint/protocol live
    *inside* the provider table and the credential stays an env-name."""

    if not identity_text(provider) or not identity_text(base_url):
        raise ValueError("provider and endpoint must be explicit text without control characters")
    field, dialect = translate_protocol("codex", protocol)
    key = provider if re.fullmatch(r"[A-Za-z0-9_-]+", provider) else json.dumps(provider, ensure_ascii=False)
    lines = [
        f"[model_providers.{key}]",
        f"name = {json.dumps(provider, ensure_ascii=False)}",
        f"base_url = {json.dumps(base_url, ensure_ascii=False)}",
        f"{field} = \"{dialect}\"",
        "env_key = \"CODEX_API_KEY\"",
    ]
    return "\n".join(lines) + "\n"


def identity_text(value: Any) -> bool:
    if not isinstance(value, str) or not value or value.strip() != value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        return False
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError:
        return False
    return True

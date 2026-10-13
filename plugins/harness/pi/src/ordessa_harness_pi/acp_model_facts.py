"""Historical Pi ACP pure configuration facts, not native RPC admission.

Provenance: old Harness compiler/common/native_materialization at 65e4095345.
ACP 0.5 adapter range and current native RPC source pin are distinct axes.
"""
from __future__ import annotations
import re
from typing import Any

CANONICAL_PROTOCOLS = ("openai-chat", "openai-responses", "anthropic-messages", "gemini-generate")
DIALECT = {"openai-chat": ("api", "openai-completions")}
VERSION_RANGE = ("0.5.0", "0.6")
RANGE_STRINGS = {"pi": ">=0.5.0 <0.6"}
NATIVE_TARGET = {"pi": "models.json"}
PI_SETTINGS_NATIVE_TARGET = "settings.json"
PI_SETTINGS_HANDLE_ID = "pi.settings.json"
PI_MAX_TOKENS_KEY = "maxTokens"

class ProtocolUnsupported(Exception):
    """No pinned native Pi field for this protocol."""


def translate_protocol(harness, protocol):
    if protocol not in CANONICAL_PROTOCOLS:
        raise ProtocolUnsupported(f"{protocol!r} is not a canonical protocol")
    dialect = DIALECT.get(protocol) if harness == "pi" else None
    if dialect is None:
        raise ProtocolUnsupported(f"{harness} has no first-hand native field for protocol {protocol!r}")
    return dialect


def render_pi_provider(*, provider: str, base_url: str, protocol: str) -> dict:
    """The `providers.<id>` object pi's models.json reads for one upstream."""
    field, dialect = translate_protocol("pi", protocol)
    return {
        "baseUrl": base_url,
        field: dialect,
        "apiKey": "$DEEPSEEK_API_KEY",  # a reference, never credential content
    }
def identity_text(value: Any) -> bool:
    if not isinstance(value, str) or not value or value.strip() != value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        return False
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError:
        return False
    return True
def safe_provider_sample(value: Any) -> bool:
    """Native credential material must not travel in pure intents.

    Only the established $ENV_NAME apiKey reference is preserved here;
    nonempty native headers require the production credential owner instead.
    """
    from collections.abc import Mapping
    if not isinstance(value, Mapping):
        return False
    key = value.get("apiKey")
    if key is not None and (not isinstance(key, str) or re.fullmatch(r"\$[A-Za-z_][A-Za-z0-9_]*", key) is None):
        return False
    return not value.get("headers")

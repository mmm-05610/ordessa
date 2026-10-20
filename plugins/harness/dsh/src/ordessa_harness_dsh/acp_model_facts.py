"""dsh ACP model facts: honestly EMPTY — no pinned native model facts here.

Provenance discipline (freeze §3): this package holds zero first-hand dsh
model-configuration facts. The family tables are empty by construction:

- ``DIALECT = {}`` — no first-hand dsh protocol dialect field exists in this
  tree, so every protocol translation is a typed refusal.
- ``NATIVE_TARGET = {"dsh": None}`` — no pinned dsh native configuration
  target exists (no provider-section renderer, no settings template claim).
- ``RANGE_STRINGS = {"dsh": ""}`` — no pinned dsh version range exists; an
  empty range admits nothing, so every concrete version assesses as
  unsupported and unparsable versions as unknown.

The npm pin ``@deepseek-ai/dsh`` ``0.1.5-rc.1`` (tooling/npm lock) is a
CLI/channel pin, not a model-configuration fact: it must never be projected
into configuration claims. ``session/load`` rejection and the resume/bridge
continuation split are channel facts, historically recorded in the unchanged original client tests; current gaps are in README.md.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


CANONICAL_PROTOCOLS = ("openai-chat", "openai-responses", "anthropic-messages", "gemini-generate")

#: Empty by design: no first-hand dsh protocol dialect mapping exists here.
DIALECT: dict[str, tuple[str, str]] = {}

#: Empty by design: no pinned dsh native configuration target exists here.
NATIVE_TARGET: dict[str, Any] = {"dsh": None}

#: Empty by design: no pinned dsh model version range exists in this tree.
RANGE_STRINGS: dict[str, str] = {"dsh": ""}

#: The dsh model-kind label this family would use if facts ever arrive.
DSH_MODEL_KIND = "dsh.model"


class ProtocolUnsupported(Exception):
    """No first-hand dsh ACP field for the supplied protocol."""


def translate_protocol(harness, protocol):
    if protocol not in CANONICAL_PROTOCOLS:
        raise ProtocolUnsupported(f"{protocol!r} is not a canonical protocol")
    if harness != "dsh":
        raise ProtocolUnsupported("dsh ACP facts cannot describe another family")
    # The dsh dialect table is empty: every protocol is honestly unsupported.
    raise ProtocolUnsupported(f"dsh has no first-hand native field for protocol {protocol!r}")


def version_in_range(harness, version):
    if harness != "dsh":
        raise ValueError("dsh ACP version fact cannot describe another family")
    if not isinstance(version,str) or not version.strip() or not all(part.isdigit() for part in version.strip().split('.')):
        return "unknown"
    # The pinned dsh range is EMPTY: no concrete version is supported by it.
    return "unsupported"


def identity_text(value: Any) -> bool:
    if not isinstance(value, str) or not value or value.strip() != value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        return False
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeError:
        return False
    return True


def digest_label(request: Any) -> str:
    """A stable short content digest for one planning request (content itself
    stays with the harness; only the label identifies it)."""
    payload = json.dumps([
        request.provider_name, request.endpoint, request.protocol, request.model_id,
    ], sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]

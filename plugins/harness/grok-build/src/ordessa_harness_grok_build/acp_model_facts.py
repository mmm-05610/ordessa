"""grok-build ACP model facts: honestly EMPTY — no pinned native model facts here.

Provenance discipline (registration draft §6 / package spec): this package
holds zero first-hand grok-build model-configuration facts. The family tables
are empty by construction:

- ``DIALECT = {}`` — no first-hand grok-build protocol dialect field exists in
  this tree, so every protocol translation is a typed refusal.
- ``NATIVE_TARGET = {"grok-build": None}`` — no pinned grok-build native
  configuration target exists (no provider-section renderer, no settings
  template claim).
- ``RANGE_STRINGS = {"grok-build": ""}`` — no pinned grok-build model version
  range exists; an empty range admits nothing, so every concrete version
  assesses as unsupported and unparsable versions as unknown.

The CLI version pin ``1.0.46`` (x.ai/changelog/build entry 2026-09-30) is a
CLI/channel pin, not a model-configuration fact: it must never be projected
into configuration claims. ACP reopen absence, kill_task/get_task_output
absence and the authenticate-extension gate are channel facts, recorded in
provider.py/client.py.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from ordessa_execution_agents.harness.definitions.model_compilation import parse_version

CANONICAL_PROTOCOLS = ("openai-chat", "openai-responses", "anthropic-messages", "gemini-generate")

#: Empty by design: no first-hand grok-build protocol dialect mapping exists here.
DIALECT: dict[str, tuple[str, str]] = {}

#: Empty by design: no pinned grok-build native configuration target exists here.
NATIVE_TARGET: dict[str, Any] = {"grok-build": None}

#: Empty by design: no pinned grok-build model version range exists in this tree.
RANGE_STRINGS: dict[str, str] = {"grok-build": ""}

#: The grok-build model-kind label this family would use if facts ever arrive.
GROK_BUILD_MODEL_KIND = "grok-build.model"


class ProtocolUnsupported(Exception):
    """No first-hand grok-build ACP field for the supplied protocol."""


def translate_protocol(harness, protocol):
    if protocol not in CANONICAL_PROTOCOLS:
        raise ProtocolUnsupported(f"{protocol!r} is not a canonical protocol")
    if harness != "grok-build":
        raise ProtocolUnsupported("grok-build ACP facts cannot describe another family")
    # The grok-build dialect table is empty: every protocol is honestly unsupported.
    raise ProtocolUnsupported(f"grok-build has no first-hand native field for protocol {protocol!r}")


def version_in_range(harness, version):
    if harness != "grok-build":
        raise ValueError("grok-build ACP version fact cannot describe another family")
    parsed = parse_version(version)
    if parsed is None:
        return "unknown"
    # The pinned grok-build range is EMPTY: no concrete version is supported by it.
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

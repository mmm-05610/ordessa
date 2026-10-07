"""Historical Claude ACP model pins; not SDK compatibility or runtime admission.

Provenance: the former Harness model/common.py at 3c83819e23 and the
reviewed Claude ACP 0.81.2 controlled packaging probes. No native call.
"""
from pacthold.harness_contracts.model_compilation import parse_version

CANONICAL_PROTOCOLS = ("openai-chat", "openai-responses", "anthropic-messages", "gemini-generate")
DIALECT = {"anthropic-messages": ("ANTHROPIC_BASE_URL", None)}
VERSION_RANGE = ("0.81", "0.82")
RANGE_STRINGS = {"claude-code": ">=0.81 <0.82"}
NATIVE_TARGET = {"claude-code": "settings.json"}


class ProtocolUnsupported(Exception):
    """No first-hand Claude ACP field for the supplied protocol."""


def translate_protocol(harness, protocol):
    if protocol not in CANONICAL_PROTOCOLS:
        raise ProtocolUnsupported(f"{protocol!r} is not a canonical protocol")
    dialect = DIALECT.get(protocol) if harness == "claude-code" else None
    if dialect is None:
        raise ProtocolUnsupported(f"{harness} has no first-hand native field for protocol {protocol!r}")
    return dialect


def version_in_range(harness, version):
    if harness != "claude-code":
        raise ValueError("Claude ACP version fact cannot describe another family")
    parsed = parse_version(version)
    if parsed is None:
        return "unknown"
    low, high = (parse_version(value) for value in VERSION_RANGE)
    padded = parsed + (0,) * max(0, len(low) - len(parsed))
    return "supported" if low <= padded < high else "unsupported"

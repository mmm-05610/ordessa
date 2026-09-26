"""The canonical protocol vocabulary shared by provider records and Harness
deployment seats (Work Order 092, R-0013 layer 1).

This is a leaf module on purpose: the Harness descriptor (execution) and the
provider service (model_configs) both depend on this single spelling of the four
protocol values, and neither may define its own. The dialect-normalization table
that folds real-world strings onto these values lives beside the service in
``model_configs.provider_protocols``; only the canonical set itself is shared
here so the descriptor's assembly-time check and the wire vocabulary cannot
drift apart.
"""
from __future__ import annotations

#: The only four protocol strings the Server recognizes, in canonical order.
CANONICAL_PROTOCOLS: tuple[str, ...] = (
    "openai-chat",
    "openai-responses",
    "anthropic-messages",
    "gemini-generate",
)

CANONICAL_PROTOCOL_SET = frozenset(CANONICAL_PROTOCOLS)

#: How many protocols a single Harness seat may declare. Bounded by the four
#: canonical values; a larger list is a malformed document, not a real family.
MAX_WIRE_PROTOCOLS = len(CANONICAL_PROTOCOLS)

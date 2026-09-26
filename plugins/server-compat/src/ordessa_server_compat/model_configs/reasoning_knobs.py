"""Work Order 096: reasoning-knob value domains and validation (harness-level
knob, model-level values). A pure, side-effect-free layer the descriptor and the
service consume; the `config.describe` *projection* of the effective domain is
owned by the wire handlers (a different line), and the native-config *write* is
093's writer - this module only decides what a legal value is.

Two rules from 096 (and AQ-0001's "default middle, never highest"):

* the effective value domain is **pinned enum ∪ the current model's facts,
  translated into this family's dialect** - a family never borrows another's
  dialect, and a value outside the domain is a typed ``CONTROL_VALUE_UNSUPPORTED``;
* when neither a pinned enum nor a model fact exists, there is **no domain** (the
  knob is "undeclared"); the caller shows "未声明" and must not invent options.
"""
from __future__ import annotations

from typing import Mapping, Sequence

from ordessa_server.errors import ServerError


#: First-hand per-family reasoning-effort enums for the families whose dialect is
#: pinned in this repo (096 stage 1 citations: cc-switch codexProviderPresets.ts:642
#: -> low/medium/high; opencodeProviderPresets.ts:142-157 -> low/medium/high/xhigh).
#: Families absent here have no pinned enum; a value must then come from model facts
#: or the knob stays undeclared. qwen/dsh effort enums are NOT pinned -> absent on
#: purpose (096: "钉不死就不声明", never a guessed list).
PINNED_EFFORT_DOMAINS: Mapping[str, tuple[str, ...]] = {
    "codex": ("low", "medium", "high"),
    "opencode": ("low", "medium", "high", "xhigh"),
    "kilo": ("low", "medium", "high", "xhigh"),
}

#: The canonical `reasoning_options` effort values (092 model facts, models.dev
#: vocabulary). A family's dialect may rename them; `None` means identity.
def _translate(model_value: str, dialect_map: Mapping[str, str] | None) -> str:
    return (dialect_map or {}).get(model_value, model_value)


def effective_domain(
    harness: str,
    *,
    model_effort_values: Sequence[str] | None = None,
    dialect_map: Mapping[str, str] | None = None,
) -> tuple[str, ...] | None:
    """The legal values for this family's reasoning knob right now, or ``None``.

    ``None`` means *undeclared*: neither a pinned enum nor model facts give a
    domain, so the caller must show "未声明" and not offer invented options.
    Otherwise it is the pinned enum union the current model's (dialect-translated)
    effort facts, in a stable, de-duplicated order.
    """
    pinned = PINNED_EFFORT_DOMAINS.get(harness, ())
    translated = tuple(_translate(v, dialect_map) for v in (model_effort_values or ()))
    combined: list[str] = []
    for value in (*pinned, *translated):
        if value not in combined:
            combined.append(value)
    return tuple(combined) if combined else None


def default_effort(domain: Sequence[str] | None) -> str | None:
    """AQ-0001: the default is the *middle* of the domain, never the highest.

    For a low/medium/high domain that is `medium`; for an even count the lower
    middle. ``None`` (undeclared) yields no default - we do not invent a value.
    """
    if not domain:
        return None
    # Prefer the canonical middle; fall back to index-based middle.
    if "medium" in domain:
        return "medium"
    return domain[(len(domain) - 1) // 2]


def validate_reasoning_value(
    harness: str, value: str,
    *,
    model_effort_values: Sequence[str] | None = None,
    dialect_map: Mapping[str, str] | None = None,
    control_id: str = "reasoningEffort",
) -> str:
    """Accept a value inside the effective domain; otherwise typed refusal.

    An *undeclared* domain (no pinned enum and no model facts) is not "any value
    allowed" - it means we have nothing to validate against, so the caller must
    not be submitting a value at all: we refuse with CONTROL_VALUE_UNSUPPORTED
    naming the control, rather than silently accepting a guess.
    """
    domain = effective_domain(harness, model_effort_values=model_effort_values,
                              dialect_map=dialect_map)
    if domain is None:
        raise ServerError(
            "CONTROL_VALUE_UNSUPPORTED",
            f"{harness}.{control_id} has no declared value domain for the current model",
            status=422,
        )
    if value not in domain:
        raise ServerError(
            "CONTROL_VALUE_UNSUPPORTED",
            f"value {value!r} not in {harness}.{control_id} domain {list(domain)}",
            status=422,
        )
    return value

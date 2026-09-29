"""Work Order 093 stage 2: canonical protocol -> per-family native-config dialect.

Layer 1 froze an upstream (`{provider, model, endpoint, protocol}`); 093 makes a
harness *actually use* it by writing it into that family's native configuration
file, replacing the status quo where each `production.py`'s `OFFICIAL_BASE_URL`
is the only endpoint the family can reach.

The canonical protocol vocabulary and the dialect->canonical normalization are
**092's contract** (four values: `openai-chat` / `openai-responses` /
`anthropic-messages` / `gemini-generate`). This module does not define them - it
consumes them and maps each to the *native* dialect string that family writes,
which is first-hand from the checked-in `deploy/<family>/` templates (093 stage 1).

The one rule that makes this honest (R-0013 §4, 085's discipline): **a family
that cannot express a protocol with a first-hand-pinned native field is refused
with `PROTOCOL_UNSUPPORTED_BY_HARNESS` - never a guessed dialect value, never a
silent default.** A dialect is only emitted when a real native file key holds it.

Nothing here reads or writes credentials: the endpoint, protocol and model id are
non-secret facts; the API key stays an environment reference the projection
channel injects (R-0012 - the one-time credential projection is the only path).
"""
from __future__ import annotations

from typing import Mapping

# P-A② (approvals/PA2-dialect-release.md): each family's dialect facts live in
# that family's own module; this file keeps exactly one brand touch point - the
# explicit aggregation below - the same position `adapters/__init__.py` holds
# for ADAPTERS. Seven explicit imports (one per family package).
from .claude import native as _claude_native
from .codex import native as _codex_native
from .dsh import native as _dsh_native
from .hermes import native as _hermes_native
from .kilo import native as _kilo_native
from .opencode import native as _opencode_native
from .pi import native as _pi_native

#: The canonical protocol vocabulary (092's contract, four values).
CANONICAL_PROTOCOLS = ("openai-chat", "openai-responses", "anthropic-messages", "gemini-generate")

#: Aggregated per-family dialect table (P-A②): values are the family modules'
#: own `DIALECTS` objects - same table, not a copy. A family/protocol pair absent
#: here has NO pinned native field -> :func:`translate_protocol` refuses it (it
#: is not "unsupported forever", only "not pinned yet: refuse"). The citation
#: for every value lives next to it, in the family's `native.py`.
#:
#:   family        protocol           native field      dialect value
_FAMILY_DIALECTS: dict[str, dict[str, tuple[str, str | None]]] = {
    "codex": _codex_native.DIALECTS,
    "pi": _pi_native.DIALECTS,
    "hermes": _hermes_native.DIALECTS,
    "opencode": _opencode_native.DIALECTS,
    "kilo": _kilo_native.DIALECTS,
    # harness id key is `claude-code`; the family package directory is `claude`
    # (naming mismatch kept as-is by the approval).
    "claude-code": _claude_native.DIALECTS,
    "dsh": _dsh_native.DIALECTS,
}

#: Aggregated native target paths (P-A②): the six families that pin one. dsh
#: pins `None` in its own module and stays **absent** here - exactly the
#: pre-P-A② shape; `materialize_family` reads this with `.get()`, so absent and
#: None would resolve identically for it either way.
_NATIVE_TARGET = {
    "codex": _codex_native.NATIVE_TARGET,
    "opencode": _opencode_native.NATIVE_TARGET,
    "kilo": _kilo_native.NATIVE_TARGET,
    "pi": _pi_native.NATIVE_TARGET,
    "hermes": _hermes_native.NATIVE_TARGET,
    "claude-code": _claude_native.NATIVE_TARGET,
}


class NativeMaterializationError(RuntimeError):
    """A typed refusal of one native-config write."""

    def __init__(self, code: str, message: str, *, harness: str | None = None,
                 protocol: str | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.harness = harness
        self.protocol = protocol


def is_pinnable(harness: str, protocol: str) -> bool:
    """Whether this family has a first-hand native field for this protocol."""
    return protocol in _FAMILY_DIALECTS.get(harness, {})


def translate_protocol(harness: str, protocol: str) -> tuple[str, str | None]:
    """(native field, dialect value) for one family/protocol, or typed refusal.

    Raises :class:`NativeMaterializationError` with ``PROTOCOL_UNSUPPORTED_BY_HARNESS``
    naming both the family and the protocol when the family has no pinned native
    field for it - the caller must then write nothing (no approximation).
    """
    if protocol not in CANONICAL_PROTOCOLS:
        raise NativeMaterializationError(
            "PROTOCOL_CANONICAL_UNKNOWN",
            f"{protocol!r} is not a canonical protocol", protocol=protocol)
    dialect = _FAMILY_DIALECTS.get(harness, {}).get(protocol)
    if dialect is None:
        raise NativeMaterializationError(
            "PROTOCOL_UNSUPPORTED_BY_HARNESS",
            f"{harness} has no first-hand native field for protocol {protocol!r}",
            harness=harness, protocol=protocol)
    return dialect


def render_codex_provider_section(*, provider: str, base_url: str, protocol: str,
                                  ) -> str:
    """The `[model_providers.<id>]` TOML block codex reads an endpoint from.

    Order-093 G1 point: the endpoint/protocol live *inside* the
    `[model_providers.<id>]` table, never at the top level - a key moved up one
    level is a different setting and must fail the family's gate. Idempotent: the
    same input yields byte-identical output (stable key order).
    """
    field, dialect = translate_protocol("codex", protocol)  # refuses unsupported
    lines = [
        f"[model_providers.{provider}]",
        f"name = \"{provider}\"",
        f"base_url = \"{base_url}\"",
        f"{field} = \"{dialect}\"",
        # The credential is a name the environment supplies, never a value.
        "env_key = \"CODEX_API_KEY\"",
    ]
    return "\n".join(lines) + "\n"


def render_pi_provider(*, provider: str, base_url: str, protocol: str) -> dict:
    """The `providers.<id>` object pi's models.json reads for one upstream."""
    field, dialect = translate_protocol("pi", protocol)
    return {
        "baseUrl": base_url,
        field: dialect,
        "apiKey": "$DEEPSEEK_API_KEY",  # a reference, never credential content
    }


def render_claude_env(*, base_url: str, protocol: str) -> dict:
    """claude's `env` block: anthropic-only; the endpoint carries the dialect.

    claude speaks `anthropic-messages` and nothing else here: a chat/responses/
    gemini provider is refused by :func:`translate_protocol` before this runs, so
    there is no way to write a wrong value into the file.
    """
    field, _dialect = translate_protocol("claude-code", protocol)
    return {"ANTHROPIC_BASE_URL": base_url}


def _limit_block(*, context: int | None, output: int | None) -> dict:
    """G8: a limit is written only where a fact exists - absent stays absent.

    The order-093 v2 rule: never backfill a default. If neither a user override
    nor an upstream fact is present for a limit, the key is simply not emitted.
    """
    block = {}
    if context is not None:
        block["context"] = context
    if output is not None:
        block["output"] = output
    return block


def render_opencode_provider(*, provider: str, base_url: str, protocol: str, model: str,
                             family: str = "opencode",
                             api_key_env: str = "DEEPSEEK_API_KEY",
                             context_limit: int | None = None,
                             output_limit: int | None = None) -> dict:
    """opencode/kilo's `provider.<id>` object (shared fork shape).

    G1 hierarchy: the endpoint is `options.baseURL`, the dialect is the
    provider-level `npm`, and limits sit at `models.<id>.limit` - none of them at
    the wrong level. `apiKey` is a `{env:...}` reference, never a value.
    """
    field, dialect = translate_protocol(family, protocol)
    model_entry: dict = {"name": f"{model}"}
    limits = _limit_block(context=context_limit, output=output_limit)
    if limits:
        model_entry["limit"] = limits
    return {
        field: dialect,
        "name": provider,
        "options": {"baseURL": base_url, "apiKey": "{env:%s}" % api_key_env},
        "models": {model: model_entry},
    }


def render_hermes_config(*, base_url: str, protocol: str, model: str,
                         provider: str = "custom",
                         api_key_env: str = "DEEPSEEK_API_KEY",
                         max_tokens: int | None = None) -> dict:
    """hermes' config.yaml document for one upstream.

    hermes records the endpoint twice (preferring `model.base_url`, with the
    provider block's own `api`) - both are written so nothing else can be
    contacted; the dialect is `providers.<id>.transport`. `max_tokens` is a limit
    and follows G8 (absent fact -> not written).
    """
    field, dialect = translate_protocol("hermes", protocol)
    model_block: dict = {"provider": provider, "default": model, "base_url": base_url}
    if max_tokens is not None:
        model_block["max_tokens"] = max_tokens
    return {
        "model": model_block,
        "providers": {
            provider: {
                "name": provider,
                "api": base_url,
                "key_env": api_key_env,
                field: dialect,
                "default_model": model,
                "models": {model: {}},
            },
        },
    }


def _pick_protocol(harness: str, frozen: Mapping[str, object]) -> tuple[str, str] | None:
    """First (protocol, base_url) the record declares an endpoint for, canonical order.

    Returns ``None`` when the record carries no endpoint facts - the caller then
    keeps the reviewed template bytes (093 G6: "no facts => zero regression").
    A protocol present but with no matching endpoint is skipped, never guessed.
    """
    protocols = frozen.get("protocols") or ()
    endpoints = frozen.get("endpoints") or {}
    for protocol in CANONICAL_PROTOCOLS:
        if protocol in protocols and protocol in endpoints:
            return protocol, str(endpoints[protocol])
    return None


def materialize_family(harness: str, frozen: Mapping[str, object]) -> dict | None:
    """Turn one frozen execution into a family's native endpoint/protocol write.

    This is the 093 stage-3 link: it consumes the protocol facts layer 1 (092)
    froze onto the execution (`protocols` + `endpoints`) and dispatches to the
    family's renderer, so a non-DeepSeek upstream's base URL and dialect actually
    reach the native file instead of the template constant.

    * no endpoint facts on the record -> ``None`` (caller keeps reviewed bytes);
    * a protocol the family cannot express -> ``translate_protocol`` raises
      ``PROTOCOL_UNSUPPORTED_BY_HARNESS`` (typed refusal; caller writes nothing);
    * output carries only the endpoint + dialect + env-reference key, never a
      secret value. v2 per-slot / limit facts are a later wiring; this wires the
      endpoint+protocol path the whole "second upstream is actually used" gate needs.
    """
    picked = _pick_protocol(harness, frozen)
    if picked is None:
        return None
    protocol, base_url = picked
    provider = str(frozen.get("provider") or "")
    model = str(frozen.get("model") or "")
    target = _NATIVE_TARGET.get(harness)
    if harness == "codex":
        content: object = render_codex_provider_section(
            provider=provider, base_url=base_url, protocol=protocol)
    elif harness == "pi":
        content = render_pi_provider(provider=provider, base_url=base_url, protocol=protocol)
    elif harness == "claude-code":
        content = render_claude_env(base_url=base_url, protocol=protocol)
    elif harness in ("opencode", "kilo"):
        content = render_opencode_provider(
            provider=provider, base_url=base_url, protocol=protocol, model=model,
            family=harness)
    elif harness == "hermes":
        content = render_hermes_config(base_url=base_url, protocol=protocol, model=model)
    else:
        # dsh has no pinned native protocol field -> not materializable here;
        # returning None keeps the template rather than guessing a dialect.
        return None
    return {"harness": harness, "target": target, "protocol": protocol,
            "base_url": base_url, "content": content}

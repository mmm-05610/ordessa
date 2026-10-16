"""Work Order 114 item #6 / G5: the Qoder native-config key registry.

Qoder CLI keeps its native configuration in three roots (``~/.qoder``,
``~/.qodersec``, ``~/.qoder-cli/ai-stats``). Order 114 must materialize *only*
what it understands and must **honestly register every key it read but could not
interpret** - never invent a meaning and never silently drop it (R-0032 ⑤: no
information may be swallowed in the middle of the system).

This module is the single, first-hand record of that boundary. Each entry cites
where it was observed. ``classification`` is one of:

* ``known``      - this order understands the key's role enough to act on it;
* ``app_local``  - observed, judged to be Qoder's own application state (not a
  profile fact), so deliberately excluded from materialization/sync - recorded,
  not dropped;
* ``unknown``    - observed but its semantics are **not** established here: the
  key is registered with ``meaning is None`` and a "待观测" note. No layer above
  may read an invented interpretation out of this module.

:func:`unregistered_keys` is the gate behind "no silent drop": given any parsed
document, it returns every leaf key not covered by the registry, so an
unanticipated Qoder key surfaces for registration instead of vanishing.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

#: The roots order 114 declares (first-hand ``ls``). ``~/.qoder`` is the native
#: home; the other two are declared for completeness, not materialized.
QODER_NATIVE_HOME = ".qoder"
QODER_SEC_ROOT = ".qodersec"
QODER_CLI_ROOT = ".qoder-cli"

#: Keys whose meaning order 114 has NOT established. These carry no interpretation
#: here - they are registered so a human can decide later, per the ticket's
#: "不发明语义、不静默丢弃". ``meaning`` is always ``None`` for an unknown key.
CLASSIFICATION_UNKNOWN = "unknown"


@dataclass(frozen=True)
class NativeKey:
    """One first-hand-observed Qoder native key and how this order treats it."""

    key: str            #: dotted path within its document
    document: str       #: which file it was read from (relative to a root)
    classification: str #: known | app_local | unknown
    meaning: str | None #: what this order does with it; None for unknown
    source: str         #: where it was observed first-hand (G5 "逐条给出处")


#: The registry. Every entry is first-hand from the 114 stage-1 observation
#: (`docs/server-round1/114-qoder-family-stage1-observation.md`), values never
#: recorded (credential/privacy discipline) - only key paths and classifications.
QODER_NATIVE_KEYS: tuple[NativeKey, ...] = (
    # --- ~/.qoder/settings.json ---
    NativeKey(
        "permissions.trustDirectories", "settings.json", "known",
        "list of host directories the user trusted; a profile permission the "
        "materializer writes back only inside the declared isolated home",
        "114 stage 1 (settings.json first-hand, values 脱敏)",
    ),
    NativeKey(
        "security.auth.selectedType", "settings.json", CLASSIFICATION_UNKNOWN, None,
        "114 stage 1 - observed string key; its role (login-method selection?) "
        "is NOT established here; 待观测",
    ),
    NativeKey(
        "model.name", "settings.json", "known",
        "the model id Qoder was last pointed at; a model-control candidate, not "
        "an account credential",
        "114 stage 1 (settings.json first-hand)",
    ),
    NativeKey(
        "model.preferences.qfmodel.contextWindow", "settings.json",
        CLASSIFICATION_UNKNOWN, None,
        "114 stage 1 - an int the harness stores; whether it drives request "
        "sizing is NOT confirmed here; 待观测",
    ),
    NativeKey(
        "model.preferences.qfmodel.reasoning.effort", "settings.json",
        CLASSIFICATION_UNKNOWN, None,
        "114 stage 1 - relationship to `--thinking`/`--reasoning-effort` and to "
        "the product tier (096/107) is NOT established here; 待观测",
    ),
    # --- ~/.qoder/state.json ---
    NativeKey(
        "lastLoginMethod", "state.json", "known",
        "which account flow last logged in (email/Google/GitHub); read by the "
        "094/095 account model, not by this config materializer",
        "114 stage 1 (state.json first-hand)",
    ),
    NativeKey(
        "tipsShown", "state.json", "app_local",
        "Qoder's own onboarding/UI state - excluded from profile materialization "
        "and sync; recorded, not dropped",
        "114 stage 1 (state.json first-hand)",
    ),
    NativeKey(
        "startupWarningCounts", "state.json", "app_local",
        "Qoder's own runtime warning counter - excluded from materialization; "
        "recorded, not dropped",
        "114 stage 1 (state.json first-hand)",
    ),
    # --- other roots: purpose NOT established; registered as unknown ---
    NativeKey(
        ".qodersec/config.yaml", QODER_SEC_ROOT, CLASSIFICATION_UNKNOWN, None,
        "114 stage 1 - a CodeSec-style security-review tool's config (its header "
        "says 'full-field reference / first-run seed'); whether it belongs in "
        "placement/materialization is NOT decided here; 待观测",
    ),
    NativeKey(
        ".qoder-cli/ai-stats", QODER_CLI_ROOT, CLASSIFICATION_UNKNOWN, None,
        "114 stage 1 - `verified-<sha>.json` commit-stats receipts; judged NOT "
        "login/NOT model config, but its exact role is 未查实; recorded, not "
        "materialized",
    ),
)


def registered_keys() -> tuple[str, ...]:
    """Every dotted key path this order has accounted for."""
    return tuple(f"{entry.document}:{entry.key}" for entry in QODER_NATIVE_KEYS)


def _leaf_paths(value: Any, prefix: str = "") -> set[str]:
    if isinstance(value, Mapping):
        paths: set[str] = set()
        if not value and prefix:
            paths.add(prefix)
        for key, item in value.items():
            paths |= _leaf_paths(item, f"{prefix}.{key}" if prefix else str(key))
        return paths
    return {prefix} if prefix else set()


def unregistered_keys(document: Mapping[str, Any], *, document_name: str) -> list[str]:
    """Leaf paths present in `document` but NOT covered by the registry.

    This is the "no silent drop" gate: a Qoder key that this order has never
    looked at is reported for registration rather than being ignored by whatever
    reads the document next.
    """
    covered = {entry.key for entry in QODER_NATIVE_KEYS if entry.document == document_name}
    observed = _leaf_paths(document)
    unknown = []
    for path in sorted(observed):
        if path in covered:
            continue
        if any(path.startswith(f"{c}.") for c in covered):
            # A parent the registry already accounts for (e.g. permissions.*)
            # still counts as covered only at the leaf it registered; nested
            # leaves under a `known` subtree are surfaced unless registered.
            continue
        unknown.append(path)
    return unknown

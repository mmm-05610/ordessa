"""Order 60 B: per-tool permission rules, resolved the one way they can be.

The model is the desktop's: a rule names a *tool key*, an optional glob
pattern, and one of three actions (`allow` / `ask` / `deny`). Rules are
evaluated in order and the **last matching rule wins** - the only ordering
that lets a broad rule be narrowed by a later specific one without inventing
priority tables. Three further rules are the order's:

* **deny stays highest when nothing later matches**: resolution walks the list,
  so a later `allow` can widen what an earlier `deny` refused (that is what
  last-match-wins means); what cannot happen is a rule *inheriting* a widening
  the user never wrote - an unmatched (key, target) falls back to the preset
  in force, never to `allow`;
* **presets are starting points, not magic**: `full-access` / `default` /
  `plan` expand to explicit rule sets, and a per-tool rule may override any of
  them afterwards;
* **unknown keys and actions refuse typed** - a typo must not read as "no
  rule", because "no rule" is a security-relevant default.

This module resolves *posture only*. Whether a posture is even available for an
execution stays where it has always been: the capability gate compares the
harness's declaration with what the execution observed, and a rule can never
grant a tool the harness did not declare.
"""
from __future__ import annotations

import fnmatch
import re
from typing import Any, Iterable, Mapping, Sequence

#: The tool keys the desktop's reference names. The set is closed: a key that
#: is not here is refused, because "no rule for it" and "a typo for another
#: key" must not look the same.
TOOL_KEYS = ("read", "edit", "bash", "task", "external_directory", "webfetch", "skill")
ACTIONS = ("allow", "ask", "deny")
#: What an unmatched (key, target) resolves to when a preset is in force.
PRESET_ACTIONS = {"full-access": "allow", "default": "ask", "plan": "ask"}
#: Plan mode's deliberate exceptions: reading is free, changing is not.
PRESET_RULES: dict[str, tuple[tuple[str, str | None, str], ...]] = {
    "full-access": (),
    "default": (),
    "plan": (
        ("edit", None, "deny"),
        ("bash", None, "deny"),
        ("external_directory", None, "deny"),
    ),
}
MAX_RULES = 64
#: A glob is any bounded printable text: command patterns carry spaces and
#: quotes, so only control characters and unbounded length are refused.
_PATTERN_OK = re.compile(r"[^\x00-\x1f\x7f]{1,128}\Z")


class PermissionRuleError(RuntimeError):
    """A typed refusal of one rule or rule set."""

    def __init__(self, code: str, message: str, *, index: int | None = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message
        self.index = index


def _validate_rule(raw: Any, index: int) -> dict[str, str | None]:
    if not isinstance(raw, Mapping):
        raise PermissionRuleError("PERMISSION_RULE_INVALID", "a rule is an object", index=index)
    if set(raw) - {"key", "pattern", "action"}:
        raise PermissionRuleError(
            "PERMISSION_RULE_INVALID",
            f"unknown rule fields: {sorted(set(raw) - {'key', 'pattern', 'action'})}",
            index=index,
        )
    key = raw.get("key")
    if key not in TOOL_KEYS:
        raise PermissionRuleError(
            "PERMISSION_KEY_UNSUPPORTED",
            f"{key!r} is not a tool key (declared: {sorted(TOOL_KEYS)})",
            index=index,
        )
    action = raw.get("action")
    if action not in ACTIONS:
        raise PermissionRuleError(
            "PERMISSION_ACTION_UNSUPPORTED",
            f"{action!r} is not an action (declared: {sorted(ACTIONS)})",
            index=index,
        )
    pattern = raw.get("pattern")
    if pattern is not None:
        if not isinstance(pattern, str) or _PATTERN_OK.fullmatch(pattern) is None:
            raise PermissionRuleError(
                "PERMISSION_PATTERN_INVALID",
                "a pattern must be bounded printable text",
                index=index,
            )
    return {"key": key, "pattern": pattern, "action": action}


def validate_rules(rules: Iterable[Any]) -> list[dict[str, str | None]]:
    """Validate a rule set in order; every refusal carries the rule's index."""
    if isinstance(rules, (str, bytes)) or not isinstance(rules, Sequence):
        raise PermissionRuleError("PERMISSION_RULE_INVALID", "rules must be a list")
    if len(rules) > MAX_RULES:
        raise PermissionRuleError(
            "PERMISSION_RULE_INVALID", f"at most {MAX_RULES} rules are accepted")
    return [_validate_rule(raw, index) for index, raw in enumerate(rules)]


def preset_rules(preset: str) -> list[dict[str, str | None]]:
    """The preset's explicit rules (a starting point the user may override)."""
    if preset not in PRESET_RULES:
        raise PermissionRuleError(
            "PERMISSION_PRESET_UNSUPPORTED",
            f"{preset!r} is not a preset (declared: {sorted(PRESET_RULES)})",
        )
    return [
        {"key": key, "pattern": pattern, "action": action}
        for key, pattern, action in PRESET_RULES[preset]
    ]


def effective_rules(preset: str, overrides: Iterable[Any]) -> list[dict[str, str | None]]:
    """The preset expanded, then the user's rules appended in order."""
    return preset_rules(preset) + validate_rules(overrides)


def _matches(rule: Mapping[str, Any], key: str, target: str | None) -> bool:
    if rule["key"] != key:
        return False
    pattern = rule.get("pattern")
    if pattern is None:
        return True
    if target is None:
        # A pattern rule cannot speak about a target it was not given; the
        # unmatched case falls through to the preset, never to `allow`.
        return False
    return fnmatch.fnmatchcase(target, pattern)


def resolve(
    rules: Sequence[Mapping[str, Any]], *, key: str, target: str | None = None,
    preset: str = "default",
) -> str:
    """The action in force for one (key, target): last match wins, else preset.

    ``key`` is validated here as well, so a caller cannot dodge the closed key
    set by resolving directly.
    """
    if key not in TOOL_KEYS:
        raise PermissionRuleError(
            "PERMISSION_KEY_UNSUPPORTED",
            f"{key!r} is not a tool key (declared: {sorted(TOOL_KEYS)})",
        )
    if preset not in PRESET_ACTIONS:
        raise PermissionRuleError(
            "PERMISSION_PRESET_UNSUPPORTED", f"{preset!r} is not a preset",
        )
    action = PRESET_ACTIONS[preset]
    for rule in rules:
        if _matches(rule, key, target):
            action = str(rule["action"])
    return action


def resolve_all(
    rules: Sequence[Mapping[str, Any]], *, preset: str = "default",
    targets: Mapping[str, Sequence[str]] | None = None,
) -> dict[str, Any]:
    """The posture that goes into a frozen execution configuration.

    Without `targets`, each key resolves to one action (its targetless rule or
    the preset). With targets, each (key, target) pair resolves too, so the
    materialiser can state the per-path posture for the keys that take one.
    """
    posture: dict[str, Any] = {
        "preset": preset,
        "keys": {key: resolve(rules, key=key, preset=preset) for key in TOOL_KEYS},
    }
    if targets:
        posture["targets"] = {
            key: {
                target: resolve(rules, key=key, target=target, preset=preset)
                for target in targets.get(key, ())
            }
            for key in TOOL_KEYS
            if targets.get(key)
        }
    return posture

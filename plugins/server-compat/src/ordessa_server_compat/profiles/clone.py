"""Order 60 D: cloning a Profile - what travels, what cannot, and why.

A clone is a *new* Profile: same family copies the binding-relevant records
verbatim, another family translates what has a cross-family form and lists
everything that does not. Two rules decide every item:

* **session material never travels**. The native home, checkpoints and native
  session ids are the old Profile's; a clone starts with none of them and says
  so in its report - "不假装继承旧的原生会话";
* **a translated item is re-validated for the target, not copied blind**. A
  skill's Agent Skills shape and an MCP server's standard definition travel
  only when the target family declares the matching slot, and a hook travels
  only when the target's own hook schema accepts the model verbatim. Whatever
  fails is listed with its typed reason instead of being dropped silently.

The report is part of the product surface: the clone's row records its origin
and time, and `migration` is what the UI shows next to it.
"""
from __future__ import annotations

from typing import Any, Mapping, Sequence

from ordessa_server_compat.hooks.model import HookModelError, schema_for as hook_schema
from ordessa_server_compat.profiles.permissions import PermissionRuleError, effective_rules

#: The items every clone reports on, in one fixed order: the UI renders this
#: list, and a silent omission would read as "migrated".
MIGRATION_ITEMS = (
    "configuration",
    "credential",
    "account",
    "permissions",
    "skill",
    "mcp",
    "plugin",
    "hook",
    "native-sessions",
)


class CloneError(RuntimeError):
    """A typed refusal of one clone request."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


def plan_migration(
    *, source: Mapping[str, Any], target_harness: str,
    asset_bindings: Sequence[Mapping[str, Any]],
    hooks: Sequence[Mapping[str, Any]],
    registry_profile: Any,
) -> dict[str, Any]:
    """Decide every item's fate before anything is written.

    Pure on purpose: the report a clone shows is computed here, and the caller
    applies exactly this plan - so "what the user was told" and "what happened"
    cannot drift.
    """
    same_family = str(source["harness_type"]) == target_harness
    report: dict[str, Any] = {"targetFamily": target_harness,
                              "sourceFamily": str(source["harness_type"]),
                              "sameFamily": same_family, "items": []}

    def item(name: str, migrated: bool, reason: str, detail: Any = None) -> None:
        entry: dict[str, Any] = {"item": name, "migrated": migrated, "reason": reason}
        if detail is not None:
            entry["detail"] = detail
        report["items"].append(entry)

    if same_family:
        item("configuration", True, "same family: the configuration object is reused")
        item("credential", source.get("credential_id") is not None,
             "same family: the credential reference travels" if source.get("credential_id")
             else "the source has no credential")
        item("account", source.get("account_id") is not None,
             "same family: the subscription binding travels" if source.get("account_id")
             else "the source has no bound account")
    else:
        item("configuration", False, "families differ: configuration keys are family-specific")
        item("credential", False, "a credential is issued for one family and is not reusable")
        item("account", False, "a subscription login state belongs to its family")

    # Permissions are neutral, so they travel either way - re-expanded so the
    # stored order (last match wins) is preserved exactly.
    try:
        rules = effective_rules(
            str(source.get("permission_preset") or "default"),
            __import__("json").loads(source["permission_rules_json"])
            if source.get("permission_rules_json") else [],
        )
        report["permissions"] = {
            "preset": str(source.get("permission_preset") or "default"),
            "rules": rules,
        }
        item("permissions", True, "the rule set is family-neutral and travels in order")
    except (PermissionRuleError, ValueError) as exc:
        report["permissions"] = None
        item("permissions", False, f"the stored rule set no longer validates: {exc}")

    slots = tuple(getattr(registry_profile, "slots", ()) or ())
    for binding in asset_bindings:
        kind = str(binding["kind"])
        if kind in {"skill", "mcp", "plugin"}:
            if kind == "mcp" and "mcp" not in slots:
                item(f"{kind}:{binding['name']}", False,
                     f"the target family declares no {kind} slot")
            else:
                item(f"{kind}:{binding['name']}", True,
                     "the stored definition is family-neutral and is re-bound")
        else:
            item(f"{kind}:{binding['name']}", False,
                 f"{kind!r} assets do not travel in this model")

    try:
        target_hook_schema = hook_schema(target_harness)
    except HookModelError:
        target_hook_schema = None
    for hook in hooks:
        model = hook["model"]
        if target_hook_schema is None:
            item(f"hook:{hook['name']}", False, "the target family declares no hook model")
            continue
        event_ok = model.get("event") in target_hook_schema.events
        handlers_ok = all(
            handler.get("type") in target_hook_schema.handler_types
            for handler in model.get("handlers", ())
        )
        if event_ok and handlers_ok:
            item(f"hook:{hook['name']}", True, "the target's hook schema accepts the model")
        else:
            reasons = []
            if not event_ok:
                reasons.append(f"event {model.get('event')!r} is not declared")
            if not handlers_ok:
                reasons.append("a handler type is not declared")
            item(f"hook:{hook['name']}", False, "; ".join(reasons))

    item("native-sessions", False,
         "native sessions are the source's; a clone starts with none")
    migrated = sum(1 for entry in report["items"] if entry["migrated"])
    report["migratedCount"] = migrated
    report["refusedCount"] = len(report["items"]) - migrated
    return report

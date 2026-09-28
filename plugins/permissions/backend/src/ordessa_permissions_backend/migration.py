"""T012: the legacy Profile permission rules imported as USER INTENT, read-only.

The legacy store (mirrored here as *stored-data vocabulary* only - this module
never imports the compat engine) resolved rules **last-match-wins**: a later
looser rule reversed an earlier stricter one, and the `full-access` preset
fell back to `allow`. The new engine (data-model §规则合成 4/5) is
order-irrelevant and strictest-wins at equal priority, so such entries are NOT
provably equivalent. The migrator's contract, per plan §迁移:

* fidelity first: the stored values are read, never mutated or deleted, and
  every result carries them back verbatim (`original`, `read_back`);
* equivalent entries map into `ordessa_permissions_api.PermissionIntent`
  rules (USER scope - a Profile's intent can only narrow);
* the migration never fabricates a `PolicyCeiling` and never derives an
  admin bound from profile data - absence of a trusted ceiling stays
  "unverified", which is the opposite of "no limit", so nothing imported
  here can stand in for one;
* anything not provably equivalent - an unknown key/action/shape, a pattern
  without a bounded literal, a later looser rule for the same key (the
  deny-reversal case), a duplicate, or a preset whose fallback posture cannot
  be represented - is marked `needsReview`, kept OUT of the intent, and
  therefore resolves to ask/deny, never to an imported allow;
* idempotent: importing the same stored values twice answers the same intent
  revision and digest; changed stored values append a new revision - the
  history is never overwritten.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from typing import Any, Callable, Mapping

from ordessa_permissions_api import (
    PermissionIntent,
    PolicyRefusal,
    Scope,
    TargetMatcher,
    TypedRule,
)

from .policies import PolicyRepository

__all__ = [
    "LEGACY_ACTIONS",
    "LEGACY_PRESET_ACTIONS",
    "LEGACY_PRESET_RULES",
    "LEGACY_TOOL_KEYS",
    "MAX_LEGACY_RULES",
    "LegacyImportIssue",
    "LegacyProfileRulesMigration",
    "LegacyRuleImport",
]

#: The closed legacy vocabulary, transcribed from the stored-data format so
#: historical rows keep their identifiers (FR-10). It is data documentation,
#: not an engine: nothing in this module resolves a decision the old way.
LEGACY_TOOL_KEYS: tuple[str, ...] = (
    "read", "edit", "bash", "task", "external_directory", "webfetch", "skill")
LEGACY_ACTIONS: tuple[str, ...] = ("allow", "ask", "deny")
LEGACY_PRESET_ACTIONS: Mapping[str, str] = {
    "full-access": "allow", "default": "ask", "plan": "ask"}
LEGACY_PRESET_RULES: Mapping[str, tuple[tuple[str, str | None, str], ...]] = {
    "full-access": (),
    "default": (),
    "plan": (
        ("edit", None, "deny"),
        ("bash", None, "deny"),
        ("external_directory", None, "deny"),
    ),
}
MAX_LEGACY_RULES = 64
_STRICTNESS = {"allow": 1, "ask": 2, "deny": 3}
#: The new engine's posture for an unmatched operation is `ask` (synthesis
#: rule 3); presets that fell back to `ask` need no imported rule, while a
#: preset that fell back to `allow` cannot be represented by a narrowing-only
#: intent at all - that finding is flagged, never imported.
NEW_FALLBACK_ACTION = "ask"
_PRESET_MARKER = object()  # sentinel index for preset-expanded entries


@dataclass(frozen=True)
class LegacyImportIssue:
    """One needsReview finding: which stored entry (`None` - the record
    itself) and why. A flagged entry never resolves to allow."""

    index: int | None
    reason: str
    original: Any = None


@dataclass(frozen=True)
class LegacyRuleImport:
    """The outcome of one read-only import."""

    profile_id: str
    intent: PermissionIntent | None
    intent_digest: str | None
    imported_indices: tuple[int, ...]
    needs_review: tuple[LegacyImportIssue, ...]
    original: Mapping[str, Any]
    ceiling_created: bool = False  # structurally impossible; stated for the gate

    @property
    def fully_equivalent(self) -> bool:
        return not self.needs_review and self.intent is not None


def _intent_id(profile_id: str) -> str:
    return f"legacy-profile:{profile_id}"


def _stored_rule(rule: Any) -> dict[str, Any]:
    """The canonical stored spelling of one rule (typed or dict), the digest
    input: key, action, pattern - nothing else can move the digest."""
    if isinstance(rule, TypedRule):
        return {"key": rule.tool.key, "action": rule.action.value,
                "pattern": None if rule.target is None else rule.target.pattern}
    return {"key": rule["key"], "action": rule["action"], "pattern": rule.get("pattern")}


def _digest(profile_id: str, harness_id: str, rules: list[dict[str, Any]]) -> str:
    canonical = json.dumps({"profile": profile_id, "harness": harness_id, "rules": rules},
                           sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _entry_problem(item: Any) -> str | None:
    if not isinstance(item, Mapping):
        return "the entry is not a rule object; it is not imported"
    unknown = set(item) - {"key", "pattern", "action"}
    if unknown:
        return f"unknown legacy rule fields {sorted(unknown)}; not imported"
    key = item.get("key")
    if key not in LEGACY_TOOL_KEYS:
        return (f"{key!r} is not a legacy tool key; the vocabulary is closed"
                " and nothing inherits")
    action = item.get("action")
    if action not in LEGACY_ACTIONS:
        return f"{action!r} is not a legacy action; not imported"
    pattern = item.get("pattern")
    if pattern is not None and (not isinstance(pattern, str) or not pattern or len(pattern) > 128
                                or any(ord(char) < 0x20 or ord(char) == 0x7f
                                       for char in pattern)):
        return "the pattern is not bounded printable text; not imported"
    return None


class LegacyProfileRulesMigration:
    """Read-only importer: analyzes stored values and stores the resulting
    USER-scope intent in the policy store. It never touches the legacy rows,
    never writes a ceiling, and never resolves anything to allow itself."""

    def __init__(self, policies: PolicyRepository) -> None:
        self._policies = policies

    # -- analysis (pure over the stored values) --------------------------------------

    def analyze(self, row: Mapping[str, Any]) -> LegacyRuleImport:
        if not isinstance(row, Mapping):
            raise TypeError("a legacy profile row must be a mapping of stored values")
        profile_id = str(row.get("id") or "")
        harness_id = str(row.get("harness_type") or "")
        preset = row.get("permission_preset")
        rules_json = row.get("permission_rules_json")
        original = {"permission_preset": preset, "permission_rules_json": rules_json}
        review: list[LegacyImportIssue] = []

        if not profile_id:
            review.append(LegacyImportIssue(None, "the profile row carries no id"))
            return LegacyRuleImport("", None, None, (), tuple(review), original)
        if not harness_id:
            # PermissionIntent requires a harness id; inventing one would
            # attribute rules to an authority nobody observed.
            review.append(LegacyImportIssue(
                None, "the profile row carries no harness type; the intent"
                      " cannot be attributed to a harness"))
            return LegacyRuleImport(profile_id, None, None, (), tuple(review), original)

        entries: list[tuple[Any, dict[str, Any]]] = []
        preset_key = preset if isinstance(preset, str) and preset else "default"
        if preset_key not in LEGACY_PRESET_ACTIONS:
            review.append(LegacyImportIssue(
                None, f"unknown legacy preset {preset_key!r}; the fallback posture"
                      " cannot be imported and nothing falls back to allow",
                preset_key))
        else:
            if LEGACY_PRESET_ACTIONS[preset_key] != NEW_FALLBACK_ACTION:
                review.append(LegacyImportIssue(
                    None, f"preset {preset_key!r} falls back to"
                          f" {LEGACY_PRESET_ACTIONS[preset_key]!r}, which a"
                          " narrowing-only user intent cannot represent; it is"
                          " never imported as an allow-all rule", preset_key))
            for key, pattern, action in LEGACY_PRESET_RULES.get(preset_key, ()):
                entries.append((_PRESET_MARKER,
                                {"key": key, "pattern": pattern, "action": action}))

        parsed, structural = self._parse_rules(rules_json)
        review.extend(structural)
        entries.extend(parsed)

        kept, imported, ordering_review = self._select(entries)
        review.extend(ordering_review)

        intent: PermissionIntent | None = None
        intent_digest: str | None = None
        try:
            intent = self._build_intent(profile_id, harness_id, kept)
            intent_digest = _digest(profile_id, harness_id, [_stored_rule(r) for r in kept])
        except PolicyRefusal as refusal:
            review.append(LegacyImportIssue(
                None, f"the importable rule set was refused: {refusal.human_readable[:180]}"
                      " - nothing is imported as an allow"))
            intent, intent_digest = None, None
        return LegacyRuleImport(profile_id, intent, intent_digest, imported,
                                tuple(review), original)

    @staticmethod
    def _parse_rules(rules_json: Any):
        if rules_json in (None, ""):
            return [], []
        if isinstance(rules_json, str):
            try:
                raw = json.loads(rules_json)
            except ValueError:
                return [], [LegacyImportIssue(
                    None, "the stored rules json is not parseable; no rule is"
                          " imported, so nothing can resolve to allow", rules_json)]
        elif isinstance(rules_json, list):
            raw = rules_json
        else:
            return [], [LegacyImportIssue(
                None, "the stored rules are not a list; nothing is imported",
                type(rules_json).__name__)]
        if not isinstance(raw, list):
            return [], [LegacyImportIssue(
                None, "the stored rules are not a list; nothing is imported",
                type(raw).__name__)]
        if len(raw) > MAX_LEGACY_RULES:
            return [], [LegacyImportIssue(
                None, f"more than the legacy cap of {MAX_LEGACY_RULES} rules"
                      " cannot be imported as one intent", len(raw))]
        return [(index, item) for index, item in enumerate(raw)], []

    @staticmethod
    def _select(entries):
        """Validate each entry, then flag the last-match-wins reversals."""
        review: list[LegacyImportIssue] = []
        valid: list[tuple[Any, dict[str, Any]]] = []
        seen: set[tuple[str, Any, str]] = set()
        for index, item in entries:
            reason = _entry_problem(item)
            if reason is not None:
                review.append(LegacyImportIssue(
                    None if index is _PRESET_MARKER else index, reason,
                    dict(item) if isinstance(item, Mapping) else repr(item)))
                continue
            identity = (str(item["key"]), item.get("pattern"), str(item["action"]))
            if identity in seen:
                review.append(LegacyImportIssue(
                    None if index is _PRESET_MARKER else index,
                    "duplicate of an already-imported rule; the typed model"
                    " refuses duplicate entries", dict(item)))
                continue
            seen.add(identity)
            valid.append((index, dict(item)))
        # The reversal scan runs over the FULL legacy order: preset expansions
        # first (the legacy engine expanded the preset, then appended the
        # user's rules), then the user entries in stored order.
        kept: list[dict[str, Any]] = []
        imported: list[int] = []
        for position, (index, rule) in enumerate(valid):
            reverses_earlier = any(
                earlier["key"] == rule["key"]
                and _STRICTNESS[earlier["action"]] > _STRICTNESS[rule["action"]]
                for _, earlier in valid[:position])
            if reverses_earlier:
                review.append(LegacyImportIssue(
                    None if index is _PRESET_MARKER else index,
                    "the last-match-wins engine would let this later looser rule"
                    " reverse an earlier stricter rule for the same key (patterns"
                    " cannot be proven disjoint); equivalence is not provable, so"
                    " it needs review and is never imported as an allow", rule))
                continue
            if rule.get("pattern") is not None:
                # A legacy glob without a bounded literal ("*") is not a
                # target the typed model can speak about; flag, never widen.
                try:
                    TargetMatcher.glob(rule["pattern"])
                except PolicyRefusal as refusal:
                    review.append(LegacyImportIssue(
                        None if index is _PRESET_MARKER else index,
                        f"the pattern is not a bounded target pattern:"
                        f" {refusal.code}; not imported", rule))
                    continue
            kept.append(rule)
            if index is not _PRESET_MARKER:
                imported.append(index)
        return kept, tuple(imported), review

    def _build_intent(self, profile_id: str, harness_id: str,
                      rules: list[dict[str, Any]]) -> PermissionIntent:
        typed = [TypedRule.of(key=rule["key"], action=rule["action"],
                              pattern=rule.get("pattern"), priority=0,
                              scope=Scope.USER.value) for rule in rules]
        return PermissionIntent.of(intent_id=_intent_id(profile_id), revision=1,
                                   harness_id=harness_id, scope=Scope.USER, rules=typed)

    # -- storage (append-only revisions; never the legacy rows) ------------------------

    def import_profile(self, row: Mapping[str, Any]) -> LegacyRuleImport:
        plan = self.analyze(row)
        # Surface the findings where a reader can reach them: the Settings
        # region's `permissions.policy.describe` reports these rows. A finding
        # flags only; it can never import a rule or relax anything, and an
        # import that produced no intent still records why it did.
        self._policies.record_review_findings(
            _intent_id(plan.profile_id),
            [(issue.index, issue.reason) for issue in plan.needs_review])
        if plan.intent is None:
            return plan
        rules = [_stored_rule(rule) for rule in plan.intent.rules]
        digest = _digest(plan.profile_id, plan.intent.harness_id, rules)
        current = self._policies.intent_current(_intent_id(plan.profile_id))
        if current is not None:
            current_digest = _digest(plan.profile_id, current.harness_id,
                                     [_stored_rule(rule) for rule in current.rules])
            if current_digest == digest:
                # idempotent: the same stored values answer the same revision
                # and digest; a re-import is not a second revision.
                return LegacyRuleImport(plan.profile_id, current, digest,
                                        plan.imported_indices, plan.needs_review,
                                        plan.original)
            intent = replace(plan.intent, revision=current.revision + 1)
        else:
            intent = plan.intent
        self._policies.store_intent(intent)
        return LegacyRuleImport(plan.profile_id, intent, digest,
                                plan.imported_indices, plan.needs_review, plan.original)

    def import_from_store(self, read_row: Callable[[str], Mapping[str, Any] | None],
                          profile_id: str) -> LegacyRuleImport:
        row = read_row(profile_id)
        if row is None:
            # A missing stored row is refused typed: the migration never
            # fabricates an intent nobody stored.
            raise KeyError(f"no legacy profile row for {profile_id!r}")
        return self.import_profile(row)

    def read_back(self, read_row: Callable[[str], Mapping[str, Any] | None],
                  profile_id: str) -> Mapping[str, Any] | None:
        """The reversibility surface: re-reads the untouched legacy values from
        the caller's reader. The migration never wrote them, so this answers
        exactly what the original row still holds."""
        row = read_row(profile_id)
        if row is None:
            return None
        return {"permission_preset": row.get("permission_preset"),
                "permission_rules_json": row.get("permission_rules_json")}

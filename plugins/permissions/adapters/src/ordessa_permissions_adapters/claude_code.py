"""ClaudeAdapter - claude-code permission policy adapter (T03).

Writable native surface, measured on the pinned artifact: the only settings
paths this layer may write are `permissions.ask` and `permissions.deny`
(`_CLAUDE_WRITABLE_PATHS`), with the first-hand tool-name map
(`_CLAUDE_SETTINGS_TOOLS`) - see
`docs/design/safety-controls/harness-adapters.md` row "Claude Code" and the
compat measurements in `posture_config.py:52-70` (file paths below in
`EVIDENCE`). `permissions.allow` and `permissions.defaultMode` are *loosening*
knobs deliberately kept unwritable (measured: both can be overridden by a
later-loaded source), so a claude intent that needs one - including any
`desiredMode` such as `bypassPermissions`, `auto`, `acceptEdits`, `plan` or
`default` - is a typed `PERMISSION_POSTURE_UNEXPRESSIBLE` refusal (FR-03: no
silent downgrade, never "write it anyway").

EVIDENCE (file:line, read 2026-09-28):
- plugins/server-compat/.../profiles/posture_config.py:56-63  tool-name map
- plugins/server-compat/.../profiles/posture_config.py:65-70  writable paths
- plugins/server-compat/.../profiles/posture_config.py:149-158 unexpressible
  refusal for keys with no pinned rule name (external_directory)
- plugins/harness/.../harnesses.toml:246-251 the `request_permission` ACP
  method is documented for dsh, and deliberately NOT declared as a claude
  runtime capability (claude capabilities, harnesses.toml:89).
"""
from __future__ import annotations

from typing import Any, Mapping

from ordessa_permissions_api import RuleAction

from .base import BaseBrandAdapter
from .codes import AdapterCode
from .dto import PolicyCompileSnapshot
from .ranges import NativeVersionRange
from .results import CompileRefusal, CompileResult, CompiledIntentSet

__all__ = ["ClaudeAdapter"]

#: first-hand names of the pinned settings surface (posture_config.py:56-63).
CLAUDE_SETTINGS_TOOLS: Mapping[str, tuple[str, ...]] = {
    "read": ("Read", "Glob", "Grep"),
    "edit": ("Edit", "Write", "NotebookEdit"),
    "bash": ("Bash",),
    "task": ("Task",),
    "webfetch": ("WebFetch", "WebSearch"),
    "skill": ("Skill",),
    # `external_directory` has no rule name of its own: it is directory-scoped,
    # and this adapter does not invent a syntax for it (posture_config.py:53-55).
}

_WRITABLE_PATHS = ("permissions.ask", "permissions.deny")


class ClaudeAdapter(BaseBrandAdapter):
    adapter_id = "permissions.policy-adapter.claude-code"
    harness_id = "claude-code"
    version_range = NativeVersionRange(minimum="0.81.2", maximum="0.82.0")
    capability_evidence = ("posture_config.py:56-70 settings surface measured "
                           "on pinned artifact; harnesses.toml:89-99 claude family pin")

    # the writable surface is tool-name lists only - per-target rule syntax is
    # not pinned in this tree, so enforcement is expressible per tool key:
    def expressible_actions(self) -> Mapping[str, Any]:
        return {"read": frozenset({"ask", "deny"}),
                "edit": frozenset({"ask", "deny"}),
                "bash": frozenset({"ask", "deny"}),
                "task": frozenset({"ask", "deny"}),
                "webfetch": frozenset({"ask", "deny"}),
                "skill": frozenset({"ask", "deny"}),
                "external_directory": frozenset()}

    def native_tool_names(self, key: str) -> tuple[str, ...]:
        return CLAUDE_SETTINGS_TOOLS.get(key, ())

    def verifiable_fields(self) -> frozenset[str]:
        return frozenset(_WRITABLE_PATHS)

    def _assemble(self, actions: Mapping[str, RuleAction],
                  snapshot: PolicyCompileSnapshot, mode: Any) -> CompileResult:
        ask: set[str] = set()
        deny: set[str] = set()
        notes: list[str] = []
        for key, action in actions.items():
            tools = CLAUDE_SETTINGS_TOOLS.get(key)
            if tools is None:
                if action is RuleAction.ALLOW:
                    notes.append(f"{key}=allow needs no write; the family "
                                 "default applies")
                    continue
                # 反例 (c) shape: a narrower ask than any writable knob can carry
                return CompileRefusal(
                    AdapterCode.PERMISSION_POSTURE_UNEXPRESSIBLE,
                    source=f"{self.adapter_id}.compilePolicy",
                    target=f"claude settings has no pinned rule name for "
                           f"{key}={action.value}")
            if action is RuleAction.ALLOW:
                # Writing these names into permissions.allow would pre-approve
                # them - the loosening knob stays untouched (posture_config
                # .py:65-69); an allow is expressed by *not* restricting, so it
                # is simply absent from the output.
                notes.append(f"{key}=allow is not written (would pre-approve)")
                continue
            (deny if action is RuleAction.DENY else ask).update(tools)
        fields: dict[str, Any] = {}
        if ask:
            fields["permissions.ask"] = tuple(sorted(ask))
        if deny:
            fields["permissions.deny"] = tuple(sorted(deny))
        notes.append("writable paths only: " + ",".join(_WRITABLE_PATHS))
        return CompiledIntentSet(harness_id=self.harness_id, fields=fields,
                                 notes=tuple(notes))

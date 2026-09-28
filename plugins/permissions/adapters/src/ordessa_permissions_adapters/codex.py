"""CodexAdapter - codex permission policy adapter (T03).

Writable native surface, measured on the pinned artifact
(`posture_config.py:72-80, 206-285`): two top-level scalars,
`sandbox_mode` in (`read-only`, `workspace-write`) and `approval_policy` in
(`untrusted`, `on-request`). `danger-full-access` and `never` are loosening
values and `on-failure` is indistinguishable from `on-request` on both
measured oracles (`codex doctor`, `codex debug prompt-input`) - none of them
is writable, and under a ceiling that forbids the posture they would enable,
the compile refuses with `POLICY_CEILING_VIOLATION` instead of ever
attempting a bypass path (harness-adapters.md row "Codex": 受管理设备
requirements 不可提升; `danger-full-access` 被上限禁用时拒绝).

Codex gates commands, not per-tool actions: denying `bash`, `webfetch`,
`skill` or `task` per tool has no knob and refuses
(`posture_config.py:213-218`).

EVIDENCE (file:line, read 2026-09-28):
- plugins/server-compat/.../profiles/posture_config.py:77-80 strictness tables
  and writable values
- plugins/server-compat/.../profiles/posture_config.py:221-227 the
  ask-gating rule (bash asks are `untrusted`, other gated keys `on-request`)
- plugins/harness/.../harnesses.toml:13,31  the codex family declares the
  `permissions` capability and the `permission` profile slot
- plugins/harness/adapters/acp-adapter/pkg/codexacp/embedded.go:39-66,201
  PermissionDecision/RespondPermission channel shape (S-level; the Python-side
  consumption is the G1 seam, not this package).
"""
from __future__ import annotations

from typing import Any, Mapping

from ordessa_permissions_api import RuleAction

from .base import BaseBrandAdapter
from .codes import AdapterCode
from .dto import PolicyCompileSnapshot
from .ranges import NativeVersionRange
from .results import CompileRefusal, CompileResult, CompiledIntentSet

__all__ = ["CodexAdapter"]

#: measured strictness scales, higher is stricter (posture_config.py:77-78)
_SANDBOX_STRICTNESS = {"read-only": 3, "workspace-write": 2, "danger-full-access": 1}
_APPROVAL_STRICTNESS = {"untrusted": 3, "on-request": 2, "on-failure": 2, "never": 1}
_WRITABLE_SANDBOX = ("read-only", "workspace-write")
_WRITABLE_APPROVAL = ("untrusted", "on-request")

#: keys whose *denial* the sandbox mode can express (writes are the sandbox's
#: business); denial of any other key has no per-tool knob (posture_config
#: .py:213-218).
_WRITE_DENIED_KEYS = ("edit", "external_directory")
#: keys that cannot be denied per-tool at all.
_NO_PER_TOOL_DENY = ("bash", "webfetch", "skill", "task", "read")


class CodexAdapter(BaseBrandAdapter):
    adapter_id = "permissions.policy-adapter.codex"
    harness_id = "codex"
    version_range = NativeVersionRange(minimum="2.0", maximum="3.0")
    capability_evidence = ("posture_config.py:77-80,206-285 measured writable "
                           "scalars; harnesses.toml:13,31 permissions capability "
                           "and permission slot declared")

    def expressible_actions(self) -> Mapping[str, Any]:
        return {"read": frozenset({"ask"}),
                "edit": frozenset({"ask", "deny"}),
                "external_directory": frozenset({"ask", "deny"}),
                "bash": frozenset({"ask"}),
                "task": frozenset({"ask"}),
                "webfetch": frozenset({"ask"}),
                "skill": frozenset({"ask"})}

    def writable_sandbox_values(self) -> tuple[str, ...]:
        return _WRITABLE_SANDBOX

    def writable_approval_values(self) -> tuple[str, ...]:
        return _WRITABLE_APPROVAL

    def sandbox_strictness(self, value: str) -> int:
        return _SANDBOX_STRICTNESS[value]

    def approval_strictness(self, value: str) -> int:
        return _APPROVAL_STRICTNESS[value]

    def verifiable_fields(self) -> frozenset[str]:
        # the read-back oracle is the top-level scalar parse plus the stricter-
        # kept comparison (posture_config.py:231-243): these two fields only.
        return frozenset({"sandbox_mode", "approval_policy"})

    def _mode_gate(self, snapshot: PolicyCompileSnapshot) -> Any:
        mode = snapshot.intent.desired_mode if snapshot.intent else None
        if mode is None:
            return None
        if mode.name in _WRITABLE_APPROVAL:
            return {"approval_floor": mode.name}
        # `never` loosens approvals away entirely; `on-failure` cannot be
        # told apart from `on-request` on either oracle - emitting it would
        # claim an effect that cannot be shown (posture_config.py:74-76).
        return CompileRefusal(
            AdapterCode.PERMISSION_POSTURE_UNEXPRESSIBLE,
            source=f"{self.adapter_id}.compilePolicy",
            target=f"codex approval_policy={mode.name!r} is not a writable "
                   "pinned value")

    def _assemble(self, actions: Mapping[str, RuleAction],
                  snapshot: PolicyCompileSnapshot, mode: Any) -> CompileResult:
        for key in _NO_PER_TOOL_DENY:
            if actions[key] is RuleAction.DENY:
                return CompileRefusal(
                    AdapterCode.PERMISSION_POSTURE_UNEXPRESSIBLE,
                    source=f"{self.adapter_id}.compilePolicy",
                    target=f"codex has no per-tool deny for {key}; its sandbox "
                           "modes are directory-scoped")
        notes: list[str] = []
        fields: dict[str, Any] = {}
        writes_denied = any(actions[key] is RuleAction.DENY for key in _WRITE_DENIED_KEYS)
        if writes_denied:
            fields["sandbox_mode"] = "read-only"
            notes.append("write denials narrow the sandbox to read-only")
        gated = sorted(key for key, action in actions.items()
                       if action is not RuleAction.ALLOW)
        approval: str | None = None
        if gated:
            approval = "untrusted" if "bash" in gated else "on-request"
            notes.append(f"asking on {gated} is the approval policy "
                         f"{approval!r}; codex gates commands, not per-tool "
                         "actions")
        if isinstance(mode, Mapping) and mode.get("approval_floor"):
            floor = mode["approval_floor"]
            approval = (floor if approval is None or
                        _APPROVAL_STRICTNESS[floor] > _APPROVAL_STRICTNESS[approval]
                        else approval)
            notes.append(f"requested mode {floor!r} honoured as an approval "
                         "floor, never a loosening")
        if approval is not None:
            assert approval in _WRITABLE_APPROVAL
            fields["approval_policy"] = approval
        return CompiledIntentSet(harness_id=self.harness_id, fields=fields,
                                 notes=tuple(notes))

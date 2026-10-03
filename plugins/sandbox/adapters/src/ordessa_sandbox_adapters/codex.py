"""CodexSandboxAdapter — codex native-sandbox configuration adapter (T05).

Writable native surface, measured on the pinned artifact:

* accepted ``sandbox_mode`` values come from the committed, version-matched App
  Server JSON schema ``definitions.SandboxMode`` (``read-only`` /
  ``workspace-write`` / ``danger-full-access``) — plugins/harness/adapters/
  acp-adapter/internal/codex/schema/codex_app_server_protocol.v2.schemas.json:92-99;
* but only ``read-only`` / ``workspace-write`` are *writable* isolation
  postures — ``_WRITABLE_SANDBOX`` (posture_config.py:79);
* strictness table ``_SANDBOX_STRICTNESS`` (posture_config.py:77);
* the bridge carries the resolved ``Sandbox`` value
  (plugins/harness/adapters/acp-adapter/pkg/codexacp/runtime.go:26-27,116-117).

``danger-full-access`` is codex's de-facto "no sandbox" posture. When a ceiling
forbids loosening it, or the administrator enforces the sandbox, the compile
refuses — it never attempts a bypass path (harness-adapters.md Codex row:
受管理设备 requirements 不可提升; ``danger-full-access`` 被上限禁用时拒绝).

The compiled fields bind for real: each one converts into the platform's
``SetField`` over the server-issued ``TargetHandle`` (``seam.py``), and the
closed payload schema contributed on the point is what refuses a shell/path
shaped request.
"""
from __future__ import annotations

from typing import Any, Mapping

from ordessa_harness_api.intents import TargetHandle
from ordessa_sandbox_api import CodexSandboxConfig, NativeSandboxIntent, \
    ToolCategory

from .base import BaseSandboxAdapter
from .dto import AuthorizedFacts
from .ranges import NativeVersionRange
from .results import CompileRefusal, CompileResult
from .seam import CompiledFieldIntent, KIND_SET_FIELD
from ordessa_sandbox_api import SandboxErrorCode

__all__ = ["CodexSandboxAdapter"]

#: writable isolation postures (posture_config.py:79)
_WRITABLE_SANDBOX = ("read-only", "workspace-write")


class CodexSandboxAdapter(BaseSandboxAdapter):
    adapter_id = "sandbox.native-config.codex"
    harness_id = "codex"
    brand = "codex"
    version_range = NativeVersionRange(minimum="2.0", maximum="3.0")
    coverable = frozenset({ToolCategory.BASH, ToolCategory.READ,
                           ToolCategory.EDIT, ToolCategory.NETWORK})
    capability_evidence = (
        "posture_config.py:77-79 strictness/writable tables; committed Codex "
        "schema SandboxMode enum; codexacp/runtime.go:26-27 ProfileConfig.Sandbox")

    def native_field_claims(self) -> tuple[str, ...]:
        return ("sandbox_mode", "sandbox_workspace_write")

    def config_from_payload(self, payload: Mapping[str, Any]) -> CodexSandboxConfig:
        """The closed point payload -> the domain codex config.

        The payload was already schema-validated by the platform
        (``descriptor.payload_schema``); this only re-expresses it.
        """
        return CodexSandboxConfig(
            sandbox_mode=payload["sandbox_mode"],
            writable_roots=tuple(payload.get("writable_roots", ())),
            network_access=bool(payload.get("network_access", False)))

    def _compile_brand(self, intent: NativeSandboxIntent, target: TargetHandle,
                       authorized: AuthorizedFacts | None) -> CompileResult:
        config: Any = intent.config
        if config.sandbox_mode not in _WRITABLE_SANDBOX:
            # danger-full-access is in the native vocabulary but is NOT a
            # writable isolation posture: refuse, do not approximate, do not
            # attempt any bypass.
            return CompileRefusal(
                SandboxErrorCode.SANDBOX_NATIVE_UNSUPPORTED,
                source=f"{self.adapter_id}.compile",
                target=f"codex sandbox_mode {config.sandbox_mode!r} is not a "
                       "writable sandbox posture (only read-only/"
                       "workspace-write); no bypass is attempted")
        fields = [CompiledFieldIntent(
            field_path_segments=("sandbox_mode",), value=config.sandbox_mode,
            kind=KIND_SET_FIELD, intent=intent, target=target)]
        notes = ["sandbox_mode compiled to a Harness C3 SetField within the "
                 "writable posture set"]
        if config.writable_roots or config.network_access:
            fields.append(CompiledFieldIntent(
                field_path_segments=("sandbox_workspace_write",),
                value={"writableRoots": list(config.writable_roots),
                       "networkAccess": bool(config.network_access)},
                kind=KIND_SET_FIELD, intent=intent, target=target))
            notes.append("workspace-write roots/network carried as one "
                         "structured field, never a raw path write")
        return self._result(intent, fields, notes)


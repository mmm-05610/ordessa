from __future__ import annotations

import shutil
import subprocess
import secrets
from pathlib import Path
from typing import Any
from pacthold_runtime_compat.credentials import CONTRACT_ID, PreparedSecretMount, ResolvedCredential
from pacthold_runtime_compat.resource_contracts import CredentialRefV1
from pacthold.work_core import Ref, RefType
from pacthold.work_core.registry import ProviderDescriptor
from pacthold.extensions import ResourceSelection, SelectorField


class CodexCredentialSource:
    """Plugin-owned, non-secret projection of the native Codex login."""

    locator = "codex-login/default"
    provider = "codex"
    provider_id = "codex-login"
    supported_contract_ids = frozenset({CONTRACT_ID})

    def __init__(self, *, home: Path | None = None, binary: str | None = None) -> None:
        self.home = (home or Path.home()).resolve()
        self.binary = binary or shutil.which("codex")

    def validate(self, value: Any) -> None:
        if value is None:
            return
        if not isinstance(value, (dict, CredentialRefV1)):
            raise ValueError("UNSUPPORTED_CODEX_CREDENTIAL_SOURCE")
        provider = value.provider if isinstance(value, CredentialRefV1) else value.get("provider")
        locator = value.native_locator if isinstance(value, CredentialRefV1) else value.get("native_locator")
        if provider not in {self.provider, self.provider_id} or locator != self.locator:
            raise ValueError("UNSUPPORTED_CODEX_CREDENTIAL_SOURCE")
        if isinstance(value, dict) and set(value) - {"provider", "native_locator", "revision", "digest"}:
            raise ValueError("UNSUPPORTED_CODEX_CREDENTIAL_SOURCE")

    def project(self, execution_root: Path, value: Any) -> dict[str, Any]:
        self.validate(value)
        del execution_root
        return {"provider": (value or {}).get("provider", self.provider) if value else None,
                "native_locator": (value or {}).get("native_locator") if value else None,
                "method": "locator-only", "materialized": False}

    def cleanup(self, execution_root: Path) -> None:
        del execution_root

    def descriptor(self):
        return ProviderDescriptor(self.provider_id, "Codex official login credential", "1")

    def _source(self) -> Path:
        # This fixed authority location is private provider state.  It is
        # never returned in a Ref, manifest, event, diagnostic, or API DTO.
        return self.home / ".codex" / "auth.json"

    def resolve(self, contract_id, ref, *, context=None):
        del context
        if contract_id != CONTRACT_ID or ref.type is not RefType.ARTIFACT or ref.provider != self.provider_id:
            raise ValueError("CREDENTIAL_REF_MISMATCH")
        if ref.native_id != self.locator or ref.metadata.get("schema_version", "1") != "1":
            raise ValueError("CREDENTIAL_LOCATOR_UNSUPPORTED")
        return CredentialRefV1(self.provider_id, self.locator, "codex", int(ref.metadata.get("revision", "1")))

    def prepare_mount(self, ref, execution_scope, guest_target, access):
        if not isinstance(ref, CredentialRefV1):
            raise TypeError("credential mount requires CredentialRefV1")
        self.validate(ref)
        if execution_scope.startswith("execution:") is False or guest_target != "/runtime/home/auth.json" or access != "ro":
            raise ValueError("CODEX_SECRET_MOUNT_REJECTED")
        source = self._source()
        # Metadata-only checks: do not open, parse, copy, hash, or disclose it.
        if source.is_symlink() or not source.exists() or not source.is_file():
            raise ValueError("CODEX_LOGIN_UNAVAILABLE")
        token = "codex-secret:" + secrets.token_urlsafe(24)
        return PreparedSecretMount(token, ref, execution_scope, guest_target, access)

    def bind_to_sandbox(self, prepared, sandbox_port):
        register = getattr(getattr(sandbox_port, "provider", None), "register_prepared_secret_mount", None)
        if not callable(register):
            raise ValueError("sandbox does not support typed secret mounts")
        register(prepared, self._source())

    def cleanup_mount(self, prepared, sandbox_port=None):
        if sandbox_port is not None:
            sources = getattr(getattr(sandbox_port, "provider", None), "_secret_sources", None)
            if isinstance(sources, dict): sources.pop(prepared.token, None)

    def diagnostics(self) -> dict[str, Any]:
        try:
            available = self._source().is_file() and not self._source().is_symlink()
        except (OSError, ValueError):
            available = False
        return {"available": available, "login_status": "deferred-to-sandbox-preflight", "locator": self.locator}


class CodexCredentialSelector:
    id = "codex-login"
    contract_id = CONTRACT_ID
    title = "Codex official subscription login"
    fields = (SelectorField("mode", "Credential", kind="select", default="official", required=False),)

    def __init__(self, provider: CodexCredentialSource):
        self.provider = provider

    def prepare(self, parameters, *, execution_id):
        del execution_id
        if set(parameters) - {"mode"} or parameters.get("mode", "official") != "official":
            raise ValueError("CODEX_CREDENTIAL_MODE_UNSUPPORTED")
        ref = Ref(RefType.ARTIFACT, self.provider.provider_id, self.provider.locator,
                  metadata={"schema_version": "1", "revision": "1"})
        return ResourceSelection(self.contract_id, ref, "codex-login/default", "locator-only")

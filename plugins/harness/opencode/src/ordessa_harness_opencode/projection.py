from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

from .profiles import OpenCodeProfileRef
from ordessa_execution_api.resources.profiles import exact_historical_envelope


def _sha(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class WorkspaceRuntimeSource:
    path: Path
    guest_target: str = "/workspace"
    access: str = "rw"


@dataclass(frozen=True)
class ProfileRuntimeSource:
    path: Path
    guest_target: str = "/runtime/home"
    access: str = "rw"


@dataclass(frozen=True)
class ExecutableRuntimeSource:
    path: Path
    guest_target: str = "/runtime/bin/opencode"
    access: str = "ro"


@dataclass(frozen=True)
class HelperRuntimeSource:
    path: Path
    guest_target: str = "/runtime/helpers"
    access: str = "ro"


@dataclass(frozen=True)
class OpenCodeProjection:
    directory: Path
    config_path: Path
    manifest_path: Path
    profile_ref: OpenCodeProfileRef
    credential_locator: str | None
    source_digests: Mapping[str, str]


class OpenCodeProjector:
    """Renders canonical inputs into OpenCode's native config directory."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()

    def materialize_current(self, execution_id: str, ref: OpenCodeProfileRef, *,
                            modern_ref, historical_ref, profile_views) -> OpenCodeProjection:
        from ordessa_execution_api.resources.profiles import HistoricalProfileViewPort
        if not isinstance(profile_views, HistoricalProfileViewPort):
            raise TypeError("admitted historical Profile view port required")
        view = profile_views.select_current(modern_ref, historical_ref)
        return self.materialize(execution_id, ref, historical_view=view)

    def materialize(self, execution_id: str, ref: OpenCodeProfileRef, *, historical_view) -> OpenCodeProjection:
        if type(ref) is not OpenCodeProfileRef or ref.provider != "harness-profile":
            raise ValueError("PROFILE_REF_MISMATCH")
        if not execution_id or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in execution_id):
            raise ValueError("INVALID_EXECUTION_ID")
        profile = exact_historical_envelope(historical_view,harness_type="opencode",
            profile_id=ref.profile_id,revision=ref.revision,digest=ref.digest)
        directory = self.root / execution_id / "opencode"
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        config = dict(profile["native_payload"])
        native: dict[str, Any] = {}
        for key in ("model", "small_model", "provider", "permission", "tools", "instructions"):
            if key in config:
                native[key] = config[key]
        # OpenCode's global config directory is the native target for skills.
        skills = config.get("skills") or []
        if skills:
            native["skills"] = skills
        mcp = config.get("mcp") or {}
        if mcp:
            native["mcp"] = mcp
        config_path = directory / "opencode.json"
        config_path.write_text(json.dumps(native, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        credential = profile.get("credential_source_ref") or {}
        locator = credential.get("native_locator") if isinstance(credential, Mapping) else None
        manifest = {
            "schema_version": 1, "profile_ref": {"id": ref.profile_id, "revision": ref.revision, "digest": ref.digest},
            "native_config": "opencode.json", "skills_target": "skills/", "mcp_target": "opencode.json#mcp",
            "instructions_target": "opencode.json#instructions", "credential_locator": locator,
            "credential_values_materialized": False, "config_digest": _sha(config_path),
        }
        manifest_path = directory / "projection-manifest.json"
        manifest_path.write_text(json.dumps(manifest, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        return OpenCodeProjection(directory, config_path, manifest_path, ref, locator, {"config": manifest["config_digest"]})

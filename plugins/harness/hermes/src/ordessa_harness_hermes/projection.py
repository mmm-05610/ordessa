from __future__ import annotations
import hashlib, json, shutil
from pathlib import Path
from typing import Any
from .profile import HermesProfileProvider

def _yaml(value: Any, indent: int = 0) -> str:
    # JSON is valid YAML 1.2 and preserves native Hermes config structure.
    return json.dumps(value, sort_keys=True, indent=2) + "\n"

class HermesProjection:
    def __init__(self, root: Path, profiles: HermesProfileProvider): self.root=Path(root).resolve(); self.profiles=profiles
    def materialize(self, execution_id: str, profile_ref):
        p=self.profiles.get(profile_ref.native_id, int(profile_ref.metadata["revision"]))
        if p["digest"] != profile_ref.metadata.get("digest"): raise ValueError("PROFILE_DIGEST_DRIFT")
        out=(self.root/execution_id).resolve()
        if out.parent != self.root: raise ValueError("INVALID_EXECUTION_ID")
        home=out/"hermes"; (home/"skills").mkdir(parents=True, exist_ok=True)
        config=dict(p.get("config") or {})
        # Secrets are intentionally not materialized. The locator is metadata only.
        (home/"config.yaml").write_text(_yaml(config), encoding="utf-8")
        (home/"projection-manifest.json").write_text(json.dumps({"profile_ref":dict(profile_ref.metadata), "native_home":"hermes", "credential_locator":(p.get("credential_source_ref") or {}).get("native_locator"), "shared_slots":{"skills":config.get("skills", []), "mcp":config.get("mcp", config.get("mcp_servers", [])), "instructions":config.get("instructions", []), "resources":config.get("resources", [])}}, sort_keys=True, indent=2), encoding="utf-8")
        return home
    def cleanup(self, execution_id): shutil.rmtree(self.root/execution_id, ignore_errors=True)

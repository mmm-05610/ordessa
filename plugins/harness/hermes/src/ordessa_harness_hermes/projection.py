from __future__ import annotations
import hashlib, json, shutil
from pathlib import Path
from typing import Any
from ordessa_execution_api.resources.profiles import exact_historical_envelope
from ordessa_execution_agents.harness.definitions import NativeProfileRef

def _yaml(value: Any, indent: int = 0) -> str:
    # JSON is valid YAML 1.2 and preserves native Hermes config structure.
    return json.dumps(value, sort_keys=True, indent=2) + "\n"

class HermesProjection:
    def __init__(self, root: Path): self.root=Path(root).resolve()
    def materialize_current(self, execution_id: str, profile_ref, *, modern_ref,
                            historical_ref, profile_views):
        from ordessa_execution_api.resources.profiles import HistoricalProfileViewPort
        if not isinstance(profile_views, HistoricalProfileViewPort):
            raise TypeError("admitted historical Profile view port required")
        view = profile_views.select_current(modern_ref, historical_ref)
        return self.materialize(execution_id, profile_ref, historical_view=view)
    def materialize(self, execution_id: str, profile_ref, *, historical_view):
        if (type(profile_ref) is not NativeProfileRef
                or profile_ref.provider != "harness-profile"
                or profile_ref.metadata.get("harness_type") != "hermes"):
            raise ValueError("PROFILE_REF_MISMATCH")
        p=exact_historical_envelope(historical_view,harness_type="hermes",
            profile_id=profile_ref.native_id,revision=int(profile_ref.metadata["revision"]),
            digest=profile_ref.metadata["digest"])
        out=(self.root/execution_id).resolve()
        if out.parent != self.root: raise ValueError("INVALID_EXECUTION_ID")
        home=out/"hermes"; (home/"skills").mkdir(parents=True, exist_ok=True)
        config=dict(p["native_payload"])
        # Secrets are intentionally not materialized. The locator is metadata only.
        (home/"config.yaml").write_text(_yaml(config), encoding="utf-8")
        (home/"projection-manifest.json").write_text(json.dumps({"profile_ref":dict(profile_ref.metadata), "native_home":"hermes", "credential_locator":(p.get("credential_source_ref") or {}).get("native_locator"), "shared_slots":{"skills":config.get("skills", []), "mcp":config.get("mcp", config.get("mcp_servers", [])), "instructions":config.get("instructions", []), "resources":config.get("resources", [])}}, sort_keys=True, indent=2), encoding="utf-8")
        return home
    def cleanup(self, execution_id): shutil.rmtree(self.root/execution_id, ignore_errors=True)

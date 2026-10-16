from __future__ import annotations
import os, shutil
from dataclasses import dataclass
from pathlib import Path
from .projection import HermesProjection

@dataclass(frozen=True)
class HermesLaunchSpec:
    argv: tuple[str, ...]; env: dict[str, str]; cwd: Path; home: Path; executable: Path; helper: Path | None; profile_ref: object

class HermesLaunchAdapter:
    def __init__(self, projection: HermesProjection, *, binary: str | None = None, helper: Path | None = None):
        self.projection=projection; self.binary=Path(binary).resolve() if binary else (Path(shutil.which("hermes" )).resolve() if shutil.which("hermes") else None); self.helper=helper
    def plan(self, *, execution_id, profile_ref, modern_ref, historical_ref,
             profile_views, workspace, profile):
        """Stage local config/executable only; this result is not dispatch authority."""
        if self.binary is None: raise RuntimeError("HERMES_BINARY_UNAVAILABLE")
        home=self.projection.materialize_current(execution_id, profile_ref,
            modern_ref=modern_ref, historical_ref=historical_ref,
            profile_views=profile_views)
        # bwrap binds directories reliably at this boundary; stage only the
        # selected executable into an execution-local, non-Workspace directory.
        executable_dir = home.parent / "executable"; executable_dir.mkdir(parents=True, exist_ok=True)
        staged = executable_dir / "hermes"; shutil.copy2(self.binary, staged); staged.chmod(0o700)
        env={k:v for k,v in os.environ.items() if k in {"LANG","LC_ALL","LC_CTYPE","PATH","HTTP_PROXY","HTTPS_PROXY","ALL_PROXY","NO_PROXY"}}
        env["PATH"]="/usr/bin:/bin"; env["HERMES_HOME"]="/runtime/home"; env["AGENT_BOX_EXECUTION_ID"]=execution_id
        return HermesLaunchSpec((str(staged),), env, workspace.path, home, executable_dir, self.helper, profile_ref)
    def cleanup(self, execution_id): self.projection.cleanup(execution_id)

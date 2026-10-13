from __future__ import annotations
from dataclasses import dataclass
import os, json
from pathlib import Path
from .profile import ClaudeProjection, ClaudeProfileRef
from ordessa_execution_agents.harness.definitions import NativeProfileRef

@dataclass(frozen=True)
class ClaudeLaunchSpec:
    argv: tuple[str, ...]; env: dict[str, str]; cwd: Path; profile_home: Path; helper_dir: Path; executable: str

class ClaudeLaunchAdapter:
    def __init__(self, projection: ClaudeProjection, *, binary=None):
        self.projection=projection; self.binary=binary
    def plan(self, *, execution_id, profile_ref, modern_ref, historical_ref,
             profile_views, profile, workspace, prompt, continuation=None, resources=()):
        """Stage local files and argv only; this result is not a Unit dispatch grant."""
        if not self.binary: raise RuntimeError("CLAUDE_BINARY_UNAVAILABLE")
        if (type(profile_ref) is not NativeProfileRef
                or profile_ref.provider != "harness-profile"
                or profile_ref.metadata.get("harness_type") != "claude-code"):
            raise ValueError("PROFILE_REF_MISMATCH")
        exact=ClaudeProfileRef(profile_ref.native_id, int(profile_ref.metadata.get("revision", "0")), profile_ref.metadata.get("digest", ""), profile_ref.provider)
        home=self.projection.materialize_current(execution_id, exact,
            modern_ref=modern_ref, historical_ref=historical_ref,
            profile_views=profile_views, resources=resources)
        helper=home.parent / (home.name + "-hooks"); helper.mkdir(mode=0o700, exist_ok=True)
        hook=helper / "session-start"; hook.write_text("#!/usr/bin/env python3\nimport json,os\nfrom pathlib import Path\nPath('/workspace/claude-session.json').write_text(json.dumps({'session_id': os.environ.get('AGENT_BOX_EXECUTION_ID','unknown')}))\n", encoding="utf-8"); hook.chmod(0o700)
        args=[self.binary, "--print"]
        if continuation: args += ["--resume", continuation]
        args += [prompt]
        env={k:v for k,v in os.environ.items() if k in {"LANG","LC_ALL","HTTP_PROXY","HTTPS_PROXY","NO_PROXY"}}
        return ClaudeLaunchSpec(tuple(args), env, workspace.path, home, helper, self.binary)
    def cleanup(self, execution_id): self.projection.cleanup(execution_id)

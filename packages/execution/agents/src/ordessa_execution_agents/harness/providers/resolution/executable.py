"""Bounded executable resolution; registry values never become shell code."""
from pathlib import Path
import os
def resolve_executable(identity: str, resolver_kind: str, *, search_path=None):
    if resolver_kind not in {"PATH", "PATH_OR_BUNDLE"}: raise ValueError("unsupported executable resolver")
    for directory in (search_path or os.environ.get("PATH","")).split(":"):
        candidate=Path(directory)/identity
        if candidate.is_file() and os.access(candidate,os.X_OK): return candidate
    raise FileNotFoundError(identity)

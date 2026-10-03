"""Ordessa runtime-preferences brand configuration adapters (eight brands).

Facet ``assets.runtime-preferences`` for the Harness C2 registration point
(``harness.configuration-adapters`` v1): the four run-level parameter groups
compaction / memory / shell / retry, projected per brand onto each harness's
documented native configuration surface. Pure modules: the adapters never
read HOME, never touch the network, never spawn, never write files and never
hold secret content — see the boundary gates in ``tests/``.

Evidence level: document-level (fixed official snapshots, 2026-09-27, plus
two 2026-09-28 point upgrades). Every compiled key carries a citation in
``keys.py``; unknowns stay unknown.
"""
from . import common, keys
from .claude import ClaudeAdapter, registration_manifest as claude_manifest
from .codex import CodexAdapter, registration_manifest as codex_manifest
from .dsh import DshAdapter, registration_manifest as dsh_manifest
from .hermes import HermesAdapter, registration_manifest as hermes_manifest
from .kilo import KiloAdapter, registration_manifest as kilo_manifest
from .opencode import OpencodeAdapter, registration_manifest as opencode_manifest
from .pi import PiAdapter, registration_manifest as pi_manifest
from .qwen import QwenAdapter, registration_manifest as qwen_manifest

__all__ = [
    "common", "keys",
    "PiAdapter", "CodexAdapter", "ClaudeAdapter", "HermesAdapter",
    "OpencodeAdapter", "DshAdapter", "QwenAdapter", "KiloAdapter",
    "pi_manifest", "codex_manifest", "claude_manifest", "hermes_manifest",
    "opencode_manifest", "dsh_manifest", "qwen_manifest", "kilo_manifest",
]

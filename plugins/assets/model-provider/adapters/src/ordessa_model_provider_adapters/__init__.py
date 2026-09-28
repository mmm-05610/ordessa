"""Ordessa model-provider brand configuration adapters (Pi/Codex/Claude Code).

Facet ``assets.model-provider`` for the Harness C2 registration point
(``harness.configuration-adapters`` v1). Pure modules: the adapters never read
HOME, never touch the network, never spawn, never write files and never hold
secret content — see the boundary gates in ``tests/``.
"""
from . import common
from .claude import ClaudeAdapter, registration_manifest as claude_manifest
from .codex import CodexAdapter, registration_manifest as codex_manifest
from .pi import PiAdapter, registration_manifest as pi_manifest

__all__ = [
    "common", "ClaudeAdapter", "CodexAdapter", "PiAdapter",
    "claude_manifest", "codex_manifest", "pi_manifest",
]

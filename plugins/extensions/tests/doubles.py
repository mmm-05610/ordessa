"""Shared doubles for the EXT tests: a published-vocabulary AdapterContext.

The doubles use ONLY published `ordessa_harness_api` shapes — no harness
internals — so the adapter is proven against the same surface the real
runtime hands it.
"""
from __future__ import annotations

from ordessa_harness_api import (
    AdapterContext, Installation, TargetDescriptor, TargetHandle,
)

CODEX_INSTALLATION = Installation(
    harness_id="codex", native_version=(0, 147, 0),
    adapter_version=(1, 1, 14),
    evidence_ref="plugins/harness/src/ordessa_harness/codex/production.py:88")

CLAUDE_INSTALLATION = Installation(
    harness_id="claude", native_version=(2, 1, 274),
    adapter_version=(0, 81, 2),
    evidence_ref="plugins/harness/src/ordessa_harness/claude/production.py:67")


def context_for(installation: Installation, *targets: TargetDescriptor,
                entry: str = "acp", scope: str = "instance",
                capability_evidence_ref: str = "test-double") -> AdapterContext:
    return AdapterContext(
        targets=tuple(targets), installation=installation, entry=entry,
        scope=scope, capability_evidence_ref=capability_evidence_ref)


def codex_file_target() -> TargetDescriptor:
    """The server-issued hooks.json file target the runtime WOULD hand
    out once the AR-3 seam exists (it supplies none today) — declaring
    the claimed face explicitly (round 11: empty allowed_fields is not a
    wildcard)."""
    return TargetDescriptor(handle=TargetHandle("hooks-json", 1),
                            kind="file", codec="json", scope="instance",
                            allowed_fields=(("hooks-document",),))


def claude_settings_target(*, with_allowed_fields: bool = True
                           ) -> TargetDescriptor:
    allowed = (("hooks",),) if with_allowed_fields else ()
    return TargetDescriptor(handle=TargetHandle("claude-settings", 1),
                            kind="file", codec="json", scope="instance",
                            allowed_fields=allowed)

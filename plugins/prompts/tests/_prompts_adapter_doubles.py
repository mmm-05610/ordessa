"""Shared doubles for the prompts adapter tests (published shapes only)."""
from __future__ import annotations

from ordessa_harness_api import (
    AdapterContext, Installation, TargetDescriptor, TargetHandle,
)

PI_INSTALLATION = Installation(
    harness_id="pi", native_version=(0, 84, 2), adapter_version=(0, 5, 0),
    evidence_ref="plugins/harness/packaging/pi/package-lock.json:45-46")

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


def json_file_target(*, allowed=()) -> TargetDescriptor:
    return TargetDescriptor(handle=TargetHandle("any-json", 1),
                            kind="file", codec="json", scope="instance",
                            allowed_fields=allowed)

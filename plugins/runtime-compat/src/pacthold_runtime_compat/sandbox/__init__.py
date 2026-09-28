"""Compatibility shim for the retired standalone sandbox protocol.

The canonical ``agent-box.sandbox@1`` value (``SandboxV1``) and every still
supported sandbox support type now live in
:mod:`pacthold.extensions.runtime_composition`.  This shim re-exports those
support types for one transition cycle only; new code must import from the
canonical module.  The former ``SandboxTemplateV1`` contract type, the
``SandboxTemplate`` alias and the runnable ``ResolvedSandbox.start()`` /
``SandboxedProcess`` protocol are intentionally gone — there is exactly one
``agent-box.sandbox@1`` Python type, and real execution only ever goes
through ``Sandbox.wrap()``.
"""
from ..runtime_composition.protocol import (
    SANDBOX_CONTRACT_ID as CONTRACT_ID,
    ProjectionRejected,
    SandboxAmbiguous,
    SandboxError,
    SandboxRequirements,
    SandboxUnavailable,
    SandboxUnsupported,
    digest_json,
    guest_path,
)

__all__ = [
    "CONTRACT_ID",
    "ProjectionRejected",
    "SandboxAmbiguous",
    "SandboxError",
    "SandboxRequirements",
    "SandboxUnavailable",
    "SandboxUnsupported",
    "digest_json",
    "guest_path",
]

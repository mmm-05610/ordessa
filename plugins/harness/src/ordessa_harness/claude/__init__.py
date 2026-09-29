"""Official, isolated Claude Code Harness plugin."""

from .attachments import (
    ClaudeAttachmentRefused,
    ClaudePreparedAttachment,
    assemble_attachment_blocks,
    claude_attachment_capabilities,
    verify_attachment,
)
from .contracts import ClaudeContinuationV1

__all__ = [
    "ClaudeContinuationV1",
    "ClaudePreparedAttachment",
    "ClaudeAttachmentRefused",
    "assemble_attachment_blocks",
    "claude_attachment_capabilities",
    "verify_attachment",
]

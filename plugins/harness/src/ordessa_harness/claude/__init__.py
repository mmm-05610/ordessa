"""Historical Claude metadata; runtime belongs to the independent provider.

Continuation identifiers remain stable. ACP attachment utilities now belong to
ordessa_harness_claude_code.acp_attachments; no legacy import shim is supplied.
"""
from .contracts import ClaudeContinuationV1

__all__ = ["ClaudeContinuationV1"]

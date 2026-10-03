"""Agent domain (A1): single-owner sessions/config/submissions (T010-01)."""
from .owners import (
    AgentOwnerError,
    AgentOwnerRegistry,
    AuthorityConflictError,
    ConfigOwner,
    ConfigSnapshot,
    InteractionOwner,
    OperationSummary,
    RunOwner,
    SessionOwner,
    SubmissionOwner,
    SubmissionReceipt,
    UnknownOutcome,
)
from .plugin import PLUGIN_ID, AgentDomainPlugin

__all__ = [
    "AgentOwnerError",
    "AgentOwnerRegistry", "AuthorityConflictError", "ConfigOwner", "ConfigSnapshot",
    "InteractionOwner", "OperationSummary", "RunOwner", "SessionOwner",
    "SubmissionOwner", "SubmissionReceipt", "UnknownOutcome",
    "PLUGIN_ID", "AgentDomainPlugin",
]

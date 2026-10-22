"""Agent/Profile consumer surface; explicit endpoints and original source only."""
from ordessa_agents.profiles import (
    ProfileService, Profile, ProfileRevision, ProfileRevisionRef, ProfileContent,
    ConfigurationDeclaration, ProfileNotFound, ProfileRevisionConflict, ProfileValidationError,
)
from ordessa_agents.profiles.definitions.validation import AGENT_CONTRACT_VERSION

from .sdk.manager import AgentManager, Records, ManagerRefused
from .sdk.instances import AgentInstanceRef, EndpointRef
from .sdk.interactions import InteractionService
from .harness.providers.catalog import HarnessCatalog
from .instances import AgentStartRequest, AgentStartReceipt, PreparedAgentContext

from .sdk.native_envelope import OperationRef as NativeOperationRef, PendingRequestRef as NativePendingRequestRef
from .sdk.native_runtime import NativeDispatchBinding

__all__ = ["AGENT_CONTRACT_VERSION", "ProfileService", "Profile", "ProfileRevision",
    "ProfileRevisionRef", "ProfileContent", "ConfigurationDeclaration", "ProfileNotFound",
    "ProfileRevisionConflict", "ProfileValidationError",
    "AgentManager", "Records", "ManagerRefused", "AgentInstanceRef", "EndpointRef",
    "InteractionService", "AgentStartRequest", "AgentStartReceipt", "PreparedAgentContext", "HarnessCatalog", "NativeOperationRef", "NativePendingRequestRef", "NativeDispatchBinding"]

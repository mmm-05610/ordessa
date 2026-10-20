"""Current product selection over original Agent owner and F1 capabilities.

The product no longer creates a Pacthold Environment/CoreBinding, enables old
provider plugins, issues invocation tickets, or selects a compatibility runtime.
Trusted app composition supplies existing Profile/catalog/endpoint/authority
ports and the host's original root proof. Missing bindings refuse before writes.
"""
from pathlib import Path
from dataclasses import dataclass
from ordessa_interfaces_contracts import validate_capability
from ordessa_server.composition.agent_owner import AgentOwnerInputs,AssembledAgentOwner,AgentOwnerUnavailable,_validate_inputs,assemble_agent_owner


@dataclass(frozen=True)
class _StoreLocation:
    store_path:Path


class ServerProductComposition:
    def __init__(self,*,agent_owner_inputs=None,http_bindings=None):
        if agent_owner_inputs is not None:_validate_inputs(agent_owner_inputs)
        from ordessa_server.composition.http_bindings import HttpOwnerBindings
        if http_bindings is not None and type(http_bindings) is not HttpOwnerBindings:
            raise TypeError('explicit original HTTP owner bindings required')
        self._agent_owner_inputs=agent_owner_inputs
        self._http_bindings=http_bindings

    def prepare_http_runtime(self):
        """Validate trusted inputs before the transport creates/adopts a root."""
        self.require_agent_inputs()
        if self._http_bindings is None:
            raise AgentOwnerUnavailable('original HTTP authority/context/Server identity required')
        from ordessa_server.composition.packages_convergence import build_product_registry_runtime
        bindings=self._http_bindings
        def build(data_root):
            return build_product_registry_runtime(data_root,self,bindings.authority,
                context_factory=bindings.context_factory,server_id=bindings.server_id)
        return build

    def require_agent_inputs(self):
        if self._agent_owner_inputs is None:
            raise AgentOwnerUnavailable('original Agent/Profile/catalog/authority bindings required')
        _validate_inputs(self._agent_owner_inputs)
        return self._agent_owner_inputs

    def assemble_owner(self,store_path,root_ownership):
        inputs=self.require_agent_inputs()
        return assemble_agent_owner(_StoreLocation(Path(store_path)),inputs,root_ownership)

    def build_capabilities(self,owner):
        if (type(owner) is not AssembledAgentOwner or owner._revoked
                or owner.manager.records is not owner.records or owner.interactions.records is not owner.records):
            raise AgentOwnerUnavailable('single live original Agent owner required')
        capabilities=tuple(owner.method_factory(owner))
        if not capabilities:raise AgentOwnerUnavailable('current product capability bindings required')
        for capability in capabilities:validate_capability(capability)
        return capabilities


def create_composition(*,agent_owner_inputs=None,http_bindings=None):
    return ServerProductComposition(agent_owner_inputs=agent_owner_inputs,http_bindings=http_bindings)

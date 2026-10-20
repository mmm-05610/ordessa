"""Explicit foreground Agent deployment over the current owner and F1 registry.

No Environment/store issuer, Unit records, provider activation or /3 wire RPC.
Injected Profile/catalog/endpoint/admission ports retain their original owners.
The caller must retain this runtime while any managed interaction is in use.
"""
from pathlib import Path

from ordessa_interfaces.system_access import CapabilityHost,build_registry
from ordessa_server.composition.root_ownership import DataRootOwner
from ordessa_server.composition.agent_owner import AgentOwnerInputs
from ordessa_server_product.composition import ServerProductComposition
from .configuration import AgentServiceConfiguration


class AgentToolsRuntime:
    def __init__(self,owner,host,root_owner,authenticate):
        self.owner=owner
        self.host=host
        self.authenticate=authenticate
        self._root_owner=root_owner
        self._closed=False

    def close(self):
        if self._closed:return
        self._closed=True
        try:self.owner.revoke()
        finally:self._root_owner.release()

    def __enter__(self):return self
    def __exit__(self,*args):self.close()


class AgentToolsDeployment:
    """Opt-in original SDK composition, never ambient/default grants."""
    def __init__(self,*,agent_owner_inputs:AgentOwnerInputs,authenticate):
        self.product=ServerProductComposition(agent_owner_inputs=agent_owner_inputs)
        self.product.require_agent_inputs()
        if not callable(authenticate):raise TypeError('explicit authentication callback required')
        self.inputs=agent_owner_inputs
        self.authenticate=authenticate

    def build_runtime(self,configuration:AgentServiceConfiguration):
        if type(configuration) is not AgentServiceConfiguration:
            raise TypeError('explicit AgentServiceConfiguration required')
        root=configuration.data_root
        lock=DataRootOwner(root)
        lock.acquire()
        owner=None
        try:
            (root/'state').mkdir(mode=0o700,exist_ok=True)
            core=root/'state'/'core.sqlite'
            child=root/'state'/'agent-owner'/'agent-instances.sqlite'
            binding=lock.bind_owned_root(root_path=root,store_path=core,child_path=child)
            product=self.product
            owner=product.assemble_owner(core,binding)
            capabilities=product.build_capabilities(owner)
            host=CapabilityHost(build_registry(capabilities),tuple(c.descriptor.id for c in capabilities))
            return AgentToolsRuntime(owner,host,lock,self.authenticate)
        except BaseException:
            try:
                if owner is not None:owner.revoke()
            finally:lock.release()
            raise

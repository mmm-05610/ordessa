"""Host registration handler for the single Harness definitions role."""
from dataclasses import dataclass
import hashlib
import json
from ordessa_units.admission.generation import reserve_next_generation
from ordessa_agents.harness.providers.registry.errors import CatalogUnavailable
from ordessa_server_plugin_api import ServerPluginDescriptor,ServerContributionHandler

@dataclass
class _OwnerRound:
    descriptor: ServerPluginDescriptor
    generation: int
    manifest_digest: str
    prepared: object = None
    drained: bool = False
    retired: bool = False

class HarnessDefinitionHandler(ServerContributionHandler):
    def __init__(self, runtime):
        self._runtime = runtime
        self._owners = {}

    def begin_owner_activation(self, descriptor):
        if not isinstance(descriptor, ServerPluginDescriptor) or descriptor.id in self._owners:
            raise ValueError('exact unregistered Server installation descriptor required')
        context = self._runtime.context
        generation = reserve_next_generation(context.store_port, context.environment_id,
            descriptor.id, fingerprint_port=context.fingerprint_port)
        manifest = json.dumps({'id':descriptor.id,'version':descriptor.version,
            'api_version':descriptor.api_version,'requires':list(descriptor.requires)},
            sort_keys=True,separators=(',',':')).encode('utf-8')
        token = _OwnerRound(descriptor,generation,hashlib.sha256(manifest).hexdigest())
        self._owners[descriptor.id] = token
        return token

    def _token(self, descriptor, token):
        if self._owners.get(descriptor.id) is not token or token.descriptor is not descriptor:
            raise ValueError('original owner lifecycle token required')
        return token

    def stage(self, contribution, owner):
        token = self._owners[owner]
        if token.prepared is not None:
            raise ValueError('one Harness role batch per installation generation')
        token.prepared = self._runtime.context.harness_catalog.stage(owner,token.generation,
            token.descriptor.id,token.manifest_digest,contribution.payload)
        return token

    def commit(self, contribution, prepared, owner):
        if self._owners.get(owner) is not prepared:
            raise ValueError('original staged owner required')
        prepared.prepared.commit()

    def _retire(self, token):
        if token.retired:
            return
        prepared = token.prepared
        if prepared is None:
            token.retired = True
            return
        if prepared.state == 'staged':
            prepared.rollback()
        elif prepared.state == 'rolled_back':
            pass
        elif prepared.state == 'committed':
            catalog = self._runtime.context.harness_catalog
            if not token.drained:
                catalog.drain(token.descriptor.id,token.generation)
                token.drained = True
            catalog.retire(token.descriptor.id,token.generation)
        else:
            raise CatalogUnavailable('unknown Harness registration retains owner; no replay')
        token.retired = True

    def rollback(self, contribution, prepared, owner):
        self._retire(prepared)

    def rollback_owner_activation(self, descriptor, token):
        self._retire(self._token(descriptor,token))
        self._owners.pop(descriptor.id)

    def retire_owner_activation(self, descriptor, token):
        self.rollback_owner_activation(descriptor,token)

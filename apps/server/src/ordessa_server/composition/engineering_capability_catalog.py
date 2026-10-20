"""Original registered Engineering operation and selected review-check descriptors.

Only installed operation contracts and checks returned by Engineering's public
bound-source reader are included. This reader never creates descriptors,
normalizes versions, edits digests, grants access or publishes a method.
"""
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.api import bound_review_check_capabilities
from ordessa_engineering.methods.definitions.models import CompilationCapabilities
from ordessa_engineering.domain.common.mechanisms.hashing import record_digest


class RegisteredEngineeringCommandCatalog:
    def __init__(self, plugin):
        from .engineering import EngineeringServerPlugin
        if type(plugin) is not EngineeringServerPlugin:
            raise ApplicationError('CAPABILITY_AUTHORITY_UNAVAILABLE')
        self.plugin = plugin

    def read_current(self):
        plugin=self.plugin
        registration=getattr(plugin,'_registration',None)
        factory=getattr(plugin,'_factory',None)
        authority=plugin._authority_resolver()
        if registration is None or factory is None or authority is None:
            raise ApplicationError('CAPABILITY_AUTHORITY_UNAVAILABLE')
        binding=plugin._binding_for(authority)
        installed={m.method_id for m in registration.methods if m.owner=='ordessa.engineering' and callable(m.handler)}
        # Engineering owns selected operation/source binding. The registered
        # catalog publishes only those bound descriptors which also have an
        # installed callable on this active plugin.
        bound=binding.service.bound_operation_capabilities()
        if type(bound) is not CompilationCapabilities:
            raise ApplicationError('CAPABILITY_AUTHORITY_UNAVAILABLE')
        if bound.trust_class!='host':
            raise ApplicationError('CAPABILITY_CATALOG_UNTRUSTED')
        descriptors=list(d for d in bound.capabilities if d.capability_id in installed)
        # Publish only a route which is actually bound to the original source.
        # Check descriptors remain mechanical facts, never semantic pass or a
        # blanket catalog assembled from method declarations.
        admission=binding.ports.review_admission
        if admission is not None:
            if getattr(admission,'factory',None) is not factory:
                raise ApplicationError('REVIEW_SOURCE_AUTHORITY_MISMATCH')
            if getattr(admission,'source',None) is not None:
                try:
                    checks=bound_review_check_capabilities(admission,
                        expected_factory=factory, expected_access=binding.access,
                        expected_scope=plugin.scope)
                except ApplicationError as error:
                    # A registered whole-review route without a mixed-check
                    # authority contributes no check descriptors.
                    if error.code != 'MIXED_REVIEWER_AUTHORITY_UNAVAILABLE':
                        raise
                else:
                    if checks.trust_class!='host':
                        raise ApplicationError('CAPABILITY_CATALOG_UNTRUSTED')
                    descriptors.extend(checks.capabilities)
        descriptors=tuple(descriptors)
        snapshot=record_digest('registered-engineering-command-catalog',{
            'authority_id':factory.authority_id,'scope':{'realm_id':plugin.scope.realm_id,'project_id':plugin.scope.project_id},
            'registered_owner':'ordessa.engineering',
            'descriptors':[{'capability_id':d.capability_id,'kind':d.kind,'interface_version':d.interface_version,
                'contract_digest':d.contract_digest} for d in descriptors]})
        return CompilationCapabilities(descriptors,'sha256:'+snapshot.hex,'host')


class RegisteredHostCapabilityCatalog:
    """Aggregate only actual registered owner readers with original contracts.

    This first product slice has one implemented descriptor owner. Other
    operation/check/wait owners must expose their real registered reader before
    extending this closed set; wire metadata and fixture catalogs are refused.
    Missing requirements stay missing, and duplicate contracts must be exact.
    """
    def __init__(self, readers):
        if (type(readers) is not tuple or not readers
                or any(type(reader) is not RegisteredEngineeringCommandCatalog for reader in readers)):
            raise ApplicationError('CAPABILITY_AUTHORITY_UNAVAILABLE')
        self.readers = readers

    def read_current(self):
        descriptors = {}
        snapshots = []
        for reader in self.readers:
            current = reader.read_current()
            if current.trust_class != 'host':
                raise ApplicationError('CAPABILITY_CATALOG_UNTRUSTED')
            snapshots.append(current.registry_snapshot_ref)
            for descriptor in current.capabilities:
                key = (descriptor.capability_id, descriptor.kind, descriptor.interface_version)
                previous = descriptors.get(key)
                if previous is not None and previous != descriptor:
                    raise ApplicationError('CAPABILITY_CONTRACT_CONFLICT')
                descriptors[key] = descriptor
        result = tuple(descriptors[key] for key in sorted(descriptors))
        digest = record_digest('registered-product-owner-catalog', {
            'owner_snapshots': sorted(snapshots),
            'descriptors': [{'capability_id':d.capability_id,'kind':d.kind,
                'interface_version':d.interface_version,'contract_digest':d.contract_digest} for d in result]})
        return CompilationCapabilities(result, 'sha256:' + digest.hex, 'host')

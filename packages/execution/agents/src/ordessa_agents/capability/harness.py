"""Read-only harness catalog projection; no PATH admission or process launch."""
from ordessa_agents.harness.providers.catalog import HarnessCatalog
from ordessa_agents.sdk.harness import HarnessError
from ordessa_interfaces_contracts import (Capability,CapabilityDescriptor,OperationDescriptor,
    OperationResult,CapabilityError,compute_descriptor_digest,validate_capability)

CAPABILITY_ID='agents.harness'
_VERSION='harness-catalog/1'


def _empty():
    return {'type':'object','properties':{},'required':[],'additionalProperties':False}


def _describe():
    return {'type':'object','required':['definitionRef'],'additionalProperties':False,
            'properties':{'definitionRef':{'type':'object'}}}


def descriptor():
    operations=(
        OperationDescriptor(CAPABILITY_ID+'.list',_empty(),{'type':'object'},
            cli={'command':'agents harness','operation':'list','args':()}),
        OperationDescriptor(CAPABILITY_ID+'.describe',_describe(),{'type':'object'},
            cli={'command':'agents harness','operation':'describe',
                 'args':({'name':'definitionRef','flags':('--definition-ref',),'type':'json-file'},)}),
    )
    base=CapabilityDescriptor(CAPABILITY_ID,_VERSION,operations,'')
    return CapabilityDescriptor(CAPABILITY_ID,_VERSION,operations,
        compute_descriptor_digest(base))


def build_harness_capability(catalog, *, admission=None):
    """Project the admitted catalog; ``admission`` carries rejection reasons.

    Rejected or absent providers are reported as data instead of being silently
    dropped, so a caller can tell "nothing installed" from "installed but not
    admitted" without probing the filesystem itself.
    """
    if type(catalog) is not HarnessCatalog:
        raise TypeError('original pinned HarnessCatalog required')
    rejected = dict(admission or {})

    async def list_harnesses(request, context):
        try:
            descriptors=catalog.descriptors()
        except HarnessError:
            return OperationResult('refused',error=CapabilityError(
                'CAPABILITY_UNSUPPORTED','installed harness catalog is unavailable'))
        reported=[{'definitionId':name,'reason':reason} for name,reason in sorted(rejected.items())]
        if not descriptors:
            return OperationResult('refused',data={'harnesses':[],'notAdmitted':reported},
                error=CapabilityError('CAPABILITY_UNSUPPORTED',
                    'no harness provider is admitted' if rejected else 'no harness provider is installed'))
        return OperationResult('completed',
            data={'harnesses':[item.projection() for item in descriptors],'notAdmitted':reported})

    async def describe_harness(request, context):
        try:
            provider=catalog.resolve(request['definitionRef'])
        except HarnessError:
            return OperationResult('refused',error=CapabilityError(
                'CAPABILITY_UNSUPPORTED','harness pin is not installed'))
        return OperationResult('completed',data={'harness':provider.descriptor.projection()})

    capability=Capability(descriptor(),{
        CAPABILITY_ID+'.list':list_harnesses,
        CAPABILITY_ID+'.describe':describe_harness,
    })
    validate_capability(capability)
    return capability


__all__=['CAPABILITY_ID','build_harness_capability','descriptor']

"""F1 consumer projection over the original ProfileService and admission.

The external guard authenticates and binds the existing principal/project. This
adapter never constructs Profile storage, policy, issuer or approval authority.
"""
from ordessa_execution_agents.public import ProfileService
from ordessa_execution_agents.profiles import (encode_profile,encode_revision,decode_revision_ref,
    ProfileAccessRefused,ProfileValidationError,ProfileRevisionConflict,ProfileNotFound)
from ordessa_execution_agents.sdk.contract_catalog import profile_contract
import hashlib

from ordessa_interfaces_contracts import (Capability,CapabilityDescriptor,OperationDescriptor,
    OperationResult,CapabilityError,compute_descriptor_digest,validate_capability)


def _request_key_id(request_id):
    """Map an opaque external request id to the durable RequestKey grammar."""
    if type(request_id) is not str or not request_id:
        raise ValueError('request id is required')
    return 'r-' + hashlib.sha256(request_id.encode('utf-8')).hexdigest()[:32]


_PROFILE_CLI={
    'list':({'includeArchived':{'type':'boolean'}},(),
            ({'name':'includeArchived','flags':('--include-archived',),'type':'boolean'},)),
    'readEntry':({'profileId':{'type':'string','minLength':1,'maxLength':512}},('profileId',),
            ({'name':'profileId','type':'string'},)),
    'read':({'profileRef':{'type':'object'}},('profileRef',),
            ({'name':'profileRef','type':'json-file'},)),
    'preview':({'profileRef':{'type':'object'}},('profileRef',),
            ({'name':'profileRef','type':'json-file'},)),
    'create':({'profileId':{'type':'string','minLength':1,'maxLength':512},
               'displayName':{'type':'string','minLength':1,'maxLength':512},
               'manifest':{'type':'object'}},('profileId','displayName','manifest'),
            ({'name':'profileId','type':'string'},
             {'name':'displayName','flags':('--name',),'type':'string'},
             {'name':'manifest','flags':('--manifest',),'type':'json-file'})),
    'edit':({'profileId':{'type':'string','minLength':1,'maxLength':512},'manifest':{'type':'object'},
             'expectedCatalogRevision':{'type':'integer','minimum':1,'maximum':9007199254740991},
             'baseManifestRef':{'type':'object'}},
            ('profileId','manifest','expectedCatalogRevision','baseManifestRef'),
            ({'name':'profileId','type':'string'},
             {'name':'manifest','flags':('--manifest',),'type':'json-file'},
             {'name':'expectedCatalogRevision','flags':('--expected-catalog-revision',),'type':'integer'},
             {'name':'baseManifestRef','flags':('--base-manifest-ref',),'type':'json-file'})),
    'clone':({'profileRef':{'type':'object'},'profileId':{'type':'string','minLength':1,'maxLength':512},
              'displayName':{'type':'string','minLength':1,'maxLength':512}},
             ('profileRef','profileId','displayName'),
             ({'name':'profileRef','flags':('--profile-ref',),'type':'json-file'},
              {'name':'profileId','flags':('--profile-id',),'type':'string'},
              {'name':'displayName','flags':('--name',),'type':'string'})),
    'rename':({'profileId':{'type':'string','minLength':1,'maxLength':512},
               'displayName':{'type':'string','minLength':1,'maxLength':512},
               'expectedCatalogRevision':{'type':'integer','minimum':1,'maximum':9007199254740991}},
              ('profileId','displayName','expectedCatalogRevision'),
              ({'name':'profileId','type':'string'},
               {'name':'displayName','flags':('--name',),'type':'string'},
               {'name':'expectedCatalogRevision','flags':('--expected-catalog-revision',),'type':'integer'})),
    'archive':({'profileId':{'type':'string','minLength':1,'maxLength':512},
                'expectedCatalogRevision':{'type':'integer','minimum':1,'maximum':9007199254740991}},
               ('profileId','expectedCatalogRevision'),
               ({'name':'profileId','type':'string'},
                {'name':'expectedCatalogRevision','flags':('--expected-catalog-revision',),'type':'integer'})),
    'restore':({'profileId':{'type':'string','minLength':1,'maxLength':512},
                'expectedCatalogRevision':{'type':'integer','minimum':1,'maximum':9007199254740991}},
               ('profileId','expectedCatalogRevision'),
               ({'name':'profileId','type':'string'},
                {'name':'expectedCatalogRevision','flags':('--expected-catalog-revision',),'type':'integer'})),
}


def _specs():
    """Every operation; ``capabilities`` stays call-only (no entity command)."""
    return {
        'capabilities':({},()),
        'list':_PROFILE_CLI['list'][:2],'readEntry':_PROFILE_CLI['readEntry'][:2],
        'read':_PROFILE_CLI['read'][:2],'preview':_PROFILE_CLI['preview'][:2],
        'create':_PROFILE_CLI['create'][:2],'edit':_PROFILE_CLI['edit'][:2],
        'clone':_PROFILE_CLI['clone'][:2],'rename':_PROFILE_CLI['rename'][:2],
        'archive':_PROFILE_CLI['archive'][:2],'restore':_PROFILE_CLI['restore'][:2]}


def descriptor():
    """Static Profile operation/metadata surface; no store or guard is bound."""
    obj={'type':'object'}
    specs=_specs()
    operations=[]
    for action,(properties,required) in specs.items():
        cli=None
        if action in _PROFILE_CLI:
            cli={'command':'agents profiles','operation':action,'args':_PROFILE_CLI[action][2]}
        operations.append(OperationDescriptor('profiles.'+action,
            {'type':'object','properties':properties,'required':list(required),
             'additionalProperties':False},obj,cli=cli))
    base=CapabilityDescriptor('profiles','profile-json/1',tuple(operations),'')
    return CapabilityDescriptor(base.id,base.version,base.operations,
        compute_descriptor_digest(base))


def build_profile_capability(service,*,invocation_resolver,guard):
    if type(service) is not ProfileService or not callable(invocation_resolver) or not callable(guard):
        raise TypeError('original ProfileService, authenticated resolver and scope guard required')
    specs=_specs()
    handlers={}
    for action in specs:
        operation='profiles.'+action
        async def invoke(request,context,_action=action,_operation=operation):
            invocation=invocation_resolver(context)
            try:
                # Synchronous original guard ends after the original store TX.
                with guard(_operation,invocation,service):
                    if _action=='capabilities':
                        value={**profile_contract(),'environmentNamespace':service.environment_namespace,
                            'supports':{'profileCatalog':service.capabilities().get('profileCatalog') is True,'nodes':False,'managedInput':False},'supportedMethods':['profiles.'+a for a in specs]}
                    elif _action=='list':value={'entries':[encode_profile(p) for p in service.list(include_archived=request.get('includeArchived',False))]}
                    elif _action=='readEntry':value=encode_profile(service.get(request['profileId']))
                    elif _action=='read':value=encode_revision(service.get_revision(decode_revision_ref(request['profileRef'])))
                    elif _action=='preview':
                        value=dict(service.preview(decode_revision_ref(request['profileRef'])))
                        if value.get('ready') is not True:
                            return OperationResult('refused',data=value,
                                error=CapabilityError('CAPABILITY_UNSUPPORTED',
                                                      'Profile preview remains unresolved'))
                    else:
                        # The external request id is opaque (uuid hex may start with
                        # a digit) while the durable RequestKey has its own grammar;
                        # derive a stable key instead of passing the raw id through.
                        key=service.request_key(_request_key_id(context.request_id))
                        if _action=='create':result=service.create(profile_id=request['profileId'],name=request['displayName'],content=request['manifest'],request=key)
                        elif _action=='edit':result=service.revise(request['profileId'],content=request['manifest'],expected_version=request['expectedCatalogRevision'],base_revision=decode_revision_ref(request['baseManifestRef']),request=key)
                        elif _action=='clone':result=service.clone(decode_revision_ref(request['profileRef']),profile_id=request['profileId'],name=request['displayName'],request=key)
                        elif _action=='rename':result=service.rename(request['profileId'],name=request['displayName'],expected_version=request['expectedCatalogRevision'],request=key)
                        else:result=getattr(service,_action)(request['profileId'],expected_version=request['expectedCatalogRevision'],request=key)
                        value=encode_profile(result)
                return OperationResult('completed',data=value)
            except ProfileAccessRefused:
                return OperationResult('refused',error=CapabilityError('PERMISSION_DENIED','Original Profile admission refused'))
            except ProfileRevisionConflict:
                return OperationResult('refused',error=CapabilityError('CONFLICT','Original Profile revision conflict'))
            except (ProfileValidationError,ProfileNotFound,ValueError,TypeError,KeyError):
                return OperationResult('refused',error=CapabilityError('INVALID_INPUT','Profile input invalid or unavailable'))
        handlers[operation]=invoke
    result=Capability(descriptor(),handlers)
    validate_capability(result);return result

"""Explicit preparation/authority fixture over ORIGINAL SDK Records, not a copied journal."""
from types import SimpleNamespace
from ordessa_execution_agents.sdk.interactions import (
    InteractionService,BindingProvenance,_digest_of,InteractionsRefused,
)
from ordessa_execution_agents.sdk.manager import Records
from ordessa_execution_agents.sdk.instances import AgentInstanceRef,EndpointRef
from ordessa_execution_agents.profiles import ProfileRevisionRef,encode_revision_ref

DIGEST='sha256:'+'a'*64
PROFILE=ProfileRevisionRef('env-1','profile-1',1,DIGEST)
ENDPOINT=EndpointRef('issuer','endpoint','1',DIGEST)
from ordessa_execution_agents.instances.contracts import InstanceBindingMaterial
from ordessa_execution_agents.sdk.harness import HarnessDescriptor
MATERIAL=InstanceBindingMaterial(PROFILE,HarnessDescriptor('fixture',
    {'environmentNamespace':'env-1','definitionId':'fixture','revision':'1'},DIGEST,'acp',(),()),
    ENDPOINT,DIGEST,DIGEST,'acp','session-1','original-source')
INSTANCE=AgentInstanceRef('ns-1','instance-1',MATERIAL.digest)

class Authority:
    def __init__(self):self.tokens=[];self.denied=set()
    def token(self,subject='principal:test',read=True,send=True):
        token=SimpleNamespace(subject=subject,read=read,send=send);self.tokens.append(token);return token
    def principal_scope(self,token):
        if not any(token is t for t in self.tokens):raise InteractionsRefused('FORGED_INVOCATION')
        return token.subject
    def check_read_turn(self,token,query):
        self.principal_scope(token)
        if not token.read or 'read' in self.denied:raise InteractionsRefused('READ_NOT_AUTHORIZED')
    def check_read_binding(self,token,instance):
        self.check_read_turn(token,None)
    def check_send(self,token,binding):
        self.principal_scope(token)
        if not token.send or 'send' in self.denied:raise InteractionsRefused('SEND_NOT_AUTHORIZED')


def provenance(instance=INSTANCE,endpoint=ENDPOINT):
    values={'schemaVersion':'agent-binding-provenance/1','instanceRef':instance.projection(),
        'revision':1,'profileRef':encode_revision_ref(PROFILE),'preparedPlanDigest':DIGEST,
        'endpointRef':endpoint.projection(),'directoryBindingDigest':DIGEST,'sourceRevision':'original-source',
        'configurationRefs':[],'capturedAt':'2026-10-19T00:00:00Z'}
    return BindingProvenance.decode({**values,'observationDigest':_digest_of(values)})


def original_service(path,resolver=None):
    records=Records(path);authority=Authority();sender=authority.token();reader=authority.token(send=False)
    records.publish_instance_binding(provenance(),'session-1',principal_scope='principal:test',protocol_id='acp')
    # Explicit trusted preparation fixture; no production auto-seed/fallback.
    if records.instance_control(INSTANCE)[0] is None:
        records.publish_instance_control(provenance(),SimpleNamespace(operation_ref='fixture-prepared-start'),
                                         'principal:test',binding_material=MATERIAL)
    service=InteractionService(records,authority,resolver)
    return service,authority,sender,reader

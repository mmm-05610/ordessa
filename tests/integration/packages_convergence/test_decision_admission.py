"""Real decision owner + generic host, with explicitly external fixture authority."""
import asyncio
from dataclasses import dataclass
from types import SimpleNamespace

from decision_runtime import DecisionRunner, FilesystemEvidenceStore, RulesOutcome
from decision_runtime.settings import DecisionsSettings
from decision_runtime.evidence import EvidenceScope
from ordessa_interfaces.system_access import RequestContext
from ordessa_server.composition.packages_convergence import build_packages_host


class Engine:
    engine_id='offline-fixture'
    def validate(self,payload):pass
    def evaluate(self,payload,facts):return RulesOutcome(values={'double':facts['input']['n']*2})
    def close(self):pass


class Store(FilesystemEvidenceStore):
    reads=0
    def scoped(self,scope):
        view=super().scoped(scope)
        original=view.get
        def get(ref):
            self.reads+=1
            return original(ref)
        view.get=get
        return view


@dataclass(frozen=True)
class Invocation:
    subject:str
    issuer:object


class ExistingAuthority:
    """Fixture existing store namespace owner, NOT app-created runtime ACL.

    The original store is configured as Alice's before any execution. New
    artifacts inherit that physical original owner scope; no hash->owner ledger.
    All authenticated callers have operation grants to show grants are insufficient.
    """
    def __init__(self,store):self.store,self.issuer,self.contexts,self.denied_reads=store,object(),{},set()
    def context(self,subject,request_id):
        context=RequestContext({'subject':subject},request_id)
        self.contexts[id(context)]=(context,Invocation(subject,self.issuer))
        return context
    def resolve(self,context):
        original,invocation=self.contexts.get(id(context),(None,None))
        if original is not context:raise PermissionError('unverified JSON principal')
        return invocation
    def authorize_operation(self,invocation,operation,request):return invocation.issuer is self.issuer
    def authorize_evidence_store(self,invocation,store,purpose):
        return invocation.issuer is self.issuer and invocation.subject=='alice' and store is self.store
    def authorize_evidence(self,invocation,store,digest):
        return self.authorize_evidence_store(invocation,store,'read') and invocation.subject not in self.denied_reads


def job():
    return {'spec_version':'decision-job/1','job_id':'offline-integration','version':1,'input':{'n':2},
        'limits':{'max_model_calls':0,'max_steps':2,'max_value_bytes':1024,'timeout_seconds':2.0},
        'steps':[{'id':'rules','type':'rules','engine':None,'when':{'fact':'input.n','op':'gte','value':1},
                  'payload':{'values':{'double':'input.n * 2'}}}],
        'result':{'from':'rules','path':['values','double']}}


def setup(root,*,policy=True):
    store=Store(root/'original-alice-evidence')
    settings=DecisionsSettings(runner_factory=lambda **kw:DecisionRunner(host_limits=None,**kw),
        evidence=store,default_engine=Engine())
    authority=ExistingAuthority(store)
    bindings={'services':{'decisions':settings},'invocation_resolver':authority.resolve,
        'evidence_scope_resolver':lambda invocation,operation:EvidenceScope('principal',invocation.subject)}
    if policy:bindings['decision_access']=authority
    entry=SimpleNamespace(name='decisions',module='decision_runtime.capability',attr='factory')
    host=build_packages_host(allowlist=('decisions',),bindings_by_capability={'decisions':bindings},entry_points=(entry,))
    return host,authority,store


def test_owner_can_run_and_read_original_evidence_but_knowing_digest_does_not_authorize_foreign_subject(tmp_path):
    async def scenario():
        host,authority,store=setup(tmp_path)
        ran=await host.call('decisions.run',{'job':job()},authority.context('alice','run'))
        assert ran.status=='completed' and ran.data['result']==4
        digest=ran.data['evidence']['digest']
        for operation in ('decisions.get','decisions.evidence'):
            before=store.reads
            denied=await host.call(operation,{'digest':digest},authority.context('bob','foreign-'+operation))
            assert denied.status=='refused' and denied.error.code=='PERMISSION_DENIED'
            assert denied.data is None and denied.evidence_refs==() and store.reads==before
            own=await host.call(operation,{'digest':digest},authority.context('alice','owner-'+operation))
            assert own.status=='completed' and own.data['summary']['result_digest']
            assert store.reads==before+1
        denied_run=await host.call('decisions.run',{'job':job()},authority.context('bob','foreign-run'))
        assert denied_run.status=='refused' and denied_run.error.code=='PERMISSION_DENIED'
    asyncio.run(scenario())


def test_missing_policy_never_publishes_unprotected_decision_handler(tmp_path):
    async def scenario():
        host,authority,store=setup(tmp_path,policy=False)
        for operation,request in [('decisions.validate',{'job':job()}),('decisions.run',{'job':job()}),
                                  ('decisions.get',{'digest':'a'*64}),('decisions.evidence',{'digest':'a'*64})]:
            result=await host.call(operation,request,authority.context('alice',operation))
            assert result.status=='refused' and result.error.code=='AUTHORITY_UNAVAILABLE'
        assert list(store.root.iterdir())==[] and store.reads==0
    asyncio.run(scenario())


def test_json_principal_copy_and_digest_paths_do_not_reach_original_store(tmp_path):
    async def scenario():
        host,authority,store=setup(tmp_path)
        forged=RequestContext({'subject':'alice'},'forged')
        denied=await host.call('decisions.get',{'digest':'a'*64},forged)
        assert denied.status=='refused' and denied.error.code=='PERMISSION_DENIED'
        for value in ('../'+'a'*61,'A'*64,'0'*63+'/', '\x00'*64):
            denied=await host.call('decisions.get',{'digest':value},authority.context('alice','path'))
            assert denied.status=='refused' and denied.error.code=='INVALID_INPUT'
        assert store.reads==0
    asyncio.run(scenario())


def test_current_evidence_revocation_is_independent_of_operation_grant(tmp_path):
    async def scenario():
        host,authority,store=setup(tmp_path)
        result=await host.call('decisions.run',{'job':job()},authority.context('alice','run'))
        digest=result.data['evidence']['digest'];authority.denied_reads.add('alice')
        before=store.reads
        denied=await host.call('decisions.evidence',{'digest':digest},authority.context('alice','after-revoke'))
        assert denied.status=='refused' and denied.error.code=='PERMISSION_DENIED' and store.reads==before
        assert authority.authorize_operation(Invocation('alice',authority.issuer),'decisions.evidence',{})
    asyncio.run(scenario())

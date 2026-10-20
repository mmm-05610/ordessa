"""Review counterexamples. Main session owns fixes and serial execution."""
from ordessa_units.errors import UnitAdmissionRefused
from dataclasses import replace

import pytest

from pacthold.public import Environment, InstallationRecord
from ordessa_execution_agents.public import (
    AgentContributionSet, RuntimeProviderDescriptor, RUNTIME_PROVIDER_VERSION,
    PURE_READ_VERSION, OwnerProposalInput, OwnerProposalAssessment,
    ConfigurationContractError, ConfigurationUnsupported, agent_services,
)
from ordessa_execution_agents.harness.providers.registry.contributions import RUNTIME_METHODS
from ordessa_execution_agents.units.configuration.offers import require_assessment
from decision_runtime.definitions.models import (
    FlowRef, PolicyRef, RunLimits, RunManifest, Precondition,
    ValidationObligation, ValidationReceipt,
)
from decision_runtime.definitions.values import ContractError, digest

DEF = {'environmentNamespace':'counterexample','definitionId':'test','revision':'1'}
PROVIDER = {'environmentNamespace':'counterexample','providerId':'test','generation':1}
EVIDENCE = {'environmentNamespace':'counterexample','evidenceId':'test'}

def proposal():
    return OwnerProposalInput(DEF,PROVIDER,'1',{},(),
        ({'obligationId':'configuration','requirement':'must','checkerId':'owner','checkerVersion':'1'},))

@pytest.mark.parametrize('bad_refs', ['invented', [{}], [{'environmentNamespace':'foreign','evidenceId':'test'}]])
def test_t65_must_obligation_cannot_use_fabricated_evidence_container(bad_refs):
    value = proposal()
    row = {'obligationId':'configuration','status':'passed','checkerId':'owner','checkerVersion':'1',
           'sourceVersions':{'descriptor':'1'},'evidenceRefs':bad_refs}
    with pytest.raises(ConfigurationContractError):
        result = OwnerProposalAssessment(value.input_digest,{'descriptor':'1'},'valid',(),
            (row,),'owner pure read only',(EVIDENCE,),PURE_READ_VERSION)
        require_assessment(value,result)

@pytest.mark.parametrize('bad_versions', ['not-a-version-map', ['1']])
def test_t65_obligation_source_versions_requires_mapping(bad_versions):
    value = proposal()
    row = {'obligationId':'configuration','status':'passed','checkerId':'owner','checkerVersion':'1',
           'sourceVersions':bad_versions,'evidenceRefs':[EVIDENCE]}
    with pytest.raises(ConfigurationContractError):
        result = OwnerProposalAssessment(value.input_digest,{'descriptor':'1'},'valid',(),
            (row,),'owner pure read only',(EVIDENCE,),PURE_READ_VERSION)
        require_assessment(value,result)

class _Policy:
    def admit_object_access(self,*args): return True

class _RefusingOwner:
    descriptor = RuntimeProviderDescriptor('test',RUNTIME_PROVIDER_VERSION,DEF,'sha256:'+'a'*64,
        ('describe_configuration_offers','assess_configuration_proposal'),PURE_READ_VERSION)
    def __init__(self,error): self.error=error; self.effects=[]; self.read_calls=[]
    def describe_configuration_offers(self,*args):
        self.read_calls.append('offers'); raise self.error('controlled owner refusal')
    def assess_configuration_proposal(self,*args):
        self.read_calls.append('assessment'); raise self.error('controlled owner refusal')

for _method in RUNTIME_METHODS:
    if not hasattr(_RefusingOwner,_method):
        def _effect(self,*args,_method=_method):
            self.effects.append(_method)
            raise AssertionError('native effect forbidden')
        setattr(_RefusingOwner,_method,_effect)

@pytest.mark.parametrize('error', [UnitAdmissionRefused, ConfigurationUnsupported])
@pytest.mark.parametrize('method', ['describe_configuration_offers','assess_configuration_proposal'])
def test_t57_owner_refused_unsupported_not_laundered_to_unavailable(error,method):
    env = Environment('counterexample',policy=_Policy(),principal_scope='authenticated')
    try:
        env.install(InstallationRecord('test.plugin','a'*64)); env.enable('test.plugin')
        owner = _RefusingOwner(error)
        env.activate('test.plugin',AgentContributionSet(agent_runtime_providers=(owner,)))
        api = agent_services(env)
        value = DEF if method=='describe_configuration_offers' else replace(
            proposal(),provider_ref=api.providers.describe(DEF)['providerRef'])
        with pytest.raises(error): getattr(api.configuration_offers,method)(value)
        assert owner.effects == []
    finally: env.close()

def test_t57_source_permission_uses_existing_native_profile_target():
    class NativePolicy:
        def admit_object_access(self,principal,target,access):
            return target != 'counterexample:agents.profile:private'
    env = Environment('counterexample',policy=NativePolicy(),principal_scope='authenticated')
    try:
        env.install(InstallationRecord('test.plugin','a'*64)); env.enable('test.plugin')
        owner = _RefusingOwner(ConfigurationUnsupported)
        env.activate('test.plugin',AgentContributionSet(agent_runtime_providers=(owner,)))
        api = agent_services(env)
        value = replace(proposal(),provider_ref=api.providers.describe(DEF)['providerRef'],
                        source_refs=({'environmentNamespace':'counterexample','profileId':'private','manifestRevision':1,'contentDigest':'sha256:'+'a'*64},))
        with pytest.raises(UnitAdmissionRefused): api.configuration_offers.assess_configuration_proposal(value)
        assert owner.read_calls == [] and owner.effects == []
    finally: env.close()

@pytest.mark.parametrize('kind', ['precondition','obligation'])
def test_t01_nested_subject_ref_is_typed_and_immutable(kind):
    mutable = {'source_namespace':'test','identity':{'id':'original'}}
    with pytest.raises(ContractError):
        if kind=='precondition':
            Precondition('condition','configuration',mutable,'1',None,'must','checker','1')
        else:
            ValidationObligation('obligation',mutable,'must','checker','1')

def test_t01_t66_manifest_freezes_effective_policies():
    first = PolicyRef('first','1',digest('policy',{'id':'first'}))
    second = PolicyRef('second','1',digest('policy',{'id':'second'}))
    policies = [first]
    manifest = RunManifest(digest('request',{}),FlowRef('flow','1',digest('flow',{})),
                           policies,RunLimits(),'offline.provider')
    before = manifest.manifest_digest
    policies.append(second)
    assert manifest.effective_policy_refs == (first,)
    assert manifest.manifest_digest == before

def test_t01_receipt_scalar_metadata_cannot_hide_mutable_values():
    with pytest.raises(ContractError):
        ValidationReceipt('validator','1',digest('proposal',{}),'valid',(),
                          ['2026-10-05T00:00:00Z'],['pure read only'])

@pytest.mark.parametrize('versions', [{}, {'descriptor':'wrong'}, {'descriptor':'1','foreign':'3'}])
def test_T65_obligation_versions_cannot_disagree_with_assessment(versions):
    value = proposal()
    row = {'obligationId':'configuration','status':'passed','checkerId':'owner','checkerVersion':'1',
           'sourceVersions':versions,'evidenceRefs':[EVIDENCE]}
    assessment = OwnerProposalAssessment(value.input_digest,{'descriptor':'1'},'valid',(),
        (row,),'owner pure read only',(EVIDENCE,),PURE_READ_VERSION)
    with pytest.raises(ConfigurationContractError): require_assessment(value, assessment)


def test_T65_owner_cannot_invent_shared_overall_and_obligation_source():
    value = proposal()
    row = {'obligationId':'configuration','status':'passed','checkerId':'owner','checkerVersion':'1',
        'sourceVersions':{'invented':'7'},'evidenceRefs':[EVIDENCE]}
    assessment = OwnerProposalAssessment(value.input_digest,{'descriptor':'1','invented':'7'},
        'valid',(),(row,),'owner pure read only',(EVIDENCE,),PURE_READ_VERSION)
    with pytest.raises(ConfigurationContractError): require_assessment(value, assessment)


@pytest.mark.parametrize('bad_version', [True, 1.0])
@pytest.mark.parametrize('stage', ['overall','obligation'])
def test_T65_source_versions_preserve_json_scalar_type(bad_version, stage):
    from ordessa_infrastructure.encoding.immutable_json import safe_json
    ref={'environmentNamespace':'counterexample','profileId':'p','manifestRevision':1,
        'contentDigest':'sha256:'+'a'*64}
    value=replace(proposal(),source_refs=(ref,))
    key=safe_json(ref)
    overall={'descriptor':'1',key:bad_version if stage=='overall' else 1}
    row={'obligationId':'configuration','status':'passed','checkerId':'owner','checkerVersion':'1',
        'sourceVersions':{key:bad_version},'evidenceRefs':[EVIDENCE]}
    assessment=OwnerProposalAssessment(value.input_digest,overall,'valid',(),(row,),
        'owner pure read only',(EVIDENCE,),PURE_READ_VERSION)
    with pytest.raises(ConfigurationContractError): require_assessment(value,assessment)

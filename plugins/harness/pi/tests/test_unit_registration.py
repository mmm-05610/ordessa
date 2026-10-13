"""Pi Definition registration on original governance; live Units stay separate."""
from pathlib import Path
import hashlib
import sys
from types import SimpleNamespace
import pytest
from ordessa_execution_api.environment import GuaranteeUnavailableError
from ordessa_execution_agents.harness.definitions.runtime_providers import RuntimeProviderDescriptor,RUNTIME_PROVIDER_VERSION
from ordessa_execution_agents.profiles import ProfileRevisionRef
from ordessa_units.management import UnitInstance
from ordessa_units.records import UnitRecords,OperationJournal
from ordessa_units.sessions.evidence import AcpUnitEvidence
from ordessa_units.admission.connection import ConnectionLeasePort
from ordessa_harness_pi import PiAcpHarnessPreparation
from ordessa_harness_pi.server_plugin import PiServerPlugin


@pytest.fixture
def unit(tmp_path):
    class Verifier:
        def verify_and_consume(self,*args):raise AssertionError('registration cannot consume authority')
    verifier=Verifier()
    evidence=AcpUnitEvidence(preparation_authority=lambda *a:None,start_authority=lambda *a:None)
    records=UnitRecords(OperationJournal(tmp_path/'original.sqlite'),scope_authority=SimpleNamespace(issue_scope=lambda *a:None,verify_scope=lambda *a:False),
        native_evidence=evidence,verifier=verifier,epoch_port=SimpleNamespace(current_epoch=lambda *a:0),termination_evidence=evidence)
    evidence.attach_owner(records)
    descriptor=RuntimeProviderDescriptor('pi',RUNTIME_PROVIDER_VERSION,
        {'environmentNamespace':'env','definitionId':'pi','revision':'1'},'sha256:'+'a'*64)
    binary=str(Path(sys.executable).resolve())
    preparation=PiAcpHarnessPreparation(bridge_executable=binary,
        bridge_sha256=hashlib.sha256(Path(binary).read_bytes()).hexdigest(),pi_executable=binary)
    def unavailable(*a,**k):raise AssertionError('registration cannot prepare or spawn')
    environment=SimpleNamespace(identity='environment/fixed',acquire=unavailable)
    instance=UnitInstance(descriptor=descriptor,agent_id='fixed-agent',
        profile_revision=ProfileRevisionRef('env','profile',1,'sha256:'+'b'*64),
        environment_instance=environment,environment_sharing=True,
        environment_reference={'environmentId':environment.identity},preparation=preparation,
        materializer=unavailable,records=records,projection=evidence,verifier=verifier,
        lease_port=ConnectionLeasePort(),termination_evidence=evidence)
    return instance,SimpleNamespace(records=records,verifier=verifier)


def context(view=None,namespace='env',*,bound=True):
    from ordessa_execution_agents.harness.providers.registry import HarnessCatalog
    class Policy:
        def admit_object_access(self,principal,obj,permission):return True
        def admit_invoke(self,*a):raise AssertionError('registration cannot mint authority')
    catalog=HarnessCatalog(namespace,policy=Policy(),principal_scope='controlled') if bound else None
    # The plugin receives the same catalog authority used by the consumer facade.
    return SimpleNamespace(ports={'execution.harness.catalog':catalog},harness_catalog=catalog)


def declaration(*,namespace='env',observer=None):
    from ordessa_execution_agents.harness.providers.registry import (
        HarnessDefinitionDescriptor,HarnessDefinitionDeclaration,HarnessInstallationObservation)
    if observer is None:
        def observer(ref):raise AssertionError('build/list/describe cannot inspect native installation')
    return HarnessDefinitionDeclaration(HarnessDefinitionDescriptor('pi',
        {'environmentNamespace':namespace,'definitionId':'pi','revision':'1'},
        'sha256:'+'a'*64,'acp/v1','reviewed-adapter',backend_version='reviewed-native'),observer)


def test_pi_definition_registration_uses_original_registry_and_never_creates_unit(unit):
    from server_plugin_api import ContributionBatch
    from ordessa_execution_agents.harness.providers.registry import HarnessAdmission
    instance,view=unit;ctx=context(view);catalog=ctx.harness_catalog;calls=[]
    def observe(ref):
        from ordessa_execution_agents.harness.providers.registry import HarnessInstallationObservation
        calls.append(dict(ref))
        return HarnessInstallationObservation('present',native_version='reviewed-native',version_verified=False)
    d=declaration(observer=observe)
    registration=PiServerPlugin(d).build(ctx)
    contributions=registration.contributions
    # The native host contribution carries the frozen declaration opaquely.
    assert type(contributions) is ContributionBatch
    payload=contributions.contributions[0].payload
    assert type(payload) is tuple and payload==(d,)
    contribution=contributions.contributions[0]
    assert contribution.point_id=='execution.harness.definitions'
    assert contribution.api_version=='harness-definition/1' and contribution.required is True
    admission=HarnessAdmission(ctx)
    assert admission.list()==() and calls==[]
    staged=catalog.stage('pi',1,'pi','b'*64,payload)
    assert admission.list()==() and calls==[]
    receipt=staged.commit();admitted=admission.describe(d.descriptor.definition_ref)
    assert receipt==(admitted,)
    assert admitted.owner_activation.plugin_id=='pi' and admitted.owner_activation.generation==1
    assert admitted.descriptor.provider_id=='pi' and dict(admitted.descriptor.definition_ref)=={'environmentNamespace':'env','definitionId':'pi','revision':'1'}
    assert admitted.provider_ref['contractVersion']==RUNTIME_PROVIDER_VERSION
    assert admission.list()==(admitted,) and calls==[]
    assert instance.records is view.records and instance.records.verifier is view.verifier
    assert instance.channel_factory.environment is None
    from ordessa_units.lifecycle.unit_lifecycle import UnitLifecycleRefused
    with pytest.raises(UnitLifecycleRefused,match="preparation receipt unavailable"):
        _ = instance.prepared_unit
    observation=admission.inspect_installation(d.descriptor.definition_ref)
    assert calls==[{'environmentNamespace':'env','installationId':'pi','sourceRevision':'b'*64}]
    assert observation['runtimeReady']=='unknown' and observation['versionVerified'] is False


def test_definition_registration_does_not_require_a_live_unit_owner():
    assert PiServerPlugin(declaration()).build(context()).contributions is not None


def test_missing_original_admission_hook_refuses_before_registration():
    with pytest.raises(GuaranteeUnavailableError):
        PiServerPlugin(declaration()).build(context(bound=False))


def test_missing_original_governance_binding_refused():
    with pytest.raises(GuaranteeUnavailableError,match='original Harness catalog'):
        PiServerPlugin(declaration()).build(SimpleNamespace(ports={}))


@pytest.mark.parametrize('kind',['instance','ducktyped','factory'])
def test_unit_or_old_provider_factory_cannot_register_as_a_definition(unit,kind):
    instance,view=unit
    values={'instance':instance,'ducktyped':SimpleNamespace(descriptor=instance.descriptor,
        records=view.records,_verifier=view.verifier),'factory':lambda *a:instance}
    with pytest.raises(TypeError,match='frozen Pi Harness definition'):
        PiServerPlugin(values[kind])
    assert instance.records is view.records and instance.records.verifier is view.verifier
    assert instance.channel_factory.environment is None


def test_foreign_namespace_refused():
    with pytest.raises(GuaranteeUnavailableError,match='original namespace'):
        PiServerPlugin(declaration()).build(context(namespace='foreign'))


@pytest.mark.parametrize('field',['records','verifier'])
def test_substituted_unit_owner_never_enters_definition_payload(unit,field):
    instance,view=unit;setattr(view,field,object())
    with pytest.raises(TypeError,match='frozen Pi Harness definition'):
        PiServerPlugin(instance)
    assert instance.channel_factory.environment is None


def test_all_old_brand_owners_are_physically_unavailable():
    import importlib.util
    import ordessa_harness_pi
    for name in ('provider','runtime_channel','lifecycle','projection','termination'):
        assert importlib.util.find_spec('ordessa_harness_pi.'+name) is None
    assert ordessa_harness_pi.PiAcpHarnessPreparation.harness_id=='pi'

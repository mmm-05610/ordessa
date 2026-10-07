"""Actual Codex compiler through a temporary real core; no native invocation.

Source-provider fixtures use another actual CodexRuntimeProvider with a distinct
discovery id assigned before admission. Its pure-read ports are never called;
the fixture exists only to attack the core's source generation/version checks.
"""
from dataclasses import replace
from contextlib import contextmanager
import builtins
import io
import os
import socket
import subprocess

import pytest

from ordessa_environment_api import AdmissionRefusedError, GuaranteeUnavailableError, IdentityMismatchError
from ordessa_environment_api.operations import safe_json
from ordessa_harness_codex import CodexRuntimeProvider
from ordessa_harness_codex.provider import DEFAULTS_SCHEMA
from ordessa_persistence_sqlite import SqliteStorePort, ProtectedFingerprintHmac
from pacthold.public import Environment, InstallationRecord
from pacthold.agents.public import (
    AgentContributionSet, ConfigurationContractError, ConfigurationUnsupported,
    OwnerProposalInput, ProfileNotFound, agent_services,
)
from pacthold.agents.runtime import RUNTIME_METHODS

NS = 'codex-owner-attacks'
DEF = {'environmentNamespace':NS,'definitionId':'codex','revision':'1'}
SOURCE_DEF = {'environmentNamespace':NS,'definitionId':'source-codex','revision':'1'}
CHECKER_VERSION = '0.157.1'
FORBIDDEN = tuple(dict.fromkeys(RUNTIME_METHODS + (
    '_read_configuration','_facts','_unit',
)))


class Policy:
    def __init__(self): self.revoked=set()
    def admit_object_access(self,principal,target,access): return target not in self.revoked
    def admit_invoke(self,*args): return True


@pytest.fixture
def setup(tmp_path,monkeypatch):
    assert DEFAULTS_SCHEMA == CHECKER_VERSION
    store = SqliteStorePort(tmp_path/'core.sqlite')
    # Synthetic local fingerprint material only; no real secret resolver.
    fingerprints = ProtectedFingerprintHmac({NS:b'offline-codex-attack-fixture'*2},active_key_id=NS)
    policy=Policy()
    env=Environment(NS,policy=policy,principal_scope='authenticated-test',
                    store=store,fingerprint_port=fingerprints)
    trackers=[]
    def owner_factory(definition=DEF,*,discovery_id='codex'):
        owner=CodexRuntimeProvider(definition_ref=definition,implementation_digest='sha256:'+'a'*64)
        if discovery_id!='codex':
            owner.descriptor=replace(owner.descriptor,provider_id=discovery_id)
        effects={method:0 for method in FORBIDDEN}
        trackers.append((owner,effects))
        for method in FORBIDDEN:
            def forbidden(*args,_method=method,_effects=effects,**kwargs):
                _effects[_method]+=1
                raise AssertionError('native/effect method forbidden: '+_method)
            monkeypatch.setattr(owner,method,forbidden)
        original=owner.assess_configuration_proposal
        owner._test_assess_calls=[]
        owner._test_assess_results=[]
        owner._test_after=lambda:None
        def assess(value,context):
            owner._test_assess_calls.append(value.input_digest)
            result=original(value,context)
            owner._test_assess_results.append(result)
            owner._test_after()
            return result
        monkeypatch.setattr(owner,'assess_configuration_proposal',assess)
        return owner
    env.install(InstallationRecord('codex.plugin','a'*64)); env.enable('codex.plugin')
    owner=owner_factory()
    env.activate('codex.plugin',AgentContributionSet(agent_runtime_providers=(owner,)))
    api=agent_services(env)
    try:
        yield env,policy,owner,api,owner_factory
    finally:
        env.close(); store.close()
        for provider,counts in trackers:
            assert counts=={method:0 for method in FORBIDDEN}
            assert provider._channels=={} and provider._configuration_waiters=={}


def proposal(api,*,sources=()):
    return OwnerProposalInput(DEF,api.providers.describe(DEF)['providerRef'],'1',
        {'declarations':[{'declarationId':'defaults','configurationKind':'codex.defaults',
            'schemaVersion':CHECKER_VERSION,'action':'value','requirement':'required',
            'payload':{'model':'synthetic-model','model_reasoning_effort':'high'}}]},
        sources,({'obligationId':'compile','requirement':'must',
                  'checkerId':'codex.defaults.compile','checkerVersion':CHECKER_VERSION},))


def assert_real_compile_receipt(value,result):
    assert result.status=='valid' and result.input_digest==value.input_digest
    assert result.validation_scope=='codex.defaults.declaration-compile/0.157.1'
    expected={'descriptor':'1'}
    for source in value.source_refs:
        expected[safe_json(source)]=source.get('manifestRevision',source.get('revision'))
    assert result.source_versions==expected
    assert len(result.obligation_results)==1
    row=result.obligation_results[0]
    assert row['status']=='passed' and row['checkerId']=='codex.defaults.compile'
    assert row['checkerVersion']==CHECKER_VERSION and row['sourceVersions']==expected
    assert row['evidenceRefs'][0]['environmentNamespace']==NS
    assert row['evidenceRefs'][0]['inputDigest']==value.input_digest
    assert row['evidenceRefs'][0]['durability']=='computed_nonpersistent'


def make_profile(api):
    return api.profiles.create(profile_id='source-profile',display_name='Controlled source',
        manifest={'harnessDefinitionRef':DEF,'schemaVersion':'profile/1','declarations':[]},
        request=api.profiles.request_key('setup-source-profile')).current_manifest_ref.to_dict()


def test_actual_codex_known_compile_receipt_through_real_core(setup):
    _,_,owner,api,_=setup
    source=make_profile(api)
    value=proposal(api,sources=(source,))
    result=api.providers.assess_configuration_proposal(value)
    assert_real_compile_receipt(value,result)
    assert owner._test_assess_calls==[value.input_digest]
    offers=api.providers.describe_configuration_offers(DEF)
    assert offers.complete is False and offers.offers[0].support_status=='unknown'
    assert offers.offers[0].schema_version==CHECKER_VERSION


@pytest.mark.parametrize('timing',['before','during'])
def test_actual_codex_profile_source_read_revocation(setup,timing):
    _,policy,owner,api,_=setup
    source=make_profile(api)
    value=proposal(api,sources=(source,))
    target=NS+':agents.profile:source-profile'
    if timing=='before': policy.revoked.add(target)
    else: owner._test_after=lambda:policy.revoked.add(target)
    with pytest.raises(AdmissionRefusedError):
        api.providers.assess_configuration_proposal(value)
    if timing=='before':
        assert owner._test_assess_calls==[] and owner._test_assess_results==[]
    else:
        assert owner._test_assess_calls==[value.input_digest]
        assert_real_compile_receipt(value,owner._test_assess_results[0])


@pytest.mark.parametrize('change',['retire','replace','descriptor'])
def test_actual_codex_separate_source_owner_changes_during_assessment(setup,change):
    env,_,owner,api,factory=setup
    source_owner=factory(SOURCE_DEF,discovery_id='source-codex')
    env.install(InstallationRecord('source.plugin','b'*64)); env.enable('source.plugin')
    env.activate('source.plugin',AgentContributionSet(agent_runtime_providers=(source_owner,)))
    old=api.providers.describe(SOURCE_DEF)['providerRef']
    value=proposal(api,sources=(SOURCE_DEF,))
    replacements=[]
    def mutate_source():
        if change=='descriptor':
            source_owner.descriptor=replace(source_owner.descriptor,implementation_digest='sha256:'+'c'*64)
            return
        activation=env.agent_runtime_contribution(SOURCE_DEF).owner_activation
        env.drain(activation)
        assert env.retire(activation)[0]=='retired'
        if change=='replace':
            replacement=factory(SOURCE_DEF,discovery_id='source-codex')
            replacements.append(replacement)
            env.enable('source.plugin')
            env.activate('source.plugin',AgentContributionSet(agent_runtime_providers=(replacement,)))
    owner._test_after=mutate_source
    with pytest.raises((AdmissionRefusedError,GuaranteeUnavailableError)):
        api.providers.assess_configuration_proposal(value)
    assert owner._test_assess_calls==[value.input_digest]
    assert_real_compile_receipt(value,owner._test_assess_results[0])
    assert source_owner._test_assess_calls==[]
    if replacements:
        assert replacements[0]._test_assess_calls==[]
        assert api.providers.describe(SOURCE_DEF)['providerRef']!=old


@pytest.mark.parametrize('kind',['profile','node'])
def test_absent_native_source_refused_before_actual_codex_callback(setup,kind):
    _,_,owner,api,_=setup
    if kind=='profile':
        source={'environmentNamespace':NS,'profileId':'missing-profile','manifestRevision':1,
                'contentDigest':'sha256:'+'b'*64}
        expected=ProfileNotFound
    else:
        source={'environmentNamespace':NS,'instanceId':'missing-node','generation':1}
        expected=GuaranteeUnavailableError
    value=proposal(api,sources=(source,))
    with pytest.raises(expected): api.providers.assess_configuration_proposal(value)
    assert owner._test_assess_calls==[] and owner._test_assess_results==[]


@pytest.mark.parametrize('attack',['foreign_source','foreign_definition','unknown_scheme'])
def test_namespace_and_source_scheme_rejected_before_actual_codex_callback(setup,attack):
    _,_,owner,api,_=setup
    value=proposal(api)
    if attack=='foreign_source':
        source={'environmentNamespace':'foreign','definitionId':'source','revision':'1'}
        with pytest.raises(ConfigurationContractError):
            api.providers.assess_configuration_proposal(replace(value,source_refs=(source,)))
    elif attack=='foreign_definition':
        foreign_definition=dict(DEF,environmentNamespace='foreign')
        foreign_provider=api.providers.describe(DEF)['providerRef']
        foreign_provider['environmentNamespace']='foreign'
        foreign_provider['ownerActivationRef']['environmentNamespace']='foreign'
        foreign_value=replace(value,definition_ref=foreign_definition,provider_ref=foreign_provider)
        with pytest.raises(IdentityMismatchError):
            api.providers.assess_configuration_proposal(foreign_value)
    else:
        source={'environmentNamespace':NS,'arbitraryId':'unregistered','revision':'1'}
        value=replace(value,source_refs=(source,))
        with pytest.raises(ConfigurationUnsupported): api.providers.assess_configuration_proposal(value)
    assert owner._test_assess_calls==[] and owner._test_assess_results==[]


def test_actual_codex_owner_replaced_after_real_assessment_before_core_return(setup):
    env,_,owner,api,factory=setup
    value=proposal(api)
    old=api.providers.describe(DEF)['providerRef']
    replacement=factory()
    def replace_assessed_owner():
        activation=env.agent_runtime_contribution(DEF).owner_activation
        env.drain(activation)
        assert env.retire(activation)[0]=='retired'
        env.enable('codex.plugin')
        env.activate('codex.plugin',AgentContributionSet(agent_runtime_providers=(replacement,)))
    owner._test_after=replace_assessed_owner
    with pytest.raises(AdmissionRefusedError,match='changed during observation'):
        api.providers.assess_configuration_proposal(value)
    assert owner._test_assess_calls==[value.input_digest]
    assert_real_compile_receipt(value,owner._test_assess_results[0])
    assert replacement._test_assess_calls==[]
    assert api.providers.describe(DEF)['providerRef']!=old


@contextmanager
def observe_effect_attempts(monkeypatch):
    """Python effect edges only; SQLite bytes are independently compared below.

    Counters survive swallowed guard errors, so an invalid result cannot hide an
    attempted effect. This is instrumentation, not an OS sandbox claim.
    """
    attempts=[]
    def forbidden(name):
        def fail(*args,**kwargs):
            attempts.append(name)
            raise AssertionError('effect attempted: '+name)
        return fail
    with monkeypatch.context() as guard:
        for module in (builtins,io):
            original=module.open
            def guarded_open(*args,_original=original,**kwargs):
                mode=kwargs.get('mode',args[1] if len(args)>1 else 'r')
                if any(flag in mode for flag in 'wax+'):
                    return forbidden('file.write')()
                return _original(*args,**kwargs)
            guard.setattr(module,'open',guarded_open)
        original_os_open=os.open
        def guarded_os_open(path,flags,*args,**kwargs):
            if flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND):
                return forbidden('os.open.write')()
            return original_os_open(path,flags,*args,**kwargs)
        guard.setattr(os,'open',guarded_os_open)
        for name in ('unlink','remove','rename','replace','mkdir','makedirs','rmdir',
                     'chmod','chown','truncate','write','pwrite','writev','ftruncate',
                     'link','symlink','system','posix_spawn',
                     'posix_spawnp','fork','execv','execve','execvp','execvpe'):
            if hasattr(os,name): guard.setattr(os,name,forbidden('os.'+name))
        guard.setattr(subprocess,'Popen',forbidden('subprocess.Popen'))
        for name in ('connect','connect_ex','sendto','send','sendall'):
            guard.setattr(socket.socket,name,forbidden('socket.'+name))
        yield attempts


def tree_bytes(root):
    return {str(path.relative_to(root)):path.read_bytes() if path.is_file() else None
            for path in root.rglob('*')}


@pytest.mark.parametrize('status',['valid','invalid','unverifiable'])
def test_T57_T62_actual_codex_public_reads_leave_sqlite_and_files_unchanged(setup,tmp_path,monkeypatch,status):
    _,_,owner,api,_=setup
    value=proposal(api,sources=(make_profile(api),))
    if status=='invalid':
        data={'declarations':[dict(value.proposal_data['declarations'][0],payload={'unknown':'field'})]}
        value=replace(value,proposal_data=data)
    elif status=='unverifiable':
        value=replace(value,required_obligations=())
    before=tree_bytes(tmp_path)
    with observe_effect_attempts(monkeypatch) as attempts:
        offers=api.providers.describe_configuration_offers(DEF)
        result=api.providers.assess_configuration_proposal(value)
    assert offers.complete is False and result.status==status
    assert attempts==[]
    after=tree_bytes(tmp_path)
    assert after.keys()==before.keys()
    for name,prior in before.items():
        if name=='core.sqlite-shm':
            # WAL readers may update aReadMark[0..4] in the wal-index header.
            assert len(after[name])==len(prior)
            changed={i for i,(a,b) in enumerate(zip(prior,after[name])) if a!=b}
            assert changed<=set(range(100,120)), changed
        else:
            assert after[name]==prior, name
    assert owner._channels=={} and owner._configuration_waiters=={}


@pytest.mark.parametrize('effect',['write','fd_write','process','network'])
def test_T57_T62_effect_observer_records_attempt_even_when_compiler_swallows_guard(setup,tmp_path,monkeypatch,effect):
    _,_,owner,api,_=setup
    value=proposal(api)
    original=owner._compile_change
    def faulty_compiler(change):
        try:
            if effect=='write': (tmp_path/'forbidden.txt').write_text('forbidden')
            elif effect=='fd_write': os.write(-1,b'forbidden')
            elif effect=='process': subprocess.Popen(['never-start-this-process'])
            else:
                with socket.socket() as connection: connection.connect(('127.0.0.1',1))
        except AssertionError:
            pass
        return original(change)
    monkeypatch.setattr(owner,'_compile_change',faulty_compiler)
    before=tree_bytes(tmp_path)
    with observe_effect_attempts(monkeypatch) as attempts:
        result=api.providers.assess_configuration_proposal(value)
    assert result.status=='valid'
    assert attempts==[{'write':'file.write','fd_write':'os.write','process':'subprocess.Popen','network':'socket.connect'}[effect]]
    assert tree_bytes(tmp_path)==before

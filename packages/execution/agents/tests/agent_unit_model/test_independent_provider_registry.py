"""Actual independent contributions in the sole core registry; no native IO."""
import importlib
from pathlib import Path
import sys

import pytest
from pacthold.adapters.sqlite.environment.store import SqliteStorePort
from pacthold.public import Environment,InstallationRecord
from ordessa_units.public import AgentContributionSet
from ordessa_agents.harness.providers.registry.errors import CatalogAdmissionRefused



from ordessa_units.admission.material_admission import material_registration_snapshot as _test_resource_snapshot

ROOT=Path(__file__).resolve().parents[5]
for source in ('plugins/harness/pi/src','plugins/harness/codex/src','plugins/harness/claude-code/src','packages/execution/agents/src'):
 sys.path.insert(0,str(ROOT/source))

PROVIDERS=(('ordessa_harness_codex','CodexRuntimeProvider','codex'),
 ('ordessa_harness_claude_code','ClaudeCodeRuntimeProvider','claude'))

class Policy:
 def admit_object_access(self,*args): return True
 def admit_invoke(self,*args): return True


@pytest.mark.parametrize('module,class_name,family',PROVIDERS)
def test_independent_package_stage_commit_and_retire(module,class_name,family,tmp_path,request):
 store=SqliteStorePort(tmp_path/(family+'.sqlite'))
 request.addfinalizer(store.close)
 env=Environment('units',store=store,policy=Policy(), resource_extension_snapshot=_test_resource_snapshot)
 try:
  owner='unit-'+family
  env.install(InstallationRecord(owner,'a'*64)); env.enable(owner)
  provider=getattr(importlib.import_module(module),class_name)(
   definition_ref={'environmentNamespace':'units','definitionId':family,'revision':'1'},
   implementation_digest='sha256:'+'b'*64)
  stage=env.stage_activation(owner,AgentContributionSet(agent_runtime_providers=(provider,)))
  with pytest.raises(CatalogAdmissionRefused): env.agent_runtime_contribution(provider.descriptor.definition_ref)
  receipt=stage.commit()
  admitted=env.agent_runtime_contribution(provider.descriptor.definition_ref)
  assert admitted.provider is provider and admitted.owner_activation==receipt.activation
  assert admitted.provider_ref['providerId']==family
  assert env.registry_snapshot.agent_runtime_provider_ids==(family,)
  assert env.registry_snapshot.execution_provider_ids==()
  assert 'start' not in admitted.descriptor.supported_methods
  env.retire_activation(receipt.activation)
  assert store.unresolved_provider_usages(
   'units', receipt.activation.plugin_id, receipt.activation.generation)==()
  with pytest.raises(CatalogAdmissionRefused): env.agent_runtime_contribution(provider.descriptor.definition_ref)
 finally: env.close()


def test_disable_one_independent_owner_does_not_retire_another(tmp_path,request):
 store=SqliteStorePort(tmp_path/"independent-owners.sqlite")
 request.addfinalizer(store.close)
 env=Environment('units',store=store,policy=Policy(), resource_extension_snapshot=_test_resource_snapshot)
 try:
  refs=[]; receipts=[]
  for module,class_name,family in PROVIDERS:
   owner='unit-'+family
   env.install(InstallationRecord(owner,'a'*64)); env.enable(owner)
   provider=getattr(importlib.import_module(module),class_name)(definition_ref={
    'environmentNamespace':'units','definitionId':family,'revision':'1'},implementation_digest='sha256:'+'b'*64)
   receipts.append(env.activate(owner,AgentContributionSet(agent_runtime_providers=(provider,))))
   refs.append(provider.descriptor.definition_ref)
  env.retire_activation(receipts[0].activation)
  assert store.unresolved_provider_usages(
   'units', receipts[0].activation.plugin_id, receipts[0].activation.generation)==()
  with pytest.raises(CatalogAdmissionRefused): env.agent_runtime_contribution(refs[0])
  for ref,receipt in zip(refs[1:],receipts[1:],strict=True):
   assert env.agent_runtime_contribution(ref).owner_activation==receipt.activation
 finally: env.close()

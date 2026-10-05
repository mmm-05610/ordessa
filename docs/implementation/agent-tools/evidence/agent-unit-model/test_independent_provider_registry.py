"""Actual independent contributions in the sole core registry; no native IO."""
import importlib
from pathlib import Path
import sys

import pytest
from pacthold.public import Environment,InstallationRecord
from pacthold.agents.public import AgentContributionSet
from ordessa_environment_api import AdmissionRefusedError

ROOT=Path(__file__).resolve().parents[5]
for source in ('plugins/harness/pi/src','plugins/harness/codex/src','plugins/harness/claude-code/src','packages/backend/harness-transport/src'):
 sys.path.insert(0,str(ROOT/source))

PROVIDERS=(('ordessa_harness_pi','PiRuntimeProvider','pi'),
 ('ordessa_harness_codex','CodexRuntimeProvider','codex'),
 ('ordessa_harness_claude_code','ClaudeCodeRuntimeProvider','claude'))

class Policy:
 def admit_object_access(self,*args): return True
 def admit_invoke(self,*args): return True


@pytest.mark.parametrize('module,class_name,family',PROVIDERS)
def test_independent_package_stage_commit_and_retire(module,class_name,family):
 env=Environment('units',policy=Policy())
 try:
  owner='unit-'+family
  env.install(InstallationRecord(owner,'a'*64)); env.enable(owner)
  provider=getattr(importlib.import_module(module),class_name)(
   definition_ref={'environmentNamespace':'units','definitionId':family,'revision':'1'},
   implementation_digest='sha256:'+'b'*64)
  stage=env.stage_activation(owner,AgentContributionSet(agent_runtime_providers=(provider,)))
  with pytest.raises(AdmissionRefusedError): env.agent_runtime_contribution(provider.descriptor.definition_ref)
  receipt=stage.commit()
  admitted=env.agent_runtime_contribution(provider.descriptor.definition_ref)
  assert admitted.provider is provider and admitted.owner_activation==receipt.activation
  assert admitted.provider_ref['providerId']==family
  assert env.registry_snapshot.agent_runtime_provider_ids==(family,)
  assert env.registry_snapshot.execution_provider_ids==()
  assert 'start' not in admitted.descriptor.supported_methods
  env.retire_activation(receipt.activation)
  with pytest.raises(AdmissionRefusedError): env.agent_runtime_contribution(provider.descriptor.definition_ref)
 finally: env.close()


def test_disable_one_independent_owner_does_not_retire_another():
 env=Environment('units',policy=Policy())
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
  with pytest.raises(AdmissionRefusedError): env.agent_runtime_contribution(refs[0])
  assert env.agent_runtime_contribution(refs[1]).owner_activation==receipts[1].activation
  assert env.agent_runtime_contribution(refs[2]).owner_activation==receipts[2].activation
 finally: env.close()

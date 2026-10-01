"""Seed only an explicitly supplied disposable product root; no channel/model calls."""
import json
import os
from pathlib import Path
import sys
import subprocess
from uuid import uuid4
from ordessa_server_product.composition import create_composition

private = Path(sys.argv[1]).resolve()
if not private.name.startswith('ordessa-profile-ui-'):
    raise ValueError('Disposable UI probe root required')
project = private / 'probe-project'
project.mkdir(mode=0o700)
root = Path(__file__).resolve().parents[3]
module = (root / 'plugins/harness/packaging/native-server-plan.mjs').as_uri()
options = dict(harnessId='codex', nativeProfileHarnesses=['codex'],
    pluginRoot=str(root / 'plugins/harness'),
    artifactRoot=os.environ.get('ORDESSA_NATIVE_PROFILE_ARTIFACT_ROOT')
        or '/opt/ordessa/harnesses/profile-codex-managed/artifacts')
plan = json.loads(subprocess.check_output(['node', '--input-type=module', '-e',
    f'import {{nativeServerPlan}} from {json.dumps(module)}; console.log(JSON.stringify(nativeServerPlan({json.dumps(options)}).args))'], text=True))
runtime = create_composition().native_runtime(private / 'data', plugin_root=root / 'plugins/harness',
    harness_id='codex', adapter_command=plan[plan.index('--native-adapter-command') + 1],
    adapter_args=tuple(arg.split('=', 1)[1] for arg in plan if arg.startswith('--native-adapter-arg=')),
    installed_artifact_root=options['artifactRoot'], native_profile_harnesses=('codex',))
try:
    runtime.start()
    wire = runtime.wire.dispatch
    workspace = wire('workspaces.open', dict(requestId='ui-project-' + uuid4().hex,
        environment=dict(kind='local', host=None, user=None), path=str(project)))['workspace']
    provider = wire('providerModels.create', dict(requestId='ui-provider-' + uuid4().hex,
        harness='codex', provider='openai', displayName='UI official probe', credentialId=None,
        configuration=[dict(controlId='authentication', value='managed-account')],
        protocols=['openai-responses'], endpoints={}, models=[dict(modelId='gpt-5.5', displayName='gpt-5.5',
        availability='available', unavailableReason=None), dict(modelId='gpt-5.6-sol', displayName='gpt-5.6-sol',
        availability='available', unavailableReason=None)]))['providerModel']
    profile = wire('profiles.v2.createProfile', dict(operationKey='ui-profile-' + uuid4().hex,
        realm='local', harnessId='codex', displayName='UI official probe'))['data']['profileId']
    wire('profiles.v2.saveProfile', dict(operationKey='ui-save-' + uuid4().hex, profileId=profile,
        expectedVersion=1, patches=[dict(facetId='assets.model-provider', itemId='choice', op='set',
        value=dict(harnessId='codex', providerConfigId=provider['id'], modelId='gpt-5.5'))]))
    next_profile = wire('profiles.v2.createProfile', dict(operationKey='ui-profile-' + uuid4().hex,
        realm='local', harnessId='codex', displayName='UI next-turn probe'))['data']['profileId']
    wire('profiles.v2.saveProfile', dict(operationKey='ui-save-' + uuid4().hex, profileId=next_profile,
        expectedVersion=1, patches=[dict(facetId='assets.model-provider', itemId='choice', op='set',
        value=dict(harnessId='codex', providerConfigId=provider['id'], modelId='gpt-5.6-sol'))]))
    print(json.dumps(dict(projectId=workspace['id'], profileId=profile, nextProfileId=next_profile, modelCalls=0)))
finally:
    runtime.stop()

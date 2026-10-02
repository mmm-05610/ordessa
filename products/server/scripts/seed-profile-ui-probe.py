"""Seed only an explicitly supplied disposable product root; no channel/model calls."""
import json
import os
from pathlib import Path
import sys
import subprocess
import argparse
from uuid import uuid4
from ordessa_server_product.composition import create_composition

# Never surface credential values, credential paths, or raw provider errors.
sys.excepthook = lambda kind, error, trace: print('PROFILE_UI_SEED_FAILED', file=sys.stderr)
parser = argparse.ArgumentParser()
parser.add_argument('private')
parser.add_argument('--brand', choices=('codex', 'pi', 'claude-code'), default='codex')
parser.add_argument('--allow-model-calls', action='store_true')
parser.add_argument('--key-file', type=Path)
parser.add_argument('--cleanup', action='store_true')
args = parser.parse_args()
private = Path(args.private).resolve()
if not private.name.startswith('ordessa-profile-ui-'):
    raise ValueError('Disposable UI probe root required')
brand = args.brand
project = private / 'probe-project'
if not args.cleanup:
    project.mkdir(mode=0o700)
root = Path(__file__).resolve().parents[3]
module = (root / 'plugins/harness/packaging/native-server-plan.mjs').as_uri()
asset_roots = {
    'codex': os.environ.get('ORDESSA_NATIVE_PROFILE_ARTIFACT_ROOT') or '/opt/ordessa/harnesses/profile-codex-catalog-fast-off-v6/artifacts',
    'pi': os.environ.get('ORDESSA_PI_PROFILE_ARTIFACT_ROOT') or '/opt/ordessa/harnesses/profile-pi-registration-owner-bound/artifacts',
    'claude-code': os.environ.get('ORDESSA_CLAUDE_PROFILE_ARTIFACT_ROOT') or '/opt/ordessa/harnesses/profile-claude-provider-restoration/artifacts',
}
native_brands = [] if brand == 'pi' else [brand]
options = dict(harnessId=brand, nativeProfileHarnesses=native_brands, piProfileBridge=brand == 'pi',
    pluginRoot=str(root / 'plugins/harness'),
    artifactRoot=asset_roots[brand])
plan = json.loads(subprocess.check_output(['node', '--input-type=module', '-e',
    f'import {{nativeServerPlan}} from {json.dumps(module)}; console.log(JSON.stringify(nativeServerPlan({json.dumps(options)}).args))'], text=True, stderr=subprocess.PIPE))
runtime = create_composition().native_runtime(private / 'data', plugin_root=root / 'plugins/harness',
    harness_id=brand, adapter_command=plan[plan.index('--native-adapter-command') + 1],
    adapter_args=tuple(arg.split('=', 1)[1] for arg in plan if arg.startswith('--native-adapter-arg=')),
    installed_artifact_root=options['artifactRoot'], native_profile_harnesses=tuple(native_brands),
    pi_profile_bridge=brand == 'pi')
try:
    runtime.start()
    if args.cleanup:
        from ordessa_server.credentials import CredentialRecords
        records = [record for record in CredentialRecords(runtime.database).list() if record['kind'] == 'api-key']
        for row in records:
            locator = CredentialRecords(runtime.database).get(row['credentialId'], kind='api-key')['secret_locator']
            runtime.secret_store.delete(locator)
        print(json.dumps(dict(ownCredentialCount=len(records), deleted=True)))
        sys.exit(0)
    wire = runtime.wire.dispatch
    workspace = wire('workspaces.open', dict(requestId='ui-project-' + uuid4().hex,
        environment=dict(kind='local', host=None, user=None), path=str(project)))['workspace']
    credential_id = None
    if brand != 'codex' and args.allow_model_calls:
        if args.key_file is None or not args.key_file.is_absolute():
            raise ValueError('Explicit absolute key file required')
        with args.key_file.open() as source:
            key = source.readline().strip()
        if not key:
            raise ValueError('Empty authorized credential')
        imported = wire('modelProvider.importApiKey', dict(requestId='ui-key-' + uuid4().hex,
            harnessId=brand, apiKey=key))
        del key
        if imported['state'] != 'imported':
            raise RuntimeError('Key import refused')
        credential_id = imported['credentialId']
    protocol, endpoint, models = {
        'codex': ('openai-responses', None, ('gpt-5.5', 'gpt-5.6-sol')),
        'pi': ('openai-chat', 'https://api.deepseek.com', ('deepseek-flash', 'deepseek-v4-pro')),
        'claude-code': ('anthropic-messages', 'https://api.deepseek.com/anthropic', ('haiku', 'sonnet')),
    }[brand]
    provider = wire('providerModels.create', dict(requestId='ui-provider-' + uuid4().hex,
        harness=brand, provider='openai' if brand == 'codex' else 'deepseek',
        displayName='UI official probe' if brand == 'codex' else 'UI DeepSeek probe', credentialId=credential_id,
        configuration=[dict(controlId='authentication', value='managed-account')] if brand == 'codex' else [],
        protocols=[protocol], endpoints={} if endpoint is None else {protocol: endpoint},
        models=[dict(modelId=model, displayName=model, availability='available', unavailableReason=None) for model in models]))['providerModel']
    profile = wire('profiles.v2.createProfile', dict(operationKey='ui-profile-' + uuid4().hex,
        realm='local', harnessId=brand, displayName='UI official probe'))['data']['profileId']
    wire('profiles.v2.saveProfile', dict(operationKey='ui-save-' + uuid4().hex, profileId=profile,
        expectedVersion=1, patches=[dict(facetId='assets.model-provider', itemId='choice', op='set',
        value=dict(harnessId=brand, providerConfigId=provider['id'], modelId=models[0]))]))
    next_profile = wire('profiles.v2.createProfile', dict(operationKey='ui-profile-' + uuid4().hex,
        realm='local', harnessId=brand, displayName='UI next-turn probe'))['data']['profileId']
    wire('profiles.v2.saveProfile', dict(operationKey='ui-save-' + uuid4().hex, profileId=next_profile,
        expectedVersion=1, patches=[dict(facetId='assets.model-provider', itemId='choice', op='set',
        value=dict(harnessId=brand, providerConfigId=provider['id'], modelId=models[1]))]))
    print(json.dumps(dict(harness=brand, profileCount=2, modelCalls=0, credentialImported=credential_id is not None)))
finally:
    runtime.stop()

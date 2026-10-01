"""Trusted brand dispatch for C4 live model services; no product/host knowledge."""
import json
from pathlib import Path
import subprocess

from ordessa_harness_api import Installation
from ...application.action_execution import ActionGrant
from ...application.configuration_service import ConfigurationApplicationService
from ...application.operation_journal import OperationJournal
from .bridge import ADAPTER_IDS


PINS = {'codex': ('codex-runtime', '@agentclientprotocol/codex-acp', '1.1.14'),
        'claude-code': ('claude-runtime', '@agentclientprotocol/claude-agent-acp', '0.81.2')}


def verified_installation(brand, artifact_base):
    if brand == 'pi':
        from ...pi.configuration.service import verified_installation as verify_pi
        return verify_pi(artifact_base)
    if brand not in PINS:
        raise ValueError('Pinned native Profile brand required')
    artifact, package, version = PINS[brand]
    policy = Path(__file__).resolve().parents[4] / 'runtime/native-artifact-policy.mjs'
    script = """import fs from 'node:fs'; import path from 'node:path';
      import {pathToFileURL} from 'node:url';
      const {verifyInstalledArtifact}=await import(pathToFileURL(process.argv[1]).href);
      verifyInstalledArtifact({artifactBase:process.argv[2],artifact:process.argv[3],
        packageName:process.argv[4],version:process.argv[5],variant:'native-profile'});
      const m=JSON.parse(fs.readFileSync(path.join(process.argv[2],process.argv[3]+'.manifest.json'),'utf8'));
      console.log(JSON.stringify({digest:m.treeDigest}));"""
    result = subprocess.run(['/usr/bin/node', '--input-type=module', '-e', script,
        str(policy), str(artifact_base), artifact, package, version], capture_output=True, text=True,
        timeout=30, check=True)
    observed = json.loads(result.stdout)
    return Installation(brand, tuple(map(int, version.split('.'))), (1, 0, 0),
                        'installed-' + brand + ':' + observed['digest'])


def create_model_service(*, registry, owners, target, carrier, installation, journal_path, credential_binding=None):
    if installation.harness_id == 'pi':
        from ...pi.configuration.service import create_model_service as create_pi
        return create_pi(registry=registry, owners=owners, target=target, carrier=carrier,
                         installation=installation, journal_path=journal_path, credential_binding=credential_binding)
    from ...codex.configuration.runtime import CodexLiveModelRuntime
    from ...claude.configuration.runtime import ClaudeLiveModelRuntime
    runtimes = {'codex': CodexLiveModelRuntime, 'claude-code': ClaudeLiveModelRuntime}
    brand = installation.harness_id
    if brand not in runtimes:
        raise ValueError('Pinned native Profile brand required')
    views = [view for view in carrier.contributions('harness.configuration-adapters')
             if view.payload.descriptor.adapter_id == ADAPTER_IDS[brand]]
    if len(views) != 1:
        raise ValueError('One published matching model adapter required')
    view = views[0]
    runtime = runtimes[brand](registry, owners, target=target, installation=installation,
        private_root=Path(journal_path).parent / 'unused-live-generations',
        publication_revision=view.publication_token, credential_binding=credential_binding)
    grant = ActionGrant(target, view.owner, view.publication_token, 'assets.model-provider', 'choice',
                        '1', 'acp.session.set-config-option', '1')
    service = ConfigurationApplicationService(principal='profile-owner', target=target,
        carrier=carrier, runtime=runtime, permits=None, owner_application=True,
        journal=OperationJournal(journal_path), action_executor=runtime, action_grants=(grant,))
    return service, runtime

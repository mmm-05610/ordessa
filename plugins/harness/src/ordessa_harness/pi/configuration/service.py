"""Trusted Pi composition: installed identity, current C2 publication and C4."""
import json
from pathlib import Path
import subprocess

from ordessa_harness_api import Installation
from ...application.action_execution import ActionGrant
from ...application.configuration_service import ConfigurationApplicationService
from ...application.operation_journal import OperationJournal
from .runtime import PiLiveModelRuntime


def verified_installation(artifact_base):
    policy = Path(__file__).resolve().parents[4] / "runtime/native-artifact-policy.mjs"
    script = """import fs from 'node:fs'; import path from 'node:path';
      import {pathToFileURL} from 'node:url';
      const {verifyInstalledArtifact}=await import(pathToFileURL(process.argv[1]).href);
      verifyInstalledArtifact({artifactBase:process.argv[2],artifact:'pi-profile-runtime',
        packageName:'@automatalabs/pi-acp',version:'0.5.0',variant:'pi-profile'});
      const m=JSON.parse(fs.readFileSync(path.join(process.argv[2],'pi-profile-runtime.manifest.json'),'utf8'));
      console.log(JSON.stringify({digest:m.treeDigest}));"""
    result = subprocess.run(["/usr/bin/node", "--input-type=module", "-e", script,
                             str(policy), str(artifact_base)], capture_output=True, text=True,
                            timeout=30, check=True)
    observed = json.loads(result.stdout)
    return Installation("pi", (0, 5, 0), (1, 0, 0), "installed-pi:" + observed["digest"])


def create_model_service(*, registry, owners, target, carrier, installation, journal_path, credential_binding=None):
    views = [view for view in carrier.contributions("harness.configuration-adapters")
             if view.payload.descriptor.adapter_id == "assets.model-provider.pi"]
    if len(views) != 1:
        raise ValueError("One published Pi model adapter required")
    view = views[0]
    runtime = PiLiveModelRuntime(registry, owners, target=target, installation=installation,
        private_root=Path(journal_path).parent / "unused-live-generations",
        publication_revision=view.publication_token, credential_binding=credential_binding)
    grant = ActionGrant(target, view.owner, view.publication_token, "assets.model-provider", "choice",
                        "1", "acp.session.set-config-option", "1")
    service = ConfigurationApplicationService(principal="profile-owner", target=target,
        carrier=carrier, runtime=runtime, permits=None, owner_application=True,
        journal=OperationJournal(journal_path), action_executor=runtime, action_grants=(grant,))
    return service, runtime

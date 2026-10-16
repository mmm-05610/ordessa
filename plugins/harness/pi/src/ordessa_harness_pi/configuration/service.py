"""Trusted Pi composition: installed identity, current C2 publication and C4."""
from ..acp_artifact_declarations import artifact_declaration
from ordessa_infrastructure.encoding.canonical_json import canonical_text
import json
from pathlib import Path
import subprocess

from ordessa_execution_agents.harness.definitions import Installation
from ordessa_units.records.operation_journal import OperationJournal
from ordessa_execution_agents.harness.providers.resolution.verifier_deployment import installed_verifier
from .runtime import PiLiveModelRuntime


def verified_installation(artifact_base):
    fact = artifact_declaration()
    extension = fact["profileExtension"]
    extension_policy = canonical_text({**extension, "mode": "profile", "variant": "pi-profile"})
    script = """import fs from 'node:fs'; import path from 'node:path';
      import {pathToFileURL} from 'node:url';
      const {verifyInstalledArtifact}=await import(pathToFileURL(process.argv[1]).href);
      verifyInstalledArtifact({artifactBase:process.argv[2],artifact:'pi-profile-runtime',
        packageName:'@automatalabs/pi-acp',version:'0.5.0',variant:'pi-profile',extensionPolicy:JSON.parse(process.argv[3])});
      const m=JSON.parse(fs.readFileSync(path.join(process.argv[2],'pi-profile-runtime.manifest.json'),'utf8'));
      console.log(JSON.stringify({digest:m.treeDigest}));"""
    with installed_verifier() as (node, policy):
        result = subprocess.run([node, "--input-type=module", "-e", script,
                                 str(policy), str(artifact_base), extension_policy], capture_output=True, text=True,
                                timeout=30, check=True)
    observed = json.loads(result.stdout)
    return Installation("pi", (0, 5, 0), (1, 0, 0), "installed-pi:" + observed["digest"])


def create_model_service(*, registry, owners, target, carrier, installation, journal_path,
                         runtime_factory, context_factory, action_grant_factory,
                         service_factory, descriptor_admission, credential_binding=None):
    if not all(callable(factory) for factory in (runtime_factory, context_factory,
                                                action_grant_factory, service_factory, descriptor_admission)):
        raise ValueError("Explicit Pi runtime, context, action grant and service factories required")
    views = [view for view in carrier.contributions("harness.configuration-adapters")
             if descriptor_admission(view.payload, view.owner, "harness.configuration-adapters").adapter_id == "assets.model-provider.pi"]
    if len(views) != 1:
        raise ValueError("One published Pi model adapter required")
    view = views[0]
    runtime = PiLiveModelRuntime(registry, owners, target=target, installation=installation,
        private_root=Path(journal_path).parent / "unused-live-generations",
        publication_revision=view.publication_token, credential_binding=credential_binding,
        runtime_factory=runtime_factory, context_factory=context_factory)
    grant = action_grant_factory(target, view.owner, view.publication_token, "assets.model-provider", "choice",
                        "1", "acp.session.set-config-option", "1")
    service = service_factory(principal="profile-owner", target=target,
        carrier=carrier, runtime=runtime, permits=None, owner_application=True,
        descriptor_admission=descriptor_admission,
        journal=OperationJournal(journal_path), action_executor=runtime, action_grants=(grant,))
    return service, runtime

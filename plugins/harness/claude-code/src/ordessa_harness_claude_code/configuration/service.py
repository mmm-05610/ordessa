"""Installed native identity verification owned by this brand."""
from ..acp_artifact_declarations import artifact_declaration
from ordessa_infrastructure.encoding.canonical_json import canonical_text
import json
import subprocess
from ordessa_execution_agents.harness.definitions import Installation
from ordessa_execution_agents.harness.providers.resolution.verifier_deployment import installed_verifier

def verified_installation(artifact_base):
    fact = artifact_declaration()
    extension = fact["nativeExtension"]
    brand, artifact, package, version = fact["id"], fact["managed"]["artifact"], extension["packageName"], extension["version"]
    extension_policy = canonical_text({**extension, "mode": "native", "variant": "native-profile"})
    script = """import fs from 'node:fs'; import path from 'node:path';
      import {pathToFileURL} from 'node:url';
      const {verifyInstalledArtifact}=await import(pathToFileURL(process.argv[1]).href);
      verifyInstalledArtifact({artifactBase:process.argv[2],artifact:process.argv[3],
        packageName:process.argv[4],version:process.argv[5],variant:'native-profile',extensionPolicy:JSON.parse(process.argv[6])});
      const m=JSON.parse(fs.readFileSync(path.join(process.argv[2],process.argv[3]+'.manifest.json'),'utf8'));
      console.log(JSON.stringify({digest:m.treeDigest}));"""
    with installed_verifier() as (node, policy):
        result = subprocess.run([node, '--input-type=module', '-e', script,
            str(policy), str(artifact_base), artifact, package, version, extension_policy], capture_output=True, text=True,
            timeout=30, check=True)
    observed = json.loads(result.stdout)
    return Installation(brand, tuple(map(int, version.split('.'))), (1, 0, 0),
                        'installed-' + brand + ':' + observed['digest'])


"""Brand-owned native model policy and installation facts.

Preserved pure preparation, validation, launch selection and installation
observation. This module does not construct a C4 runtime, action executor,
permission, journal or direct configuration writer.
"""
import json
import subprocess
from ordessa_agents.sdk import NativeModelLaunchRefused
from ordessa_agents.sdk import build_initial_model_params
from ordessa_agents.sdk import Installation, ConfigurationAdapterDescriptor, FieldClaim, VersionRange
from ordessa_agents.sdk import (
    FACET_ID, FACET_SCHEMA_VERSION, ENTRY, ENV_HANDLE_SUFFIX, choice_payload_schema, native_version_range)
from ordessa_agents.sdk import installed_verifier
from ordessa_agents.sdk import canonical_text
from .acp_artifact_declarations import artifact_declaration
from . import acp_model_facts as facts

HARNESS_ID = 'claude-code'

HANDLE_ID = 'claude.settings.json'

SECRET_SLOT = 'ANTHROPIC_AUTH_TOKEN'

ADAPTER_VERSION = (1, 0, 0)

def descriptor() -> ConfigurationAdapterDescriptor:
    return ConfigurationAdapterDescriptor(
        ADAPTER_ID, 'v1', FACET_ID, FACET_SCHEMA_VERSION, HARNESS_ID,
        native_version_range(facts.VERSION_RANGE), VersionRange(ADAPTER_VERSION),
        (ENTRY,), choice_payload_schema(), (
            FieldClaim('file', HANDLE_ID, ('session','model')),
            FieldClaim('file', HANDLE_ID, ('env',)),
            FieldClaim('environment', HANDLE_ID + ENV_HANDLE_SUFFIX, (SECRET_SLOT,)),
        ))

ADAPTER_ID = 'assets.model-provider.claude'
harness_id = 'claude-code'
native_version = (0, 81, 2)
managed_account_supported = False
live_registration = False
provider_restoration = True
single_root_alias = False

def initial_model_params(payload, operation_id, *, credential=None, models=None):
    return build_initial_model_params(payload, operation_id,
        protocol='anthropic-messages', provider_id='main', api='anthropic', api_key_header='x-api-key', credential=credential, models=models)

def requires_catalog(credential):
    return False

def preparation_params(payload, operation_id, *, credential=None, models=None):
    return initial_model_params(payload, operation_id, credential=credential, models=models)

def launch_options(payload, *, managed_account_factory=None):
    if payload.get('authentication') != 'managed-account':
        return {}
    initial_model_params(payload, 'create:launch-check')
    if not callable(managed_account_factory):
        raise NativeModelLaunchRefused('APPLICATION_PORT_ABSENT', 'Managed account launch unavailable')
    account = managed_account_factory('claude-code')
    raise NativeModelLaunchRefused('APPLICATION_PORT_ABSENT', 'Managed account Harness unavailable')

def authenticated(account):
    return False

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

def create_managed_account(artifact_root):
    raise NativeModelLaunchRefused('APPLICATION_PORT_ABSENT', 'Managed account Harness unavailable')

initial_params = initial_model_params
prepare = preparation_params
launch = launch_options
verify_installation = verified_installation

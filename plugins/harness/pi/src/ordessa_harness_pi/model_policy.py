"""Brand-owned native model policy and installation facts.

Preserved pure preparation, validation, launch selection and installation
observation. This module does not construct a C4 runtime, action executor,
permission, journal or direct configuration writer.
"""
import json
import subprocess
from ordessa_execution_agents.sdk import NativeModelLaunchRefused
from ordessa_execution_agents.sdk import build_initial_model_params
from ordessa_execution_agents.sdk import Installation, ConfigurationAdapterDescriptor, FieldClaim, VersionRange
from ordessa_execution_agents.sdk import (
    FACET_ID, FACET_SCHEMA_VERSION, ENTRY, ENV_HANDLE_SUFFIX, choice_payload_schema, native_version_range)
from ordessa_execution_agents.sdk import installed_verifier
from ordessa_execution_agents.sdk import canonical_text
from .acp_artifact_declarations import artifact_declaration
from . import acp_model_facts as facts

HARNESS_ID = 'pi'

HANDLE_ID = 'pi.models.json'

SECRET_SLOT = 'api_key'

ADAPTER_VERSION = (1, 0, 0)

def descriptor() -> ConfigurationAdapterDescriptor:
    return ConfigurationAdapterDescriptor(
        ADAPTER_ID, 'v1', FACET_ID, FACET_SCHEMA_VERSION, HARNESS_ID,
        native_version_range(facts.VERSION_RANGE), VersionRange(ADAPTER_VERSION),
        (ENTRY,), choice_payload_schema(), (
            FieldClaim('file', HANDLE_ID, ('session','model')),
            FieldClaim('file', HANDLE_ID, ('providers',)),
            FieldClaim('file', facts.PI_SETTINGS_HANDLE_ID, ('retry',)),
            FieldClaim('environment', HANDLE_ID + ENV_HANDLE_SUFFIX, (SECRET_SLOT,)),
        ))

ADAPTER_ID = 'assets.model-provider.pi'
harness_id = 'pi'
native_version = (0, 5, 0)
managed_account_supported = False
live_registration = True
provider_restoration = False
single_root_alias = True

def initial_model_params(payload, operation_id, *, credential=None, models=None):
    return build_initial_model_params(payload, operation_id,
        protocol='openai-chat', provider_id=None, api='openai-completions', catalogue=True, credential=credential, models=models)

def requires_catalog(credential):
    return credential is not None

def preparation_params(payload, operation_id, *, credential=None, models=None):
    if credential is None:
        return None
    return initial_model_params(payload, operation_id, credential=credential, models=models)

def launch_options(payload, *, managed_account_factory=None):
    if payload.get('authentication') != 'managed-account':
        return {}
    initial_model_params(payload, 'create:launch-check')
    if not callable(managed_account_factory):
        raise NativeModelLaunchRefused('APPLICATION_PORT_ABSENT', 'Managed account launch unavailable')
    account = managed_account_factory('pi')
    raise NativeModelLaunchRefused('APPLICATION_PORT_ABSENT', 'Managed account Harness unavailable')

def authenticated(account):
    return False

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

def create_managed_account(artifact_root):
    raise NativeModelLaunchRefused('APPLICATION_PORT_ABSENT', 'Managed account Harness unavailable')

initial_params = initial_model_params
prepare = preparation_params
launch = launch_options
verify_installation = verified_installation

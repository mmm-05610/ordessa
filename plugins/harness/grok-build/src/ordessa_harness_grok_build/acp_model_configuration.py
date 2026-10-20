"""grok-build pure model configuration boundary; pinned native facts are absent.

The old AdapterContext/target/intent runtime is retired. Channel executable pins
are not model-configuration evidence, and no applied/readback result is invented.
"""
from collections.abc import Mapping
from ordessa_execution_agents.sdk import HarnessError
from . import acp_model_facts as common

ADAPTER_ID='assets.model-provider.grok-build'
CONTRIBUTOR_VERSION='1'
GROK_BUILD_MODEL_KIND=common.GROK_BUILD_MODEL_KIND


def registration_manifest():
    # Pure historical vocabulary, never a live adapter registration or grant.
    return {'adapter_id':ADAPTER_ID,'facet_id':'assets.model-provider',
        'facet_schema_version':1,'api_version':'v1','harness_id':'grok-build',
        'kind':common.GROK_BUILD_MODEL_KIND,
        'supported_native_versions':common.RANGE_STRINGS['grok-build'],
        'native_target':common.NATIVE_TARGET['grok-build'],'entries':(),
        'payload_schema':'model-provider.choice.v1','claims':{}}


def compile_config(materials):
    if not isinstance(materials,Mapping):raise HarnessError('CONFIGURATION_INVALID')
    if materials:raise HarnessError('MODEL_CONFIGURATION_UNAVAILABLE')
    return {}

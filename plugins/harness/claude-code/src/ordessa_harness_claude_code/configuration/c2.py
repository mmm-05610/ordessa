"""Brand-owned pure C2 model provider; host effects are not constructed here."""
from ..production import MODEL_CONTROL_ID
from ordessa_execution_agents.harness.definitions import ConfigurationAdapterDescriptor, FieldClaim, VersionRange
from ordessa_execution_agents.harness.configuration.compilation.model_choice import (
    ModelChoiceAdapter, FACET_ID, FACET_SCHEMA_VERSION, ENTRY, ENV_HANDLE_SUFFIX,
    choice_payload_schema, native_version_range)
from .. import acp_model_facts as facts
from ..acp_model_configuration import ClaudeAdapter, ADAPTER_ID
from .live_model import compile_live_model

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


def _compile_native(context, desired, source):
    return compile_live_model(context.native_snapshot, desired, source, credential_binding=context.credential_binding)

def configuration_adapter():
    return ModelChoiceAdapter(
        descriptor=descriptor(), local_adapter=ClaudeAdapter(),
        compile_native=_compile_native, project_mount=None,
        target_handle_id=HANDLE_ID, minimum_native_version=facts.VERSION_RANGE[0])

def reconfiguration_for(payload):
    return configuration_adapter().reconfiguration_for(payload)


def declared_protocols():
    """Public declaration, without installation or live availability evidence."""
    return {protocol: 'declared' for protocol in facts.DIALECT}


def declared_dialects():
    """Detached native field declarations from this provider's sole facts owner."""
    from types import MappingProxyType
    return MappingProxyType(dict(facts.DIALECT))


def supported_native_versions():
    return facts.VERSION_RANGE


def declared_model_control():
    """The declared Profile model-reference control, from this brand's sole facts."""
    return MODEL_CONTROL_ID

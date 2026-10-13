"""Own public build/template port: same captured capability callback is required."""
from functools import partial
from types import MappingProxyType
from ordessa_execution_agents.harness.providers.declarations import InstallationRecipe, BuildRecipeFiles
from . import production

INSTALLATION_OWNER_ID = 'kilo'

def installation_owner_id():
    return INSTALLATION_OWNER_ID

def installation_requires_npm():
    return True

def installation_declaration(*, capabilities_for, build_files: BuildRecipeFiles):
    if not callable(capabilities_for):
        raise TypeError("explicit captured capabilities callback required")
    if type(build_files) is not BuildRecipeFiles:
        raise TypeError("explicit BuildRecipeFiles required")
    build_files.require(owner_id=installation_owner_id(), requires_npm=installation_requires_npm())
    facts = {name: getattr(production, name) for name in ('PRODUCT_MODEL_ID', 'OFFICIAL_BASE_URL', 'CREDENTIAL_ENVIRONMENT', 'CREDENTIAL_KIND', 'NATIVE_MODEL_VALUE', 'NATIVE_MODEL_ID', 'NATIVE_MODEL_SELECTION', 'ADAPTER_COMMAND', 'ADAPTER_ARGS', 'ADAPTER_ARTIFACT_ENTRY', 'BINARY_TARGET', 'ARTIFACT_TARGET', 'ARTIFACT_NAME', 'BINARY_NAME', 'STATE_TARGET') if hasattr(production, name)}
    facts["deployment_document"] = partial(production.deployment_document, capabilities_for=capabilities_for)
    if hasattr(production, "models_document"):
        facts["models_document"] = production.models_document
    return InstallationRecipe(
        owner_id=installation_owner_id(), builder=build_files.builder,
        npm_root=build_files.npm_root, facts=MappingProxyType(facts),
    )

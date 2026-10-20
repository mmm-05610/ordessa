"""Original BCA 020 identity assertions, isolated from retired runtime setup.

This exercises the existing pure reference validator and current Agent-owned
configuration descriptor/pin DTOs. The descriptor and owner activation are
controlled data, not evidence of admission or an authorized material handoff.
The original BCA longitudinal assertions remain in their original test file.
No Unit runtime, Environment, grant issuer or provider is constructed here.
"""
import pytest

from ordessa_execution_agents.harness.definitions.activation import HarnessActivationRef
from ordessa_execution_agents.harness.definitions.configuration_providers import (
    CONFIGURATION_PROVIDER_VERSION, ConfigurationContractError,
    ConfigurationProviderDescriptor, ConfigurationProviderPin, ConfigurationRoute,
)
from ordessa_units.configuration.references import (
    ConfigurationReference, ConfigurationReferenceExtraction, validate_reference_extraction,
)
from ordessa_units.bindings.materials import ResourceRef

ENV = "bca-longitudinal"
CONTRACT_ID = "sample.alpha@1"
CONFIG_PROVIDER_ID = "fixture.config"
MATERIAL_PROVIDER_ID = "provider.material"
RUNTIME_DEFINITION = {"environmentNamespace": ENV, "definitionId": "fixture", "revision": "1"}
CONFIG_IMPLEMENTATION = "sha256:" + "b" * 64
CONFIGURATION_KIND = "assets.model-provider"
CONFIGURATION_SCHEMA = "schema/1"
DECLARATION_DIGEST = "c" * 64
DECLARATION_ID = "declaration-bca"


def test_original_bca_reference_extraction_exact_identity_contract():
    descriptor = ConfigurationProviderDescriptor(
        CONFIG_PROVIDER_ID, CONFIGURATION_PROVIDER_VERSION, CONFIG_IMPLEMENTATION,
        (ConfigurationRoute(CONFIGURATION_KIND, CONFIGURATION_SCHEMA,
                            (dict(RUNTIME_DEFINITION),), ("value",), ("model.selection",)),),
        ("describe", "validate", "extract_references"))
    owner_activation = HarnessActivationRef(ENV, "fixture.plugin", 1)
    config_pin = ConfigurationProviderPin(
        descriptor.provider_id,
        descriptor.contract_version,
        descriptor.implementation_digest,
        owner_activation)
    resource_ref = ResourceRef(ENV, MATERIAL_PROVIDER_ID, CONTRACT_ID,
                               "resource-bca", "r1")
    extraction = ConfigurationReferenceExtraction(
        DECLARATION_ID, CONFIGURATION_KIND, CONFIGURATION_SCHEMA, "value",
        DECLARATION_DIGEST, dict(RUNTIME_DEFINITION), config_pin,
        "complete",
        (ConfigurationReference("material.profile", resource_ref,
                                "profile-material"),),
        None)
    validated = validate_reference_extraction(
        descriptor, extraction,
        expected_pin=config_pin,
        expected_declaration={
            "declarationId": DECLARATION_ID,
            "configurationKind": descriptor.routes[0].configuration_kind,
            "schemaVersion": descriptor.routes[0].schema_version,
            "action": "value",
            "declarationDigest": DECLARATION_DIGEST,
            "definitionRef": dict(RUNTIME_DEFINITION)})
    assert validated.to_dict() == extraction.to_dict()
    # Preserve the original exact ResourceRef equality. This isolated contract
    # does not perform the original C material handoff.
    assert validated.references[0].resource_ref == resource_ref
    # Tampered identities are typed refusals, not silent acceptances.
    foreign_pin = ConfigurationProviderPin(
        CONFIG_PROVIDER_ID, CONFIGURATION_PROVIDER_VERSION,
        CONFIG_IMPLEMENTATION, HarnessActivationRef(ENV, "fixture.plugin", 99))
    with pytest.raises(ConfigurationContractError):
        validate_reference_extraction(
            descriptor, extraction, expected_pin=foreign_pin,
            expected_declaration={
                "declarationId": DECLARATION_ID,
                "configurationKind": CONFIGURATION_KIND,
                "schemaVersion": CONFIGURATION_SCHEMA, "action": "value",
                "declarationDigest": DECLARATION_DIGEST,
                "definitionRef": dict(RUNTIME_DEFINITION)})
    foreign_extraction = ConfigurationReferenceExtraction(
        DECLARATION_ID, CONFIGURATION_KIND, CONFIGURATION_SCHEMA, "value",
        DECLARATION_DIGEST,
        {"environmentNamespace": ENV, "definitionId": "nobody",
         "revision": "1"},
        config_pin, "complete", (), None)
    with pytest.raises(ConfigurationContractError):
        validate_reference_extraction(
            descriptor, foreign_extraction,
            expected_pin=config_pin,
            expected_declaration={
                "declarationId": DECLARATION_ID,
                "configurationKind": CONFIGURATION_KIND,
                "schemaVersion": CONFIGURATION_SCHEMA, "action": "value",
                "declarationDigest": DECLARATION_DIGEST,
                "definitionRef": dict(RUNTIME_DEFINITION)})


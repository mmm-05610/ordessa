"""Pure ConfigurationProvider route/reference contracts for AT-020.

This file validates immutable data and exact declaration binding only. It does
not exercise Registry admission, reference extraction from payloads, material
resolution, compilation, Harness control, or native configuration effects.
"""
import pytest

from ordessa_environment_api import ActivationRef
from pacthold.core.configuration_admission import ConfigurationContractError
from pacthold.agents.public import (
    CONFIGURATION_METHODS,
    CONFIGURATION_PROVIDER_VERSION,
    ConfigurationProviderDescriptor,
    ConfigurationProviderPin,
    ConfigurationProviderContractError,
    ConfigurationReference,
    ConfigurationReferenceExtraction,
    ConfigurationRoute,
    ResourceRef,
    validate_reference_extraction,
)
from pacthold.agents.configuration.change import ConfigurationContractError as LegacyConfigurationContractError
from pacthold.agents.public import ConfigurationContractError as LegacyPublicConfigurationContractError


_ENV = "env"
_PROVIDER_ID = "configuration.alpha"
_PROVIDER_DIGEST = "sha256:" + "a" * 64
_DECLARATION_DIGEST = "b" * 64
_KIND = "assets.model-provider"
_SCHEMA = "schema/1"
_ACTION = "value"
_DEFINITION = {
    "environmentNamespace": _ENV,
    "definitionId": "harness.alpha",
    "revision": "7",
}


def _pin(*, provider_id=_PROVIDER_ID, contract_version=CONFIGURATION_PROVIDER_VERSION,
         implementation_digest=_PROVIDER_DIGEST, owner_activation=None):
    return ConfigurationProviderPin(
        provider_id,
        contract_version,
        implementation_digest,
        owner_activation or ActivationRef(_ENV, "extension.configuration-alpha", 3),
    )


def _route(*, kind=_KIND, schema=_SCHEMA, definitions=None, actions=(_ACTION,),
           claims=("model.selection",)):
    return ConfigurationRoute(
        kind,
        schema,
        tuple(definitions if definitions is not None else (_DEFINITION,)),
        tuple(actions),
        tuple(claims),
    )


def _descriptor(*, provider_id=_PROVIDER_ID, contract_version=CONFIGURATION_PROVIDER_VERSION,
                digest=_PROVIDER_DIGEST, routes=None, methods=None):
    return ConfigurationProviderDescriptor(
        provider_id,
        contract_version,
        digest,
        tuple(routes if routes is not None else (_route(),)),
        tuple(methods if methods is not None else CONFIGURATION_METHODS),
    )


def _resource(*, environment=_ENV, provider_id="resource.alpha", resource_id="model-config",
              revision="r3", contract_id="model.configuration@1"):
    return ResourceRef(environment, provider_id, contract_id, resource_id, revision)


def _reference(reference_id="model-source", *, resource=None, purpose="configure-model"):
    return ConfigurationReference(reference_id, resource or _resource(), purpose)


def _expected_declaration(*, declaration_id="model", kind=_KIND, schema=_SCHEMA,
                          action=_ACTION, digest=_DECLARATION_DIGEST, definition=None):
    return {
        "declarationId": declaration_id,
        "configurationKind": kind,
        "schemaVersion": schema,
        "action": action,
        "declarationDigest": digest,
        "definitionRef": dict(definition or _DEFINITION),
    }


def _extraction(*, declaration_id="model", kind=_KIND, schema=_SCHEMA,
                action=_ACTION, digest=_DECLARATION_DIGEST, definition=None,
                pin=None, coverage="complete", references=(), error_code=None):
    return ConfigurationReferenceExtraction(
        declaration_id,
        kind,
        schema,
        action,
        digest,
        dict(definition or _DEFINITION),
        pin or _pin(),
        coverage,
        tuple(references),
        error_code,
    )


def _validate(descriptor=None, extraction=None, *, pin=None, declaration=None):
    expected_pin = pin or _pin()
    expected = declaration or _expected_declaration()
    return validate_reference_extraction(
        descriptor or _descriptor(), extraction or _extraction(pin=expected_pin),
        expected_pin=expected_pin,
        expected_declaration=expected,
    )


def test_exact_route_pin_and_reference_extraction_round_trip_and_validate_to_snapshot():
    route = _route()
    descriptor = _descriptor()
    pin = _pin()
    resource = _resource()
    references = (
        _reference("model-source", resource=resource, purpose="configure-model"),
        _reference("credential-source", resource=_resource(resource_id="credential-ref"),
                   purpose="resolve-credential-reference"),
    )
    extraction = _extraction(pin=pin, references=references)

    assert ConfigurationRoute.from_dict(route.to_dict()) == route
    assert ConfigurationProviderDescriptor.from_dict(descriptor.to_dict()) == descriptor
    assert ConfigurationProviderPin.from_dict(pin.to_dict()) == pin
    assert ConfigurationReference.from_dict(references[0].to_dict()) == references[0]
    assert ConfigurationReferenceExtraction.from_dict(extraction.to_dict()) == extraction
    assert pin.provider_ref["environmentNamespace"] == _ENV
    assert pin.provider_ref["providerId"] == _PROVIDER_ID
    assert pin.provider_ref["generation"] == pin.owner_activation.generation

    snapshot = _validate(descriptor, extraction, pin=pin)
    assert snapshot == extraction
    assert snapshot is not extraction
    assert snapshot.provider_pin == pin and snapshot.provider_pin is not pin
    assert snapshot.references[0] == references[0]
    assert snapshot.references[0] is not references[0]


def test_complete_empty_references_means_no_dependencies_but_unknown_empty_does_not():
    descriptor, pin = _descriptor(), _pin()
    complete = _validate(descriptor, _extraction(pin=pin), pin=pin)
    unknown = _validate(
        descriptor,
        _extraction(pin=pin, coverage="unknown", error_code="REFERENCE_SCAN_INCOMPLETE"),
        pin=pin,
    )

    assert complete.coverage == "complete" and complete.references == ()
    assert complete.error_code is None
    assert unknown.coverage == "unknown" and unknown.references == ()
    assert unknown.error_code == "REFERENCE_SCAN_INCOMPLETE"
    assert ConfigurationReferenceExtraction.from_dict(unknown.to_dict()).coverage == "unknown"


def test_unknown_coverage_preserves_known_references_without_promoting_completeness():
    pin = _pin()
    known = _reference("known-material")
    result = _validate(
        _descriptor(),
        _extraction(pin=pin, coverage="unknown", references=(known,),
                    error_code="UNSUPPORTED_REFERENCE_KIND"),
        pin=pin,
    )
    assert result.coverage == "unknown"
    assert result.references == (known,)
    assert result.error_code == "UNSUPPORTED_REFERENCE_KIND"


def test_same_resource_may_have_distinct_purposes_only_with_distinct_reference_ids():
    pin = _pin()
    resource = _resource()
    references = (
        _reference("for-configuration", resource=resource, purpose="configure-model"),
        _reference("for-validation", resource=resource, purpose="validate-model-choice"),
    )
    result = _validate(_descriptor(), _extraction(pin=pin, references=references), pin=pin)
    assert tuple(item.resource_ref for item in result.references) == (resource, resource)
    assert tuple(item.purpose for item in result.references) == (
        "configure-model", "validate-model-choice"
    )


@pytest.mark.parametrize("wrong_pin", [
    _pin(provider_id="configuration.other"),
    _pin(implementation_digest="sha256:" + "c" * 64),
    _pin(owner_activation=ActivationRef(_ENV, "extension.configuration-alpha", 4)),
    _pin(owner_activation=ActivationRef("other-env", "extension.configuration-alpha", 3)),
])
def test_expected_provider_pin_mismatch_is_rejected_even_when_extraction_is_self_consistent(wrong_pin):
    with pytest.raises(ConfigurationContractError):
        _validate(_descriptor(), _extraction(pin=wrong_pin), pin=_pin())


@pytest.mark.parametrize("changed", [
    {"declarationId": "other-model"},
    {"configurationKind": "assets.other"},
    {"schemaVersion": "schema/2"},
    {"action": "reset"},
    {"declarationDigest": "c" * 64},
    {"definitionRef": {"environmentNamespace": _ENV, "definitionId": "harness.other", "revision": "7"}},
])
def test_expected_declaration_is_closed_and_compared_field_by_field(changed):
    declaration = _expected_declaration()
    declaration.update(changed)
    with pytest.raises(ConfigurationContractError):
        _validate(_descriptor(), _extraction(), declaration=declaration)


def test_expected_declaration_requires_exactly_the_six_frozen_fields():
    descriptor, extraction, pin = _descriptor(), _extraction(), _pin()
    expected = _expected_declaration()
    for malformed in (
        {key: value for key, value in expected.items() if key != "action"},
        {**expected, "unrequested": "extra"},
    ):
        with pytest.raises(ConfigurationContractError):
            validate_reference_extraction(
                descriptor, extraction, expected_pin=pin, expected_declaration=malformed
            )


def test_expected_pin_and_declaration_are_required_validator_inputs():
    with pytest.raises(TypeError):
        validate_reference_extraction(
            _descriptor(), _extraction(), expected_pin=_pin()
        )
    with pytest.raises(TypeError):
        validate_reference_extraction(
            _descriptor(), _extraction(), expected_declaration=_expected_declaration()
        )


@pytest.mark.parametrize("descriptor", [
    _descriptor(provider_id="configuration.other"),
    _descriptor(digest="sha256:" + "d" * 64),
    _descriptor(routes=(_route(kind="assets.other"),)),
    _descriptor(routes=(_route(schema="schema/2"),)),
    _descriptor(routes=(_route(actions=("reset",)),)),
    _descriptor(routes=(_route(definitions=({
        "environmentNamespace": _ENV, "definitionId": "harness.other", "revision": "7"
    },)),)),
])
def test_descriptor_must_exactly_admit_the_extraction_provider_and_route(descriptor):
    with pytest.raises(ConfigurationContractError):
        _validate(descriptor, _extraction())


def test_extraction_constructor_rejects_duplicate_reference_ids_but_allows_distinct_uses():
    resource = _resource()
    with pytest.raises(ConfigurationContractError):
        _extraction(references=(
            _reference("duplicate", resource=resource, purpose="read"),
            _reference("duplicate", resource=resource, purpose="configure"),
        ))


@pytest.mark.parametrize("bad_coverage,error_code", [
    ("unknown", None),
    ("complete", "REFERENCE_SCAN_INCOMPLETE"),
    ("partial", "REFERENCE_SCAN_INCOMPLETE"),
    ("unknown", "bad-code"),
])
def test_coverage_and_stable_error_code_are_closed(bad_coverage, error_code):
    with pytest.raises(ConfigurationContractError):
        _extraction(coverage=bad_coverage, error_code=error_code)


@pytest.mark.parametrize("bad_coverage", [None, 3, [], {}])
def test_non_string_coverage_values_raise_the_typed_contract_error(bad_coverage):
    with pytest.raises(ConfigurationContractError):
        _extraction(coverage=bad_coverage, error_code="REFERENCE_SCAN_INCOMPLETE")


def test_route_descriptor_and_reference_reject_duplicates_and_unknown_methods():
    route = _route()
    with pytest.raises(ConfigurationContractError):
        _descriptor(routes=(route, route))
    with pytest.raises(ConfigurationContractError):
        _route(definitions=(_DEFINITION, _DEFINITION))
    with pytest.raises(ConfigurationContractError):
        _route(actions=("value", "value"))
    with pytest.raises(ConfigurationContractError):
        _route(claims=("model.selection", "model.selection"))
    with pytest.raises(ConfigurationContractError):
        _descriptor(methods=("describe", "invented_method"))
    with pytest.raises(ConfigurationContractError):
        _descriptor(methods=("describe", "describe"))


@pytest.mark.parametrize("bad_value", [
    "latest", "*", "schema/*", "../schema/1", "/absolute/schema/1",
])
def test_route_rejects_floating_or_path_like_schema_versions(bad_value):
    with pytest.raises(ConfigurationContractError):
        _route(schema=bad_value)


@pytest.mark.parametrize("resource_environment,purpose", [
    ("other-env", "configure-model"),
    (_ENV, ""),
])
def test_extraction_rejects_cross_environment_reference_or_missing_purpose(
    resource_environment, purpose
):
    with pytest.raises(ConfigurationContractError):
        reference = _reference(resource=_resource(environment=resource_environment), purpose=purpose)
        _extraction(references=(reference,))


def test_from_dict_rejects_extra_or_missing_fields_without_coercing_unknown_data():
    descriptor = _descriptor().to_dict()
    descriptor["callable"] = "would-be-effect"
    with pytest.raises(ConfigurationContractError):
        ConfigurationProviderDescriptor.from_dict(descriptor)

    extraction = _extraction().to_dict()
    extraction.pop("providerPin", None)
    with pytest.raises(ConfigurationContractError):
        ConfigurationReferenceExtraction.from_dict(extraction)

    pin = _pin().to_dict()
    pin["generation"] = pin["generation"] + 1
    with pytest.raises(ConfigurationContractError):
        ConfigurationProviderPin.from_dict(pin)


def test_provider_version_and_digest_have_exact_safe_encodings():
    with pytest.raises(ConfigurationContractError):
        ConfigurationProviderPin(
            _PROVIDER_ID,
            "agent-configuration-provider/2",
            _PROVIDER_DIGEST,
            ActivationRef(_ENV, "extension.configuration-alpha", 3),
        )
    with pytest.raises(ConfigurationContractError):
        _descriptor(contract_version="agent-configuration-provider/2")
    with pytest.raises(ConfigurationContractError):
        _descriptor(digest="A" * 64)
    with pytest.raises(ConfigurationContractError):
        _descriptor(digest="a" * 64)


def test_public_provider_contract_error_alias_preserves_existing_configuration_error():
    assert ConfigurationProviderContractError is ConfigurationContractError
    assert LegacyPublicConfigurationContractError is LegacyConfigurationContractError
    assert LegacyPublicConfigurationContractError is not ConfigurationProviderContractError


def test_nested_input_and_output_aliases_cannot_mutate_frozen_route_or_extraction():
    definitions = [dict(_DEFINITION)]
    claims = ["model.selection"]
    route = _route(definitions=definitions, claims=claims)
    definitions[0]["revision"] = "changed"
    claims[0] = "changed.claim"
    assert route.definition_refs[0]["revision"] == "7"
    assert route.field_claims == ("model.selection",)

    descriptor = _descriptor(routes=(route,))
    exposed_route = descriptor.to_dict()["routes"][0]
    exposed_route["definitionRefs"][0]["revision"] = "output-mutation"
    assert descriptor.routes[0].definition_refs[0]["revision"] == "7"

    extraction = _extraction(references=(_reference(),))
    exposed = extraction.to_dict()
    exposed["references"][0]["resourceRef"]["resourceId"] = "output-mutation"
    assert extraction.references[0].resource_ref.resource_id == "model-config"


def test_expected_pin_rejects_a_different_caller_claimed_owner_generation():
    # A syntactically valid caller-created pin is not Registry admission,
    # authorization, or proof that a provider was invoked. The pure validator
    # only compares it with the independently fixed expected identity.
    caller_pin = _pin(owner_activation=ActivationRef(_ENV, "caller.claimed-owner", 99))
    extraction = _extraction(pin=caller_pin)
    with pytest.raises(ConfigurationContractError):
        _validate(_descriptor(), extraction, pin=_pin())


def test_schema_metadata_methods_are_data_only_and_validator_has_no_provider_to_call():
    descriptor = _descriptor(methods=("describe", "extract_references"))
    assert descriptor.supported_methods == ("describe", "extract_references")
    assert not any(callable(value) for value in descriptor.to_dict().values())
    assert _validate(descriptor, _extraction()) == _extraction()


def test_collection_bounds_reject_one_over_each_documented_limit():
    too_many_definitions = tuple({
        "environmentNamespace": _ENV,
        "definitionId": f"harness.{index}",
        "revision": "7",
    } for index in range(65))
    with pytest.raises(ConfigurationContractError):
        _route(definitions=too_many_definitions)

    with pytest.raises(ConfigurationContractError):
        _route(claims=tuple(f"field.{index}" for index in range(257)))

    too_many_routes = tuple(
        _route(kind=f"assets.kind-{index}") for index in range(65)
    )
    with pytest.raises(ConfigurationContractError):
        _descriptor(routes=too_many_routes)

    too_many_references = tuple(
        _reference(f"reference.{index}") for index in range(257)
    )
    with pytest.raises(ConfigurationContractError):
        _extraction(references=too_many_references)

    with pytest.raises(ConfigurationContractError):
        _reference(purpose="p" * 257)


def test_overridden_serializers_are_rejected_without_executing_them():
    descriptor_calls = []
    resource_calls = []

    class AdversarialDescriptor(ConfigurationProviderDescriptor):
        def to_dict(self):
            descriptor_calls.append("called")
            raise AssertionError("overridden descriptor serializer must not run")

    class AdversarialResourceRef(ResourceRef):
        def to_dict(self):
            resource_calls.append("called")
            raise AssertionError("overridden resource serializer must not run")

    ordinary = _descriptor()
    adversarial_descriptor = AdversarialDescriptor(
        ordinary.provider_id,
        ordinary.contract_version,
        ordinary.implementation_digest,
        ordinary.routes,
        ordinary.supported_methods,
    )
    with pytest.raises(ConfigurationContractError):
        _validate(adversarial_descriptor, _extraction())
    assert descriptor_calls == []

    ordinary_resource = _resource()
    adversarial_resource = AdversarialResourceRef(
        ordinary_resource.environment_namespace,
        ordinary_resource.provider_id,
        ordinary_resource.contract_id,
        ordinary_resource.resource_id,
        ordinary_resource.revision,
    )
    with pytest.raises(ConfigurationContractError):
        ConfigurationReference("adversarial", adversarial_resource, "configure-model")
    assert resource_calls == []


def test_missing_provider_is_not_converted_to_a_complete_empty_extraction():
    with pytest.raises(ConfigurationContractError):
        validate_reference_extraction(
            None,
            _extraction(),
            expected_pin=_pin(),
            expected_declaration=_expected_declaration(),
        )

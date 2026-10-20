"""Resolve one immutable Profile revision against the live Harness catalog."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from ordessa_units.errors import UnitAdmissionRefused, UnitGuaranteeUnavailable
from ordessa_units.bindings.harness_admission import read_harness_definition
from ordessa_infrastructure.encoding.immutable_json import sealed_mapping
from ordessa_execution_agents.profiles import (
    Profile,
    ProfileRevision,
    ProfileRevisionRef,
    ProfileService,
    ProfileValidationError,
    encode_content,
    encode_revision,
    encode_revision_ref,
)
from ordessa_execution_agents.harness.definitions.runtime_providers import RUNTIME_PROVIDER_VERSION
from ordessa_execution_agents.harness.providers.registry import (
    AdmittedHarnessDefinition,
    HarnessCatalog,
    HarnessDefinitionDescriptor,
)


@dataclass(frozen=True)
class UnitProfileResolution:
    """The exact immutable Profile and the catalog's admitted provider pin."""

    profile_snapshot: Mapping[str, object]
    harness_provider_ref: Mapping[str, object]
    harness_descriptor: HarnessDefinitionDescriptor


def resolve_unit_profile(
    profile_service: ProfileService,
    revision_ref: ProfileRevisionRef,
    harness_catalog: HarnessCatalog,
) -> UnitProfileResolution:
    """Resolve an explicit stored revision and its currently admitted Harness.

    The current Profile record is consulted only to reject missing or archived
    Profiles. The selected revision is always loaded independently from the
    original Profile store; it is never replaced by ``current_revision``.
    Provider identity comes only from ``HarnessCatalog.describe``.
    """
    if type(profile_service) is not ProfileService:
        raise ProfileValidationError("original ProfileService required")
    if type(revision_ref) is not ProfileRevisionRef:
        raise ProfileValidationError("fixed Profile revision reference required")
    if type(harness_catalog) is not HarnessCatalog:
        raise UnitGuaranteeUnavailable("original HarnessCatalog required")

    namespace = profile_service.environment_namespace
    if revision_ref.environment_namespace != namespace:
        raise ProfileValidationError("Profile revision belongs to another environment")

    current = profile_service.get(revision_ref.profile_id)
    if (type(current) is not Profile
            or current.profile_id != revision_ref.profile_id
            or current.current_revision.profile_id != current.profile_id
            or current.current_revision.environment_namespace != namespace):
        raise UnitGuaranteeUnavailable("current Profile identity is inconsistent")
    if current.archived_at is not None:
        raise UnitAdmissionRefused("archived Profile cannot be selected for a new Unit")

    revision = profile_service.get_revision(revision_ref)
    if (type(revision) is not ProfileRevision
            or type(revision.ref) is not ProfileRevisionRef
            or revision.ref != revision_ref
            or revision.ref.environment_namespace != namespace
            or revision.ref.profile_id != current.profile_id):
        raise UnitGuaranteeUnavailable("stored Profile revision identity is inconsistent")
    # Reuse the canonical codec as the single content/digest validation path.
    encoded = encode_revision(revision)
    if encoded["ref"] != encode_revision_ref(revision_ref):
        raise UnitGuaranteeUnavailable("stored Profile revision reference changed")
    if encoded["content"] != encode_content(revision.content):
        raise UnitGuaranteeUnavailable("stored Profile revision content changed")

    definition_ref = revision.content.harness_definition_ref
    if (not isinstance(definition_ref, Mapping)
            or definition_ref.get("environmentNamespace") != namespace):
        raise ProfileValidationError("Profile Harness definition belongs to another environment")

    admitted = read_harness_definition(harness_catalog, definition_ref)
    if (type(admitted) is not AdmittedHarnessDefinition
            or type(admitted.descriptor) is not HarnessDefinitionDescriptor
            or admitted.descriptor.definition_ref != definition_ref
            or admitted.descriptor.definition_ref.get("environmentNamespace") != namespace):
        raise UnitAdmissionRefused("exact active Profile Harness definition unavailable")

    provider_ref = admitted.provider_ref
    owner_ref = provider_ref.get("ownerActivationRef") if isinstance(provider_ref, Mapping) else None
    activation = admitted.owner_activation
    if (not isinstance(provider_ref, Mapping)
            or set(provider_ref) != {
                "environmentNamespace", "providerId", "ownerActivationRef", "generation",
                "contractVersion", "implementationDigest",
            }
            or provider_ref.get("environmentNamespace") != namespace
            or provider_ref.get("providerId") != admitted.descriptor.provider_id
            or provider_ref.get("generation") != activation.generation
            or provider_ref.get("contractVersion") != RUNTIME_PROVIDER_VERSION
            or provider_ref.get("implementationDigest") != admitted.descriptor.implementation_digest
            or not isinstance(owner_ref, Mapping)
            or dict(owner_ref) != {
                "environmentNamespace": namespace,
                "pluginId": activation.plugin_id,
                "generation": activation.generation,
            }):
        raise UnitAdmissionRefused("Harness catalog returned an inconsistent admitted provider pin")

    snapshot = sealed_mapping({
        "ref": encode_revision_ref(revision.ref),
        "manifest": encode_content(revision.content),
    })
    return UnitProfileResolution(
        profile_snapshot=snapshot,
        harness_provider_ref=provider_ref,
        harness_descriptor=admitted.descriptor,
    )


__all__ = ["UnitProfileResolution", "resolve_unit_profile"]

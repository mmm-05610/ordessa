"""Interpret the Harness catalog's read refusals at the Unit boundary."""
from ordessa_execution_agents.harness.providers.registry.errors import (
    CatalogAdmissionRefused, CatalogIdentityConflict, CatalogUnavailable,
)
from ordessa_units.errors import (
    UnitAdmissionRefused, UnitGuaranteeUnavailable, UnitIdentityMismatch,
)


def read_harness_definition(catalog, definition_ref, *, cleanup_provider_ref=None):
    try:
        if cleanup_provider_ref is not None:
            return catalog.describe_for_cleanup(definition_ref, cleanup_provider_ref)
        return catalog.describe(definition_ref)
    except CatalogIdentityConflict as error:
        raise UnitIdentityMismatch(str(error)) from error
    except CatalogAdmissionRefused as error:
        raise UnitAdmissionRefused(str(error)) from error
    except CatalogUnavailable as error:
        raise UnitGuaranteeUnavailable(str(error)) from error

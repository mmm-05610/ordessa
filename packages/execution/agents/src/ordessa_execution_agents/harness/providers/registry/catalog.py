"""Read-only public projections of the Environment's admitted providers.

No discovery cache, native probing or invocation capability is created here.
Harness descriptors expose declared metadata, not installation or readiness
evidence.

This module is a neutral admission projection only. The upper-layer Agent
configuration offer/proposal aggregation lives with the unit-configuration owner
(``ordessa_units.configuration.offers``); it is not re-imported
here, so this registry has no dependency on units or profiles.
"""
import json
from collections.abc import Mapping

from .errors import CatalogAdmissionRefused, CatalogIdentityConflict, CatalogUnavailable
from ordessa_execution_agents.harness.definitions.errors import CoreDTOError
from ordessa_infrastructure.encoding.immutable_json import safe_json


class AgentProviders:
    def __init__(self, environment):
        self._environment = environment

    @staticmethod
    def _view(admitted):
        return {"descriptor": admitted.descriptor.to_dict(),
                "providerRef": json.loads(safe_json(admitted.provider_ref))}

    def _harness_admission(self):
        # Keep this import and owner-binding check lazy: configuration-only
        # consumers do not acquire a dependency on Harness registration.
        from .definition_admission import HarnessAdmission
        return HarnessAdmission(self._environment)

    def list(self):
        try:
            return tuple(self._view(item) for item in self._harness_admission().list())
        except CoreDTOError as error:
            raise CatalogAdmissionRefused("Harness declaration changed after admission") from error

    def describe(self, definition_ref):
        if (not isinstance(definition_ref, Mapping)
                or set(definition_ref) != {"environmentNamespace", "definitionId", "revision"}
                or any(not isinstance(value, str) or not value for value in definition_ref.values())):
            raise CatalogIdentityConflict("complete Harness definition reference required")
        try:
            return self._view(self._harness_admission().describe(definition_ref))
        except CoreDTOError as error:
            raise CatalogAdmissionRefused("Harness declaration changed after admission") from error

    def configuration_list(self):
        raise CatalogUnavailable("specific configuration definition owner is not bound")

    def configuration_describe(self, definition_ref):
        if (not isinstance(definition_ref, Mapping)
                or set(definition_ref) != {"environmentNamespace", "definitionId", "revision"}
                or any(not isinstance(value, str) or not value for value in definition_ref.values())):
            raise CatalogIdentityConflict("complete configuration definition reference required")
        raise CatalogUnavailable("specific configuration definition owner is not bound")

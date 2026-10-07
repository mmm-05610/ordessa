"""Read-only public projections of the Environment's admitted providers.

No discovery cache, native probing or invocation capability is created here.
Supported methods are declarations, not installation or readiness evidence.
"""
import json
from collections.abc import Mapping

from ordessa_environment_api import IdentityMismatchError
from ordessa_environment_api.operations import safe_json


class AgentProviders:
    def __init__(self, environment):
        self._environment = environment

    @staticmethod
    def _view(admitted):
        return {"descriptor": admitted.descriptor.to_dict(),
                "providerRef": json.loads(safe_json(admitted.provider_ref))}

    @staticmethod
    def _configuration_view(admitted):
        """Thin projection of admitted configuration metadata (freeze §3).

        Data only: descriptor dict, sealed runtime provider ref and the
        §2-verified recognized definition subset. No callable, no instance.
        """
        return {"descriptor": admitted.descriptor.to_dict(),
                "providerRef": json.loads(safe_json(admitted.runtime_provider_ref)),
                "recognizedDefinitions": [json.loads(safe_json(item))
                                          for item in admitted.recognized_definitions]}

    def list(self):
        return tuple(self._view(item) for item in
                     self._environment.agent_runtime_contributions())

    def describe(self, definition_ref):
        if (not isinstance(definition_ref, Mapping)
                or set(definition_ref) != {"environmentNamespace", "definitionId", "revision"}
                or any(not isinstance(value, str) or not value for value in definition_ref.values())):
            raise IdentityMismatchError("complete RuntimeProvider definition reference required")
        return self._view(self._environment.agent_runtime_contribution(definition_ref))

    def configuration_list(self):
        return tuple(self._configuration_view(item) for item in
                     self._environment.agent_configuration_contributions())

    def configuration_describe(self, definition_ref):
        if (not isinstance(definition_ref, Mapping)
                or set(definition_ref) != {"environmentNamespace", "definitionId", "revision"}
                or any(not isinstance(value, str) or not value for value in definition_ref.values())):
            raise IdentityMismatchError("complete configuration definition reference required")
        return self._configuration_view(
            self._environment.agent_configuration_contribution(definition_ref))

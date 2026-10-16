"""Immutable ACP observations and closed native query errors; no process effects."""
from __future__ import annotations
from dataclasses import dataclass
import json


@dataclass(frozen=True)
class NativeSessionObservation:
    """A live Agent response correlated to this channel's session/new request.

    This is not a runtime generation or a configuration confirmation.
    """

    connection_id: str
    execution_id: str
    ledger_session_id: str
    native_session_id: str


class NativeConfigurationUnavailable(RuntimeError):
    """No independent live configuration evidence; never an applied receipt."""


class NativeConfigurationRefused(NativeConfigurationUnavailable):
    """The native answered this owner query with a JSON-RPC error object.

    Distinct only for callers that ask for the distinction; every existing
    consumer keeps catching the base class. Carries the reply's numeric code,
    never its message text.
    """

    def __init__(self, error_code):
        super().__init__('native configuration query refused by the native side')
        self.error_code = error_code


@dataclass(frozen=True)
class NativeConfigurationObservation:
    owner: NativeSessionObservation
    native_generation: str
    busy: bool
    config_options_json: str

    @property
    def config_options(self) -> list:
        # Keep the observation immutable even if a consumer edits its DTO.
        return json.loads(self.config_options_json)


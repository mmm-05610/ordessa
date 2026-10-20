"""Queue validation/read observations with explicit missing Agent apply binding.

The old C4 product plan/apply/journal execution chain is retired. A queued ACP
session target cannot self-authorize as an AgentInstanceRef; submission refuses
until a trusted queue-to-Agent binding and asynchronous dispatch port are bound.
The SDK already supports recorded apply/query; this synchronous legacy queue
port cannot infer that binding from an ACP routing target.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from ordessa_server.composition.native_channels.registry import NativeConfigurationUnavailable
from ordessa_model_provider.turn_application import (
    SUBMIT_READY, SUBMIT_REFUSED, SUBMIT_UNKNOWN, SubmitResult,
)

FACET_ID = "assets.model-provider"
ITEM_ID = "choice"
SCHEMA_VERSION = "1"

#: The plugin-side reason vocabulary this port may answer with (the codes the
#: choice surface already publishes wire families for).
ADAPTER_MISSING = "ADAPTER_MISSING"
TARGET_STALE = "TARGET_STALE"


class _SubmissionRefused(Exception):
    """A typed, zero-prompt refusal: the intent stays, an explicit retry may
    use a new operation key (FR-06)."""


class _SubmissionUnknown(Exception):
    """An undecided outcome: zero prompt and the session blocks until an
    observation settles it (FR-06)."""


class ProductTurnApplication:
    """The one real application of an unbound session's frozen model intent."""

    def __init__(self, *, authority_of: Callable[[], Any],
                 catalog_of: Callable[[], Any]) -> None:
        self._authority_of = authority_of
        self._catalog_of = catalog_of

    # -- TurnApplicationPort ---------------------------------------------------

    def submit(self, target: Mapping[str, Any], *, operation_key: str,
               expected_sequence: int | None,
               intent: Mapping[str, Any]) -> SubmitResult:
        try:
            return self._submit(target, operation_key=operation_key,
                                expected_sequence=expected_sequence, intent=intent)
        except _SubmissionRefused as refused:
            return SubmitResult(outcome=SUBMIT_REFUSED, reason=str(refused),
                                sequence=expected_sequence)
        except _SubmissionUnknown as unknown:
            return SubmitResult(outcome=SUBMIT_UNKNOWN, reason=str(unknown),
                                sequence=expected_sequence)
        except NativeConfigurationUnavailable as error:
            # An inactive/replaced authority (C02) or a dead native owner is a
            # typed refusal: nothing was applied, the intent stays, a retry
            # after the client re-observes the session may use a new key.
            return SubmitResult(outcome=SUBMIT_REFUSED, reason=f"{TARGET_STALE}: {error}",
                                sequence=expected_sequence)

    def _submit(self, target, *, operation_key, expected_sequence, intent) -> SubmitResult:
        if self._authority_of() is None:
            return SubmitResult(outcome=SUBMIT_REFUSED,reason=ADAPTER_MISSING,sequence=expected_sequence)
        raise _SubmissionRefused(
            'APPLICATION_PORT_ABSENT: queued ACP target has no authenticated AgentInstanceRef '
            'and no trusted asynchronous queue-to-Agent dispatch binding is installed')

    def routing_identity(self, target: Mapping[str, Any]) -> Mapping[str, Any] | None:
        """The currently observed binding identity, or None when unobserved.

        Read-only: this observation never registers a binding and never rounds
        a native trip; the submit path re-observes freshly and the plugin's own
        fence refuses an application that landed on another channel/owner/
        generation than this admission identity (M09/C02).
        """
        try:
            authority = self._authority_of()
            if authority is None:
                return None
            binding = authority.observed_native(
                harness_id=str(target.get("harnessId") or ""),
                native_session_id=str(target.get("acpSessionId") or ""))
        except NativeConfigurationUnavailable:
            return None
        except Exception:  # noqa: BLE001 - an unobserved identity is never a guess
            return None
        if binding is None:
            return None
        return {"owner": self._owner_identity(binding.snapshot.owner),
                "canonicalUid": binding.uid,
                "generation": int(binding.snapshot.target.runtime_generation)}

    # -- internals --------------------------------------------------------------

    @staticmethod
    def _owner_identity(owner: Any) -> str:
        """The backend-observed owner identity of one live native session.

        The observation is minted by the channel that saw the correlated
        session/new reply; connection + native session id name it exactly.
        """
        return f"{owner.connection_id}:{owner.native_session_id}"


class NativeModelEligibilityPort:
    """Queue-time structural verdict and read-only observation over the
    neutral authority. It never applies: the one real application entry is
    :class:`ProductTurnApplication` (appendix §3.3 - a second apply chain must
    not exist), so ``apply`` refuses typed and the legacy R1 pipeline that
    would call it has no production consumer (appendix §6b.3)."""

    def __init__(self, *, authority_of: Callable[[], Any]) -> None:
        self._authority_of = authority_of

    def eligibility(self, harness_id: str, config_ref: Mapping[str, Any],
                    session_ref: Mapping[str, Any]) -> str:
        from ordessa_model_provider.ports import (
            ELIGIBILITY_READY, ELIGIBILITY_UNKNOWN, ELIGIBILITY_UNSUPPORTED,
        )
        try:
            authority = self._authority_of()
            if authority is None:
                return ELIGIBILITY_UNKNOWN
            # Structural facts first: a verified installation route and the
            # one published model adapter for this harness.
            installation = authority.services.verify(harness_id)
            from ordessa_server.composition.configuration.model.bindings import model_descriptor
            adapter_id = model_descriptor(harness_id).adapter_id
            views = [view for view in authority.services.carrier.contributions(
                "harness.configuration-adapters")
                if adapter_id is not None
                and getattr(getattr(view, "payload", None), "descriptor", None) is not None
                and view.payload.descriptor.adapter_id == adapter_id]
            if len(views) != 1:
                return ELIGIBILITY_UNKNOWN
            if installation.harness_id != harness_id:
                return ELIGIBILITY_UNSUPPORTED
            # The live native owner: a canonically bound session or, before
            # the first application, the backend's own live observation of
            # the native session (a queue-time existence check that mints
            # nothing). Neither present -> there is no next turn to apply to
            # (an absence, never a guess).
            if authority.observed_native(
                    harness_id=harness_id,
                    native_session_id=str(session_ref.get("acpSessionId") or "")) is None \
                    and not authority.has_live_native(
                        harness_id=harness_id,
                        native_session_id=str(session_ref.get("acpSessionId") or "")):
                return ELIGIBILITY_UNKNOWN
            return ELIGIBILITY_READY
        except NativeConfigurationUnavailable:
            return ELIGIBILITY_UNKNOWN
        except Exception:  # noqa: BLE001 - an unverifiable verdict is never ready
            return ELIGIBILITY_UNKNOWN

    def read_back(self, session_ref: Mapping[str, Any]) -> Mapping[str, Any]:
        """A fresh native observation of the session's current model.

        The value is the native's own answer (its configuration report), read
        through the authority; the catalog identity projection uses the same
        observed option metadata the adapters compile against. A missing or
        ambiguous observation is an unknown outcome, never a synthesized one,
        and an unregistered session is an absence - a read never registers.
        """
        from ordessa_model_provider.ports import SESSION_CONFIG_OUTCOME_UNKNOWN, SessionConfigError
        try:
            authority = self._authority_of()
            if authority is None:
                raise SessionConfigError(SESSION_CONFIG_OUTCOME_UNKNOWN, ADAPTER_MISSING)
            binding = authority.observed_native(
                harness_id=str(session_ref.get("harnessId") or ""),
                native_session_id=str(session_ref.get("acpSessionId") or ""))
            if binding is None:
                raise SessionConfigError(SESSION_CONFIG_OUTCOME_UNKNOWN,
                                         f"{TARGET_STALE}: no live native session owner")
            snapshot = authority.resolve(binding.snapshot.target)
        except SessionConfigError:
            raise
        except NativeConfigurationUnavailable as error:
            raise SessionConfigError(SESSION_CONFIG_OUTCOME_UNKNOWN,
                                     f"{TARGET_STALE}: {error}") from error
        except Exception as error:  # noqa: BLE001
            raise SessionConfigError(SESSION_CONFIG_OUTCOME_UNKNOWN,
                                     f"{type(error).__name__}: {error}") from error
        return self._model_observation(snapshot.config_options)

    @staticmethod
    def _model_observation(config_options):
        from ordessa_model_provider.ports import SESSION_CONFIG_OUTCOME_UNKNOWN, SessionConfigError
        selectors = [item for item in config_options if item.get("id") == "model"]
        if len(selectors) != 1 or not isinstance(selectors[0].get("currentValue"), str):
            raise SessionConfigError(SESSION_CONFIG_OUTCOME_UNKNOWN,
                                     "native model observation unavailable")
        current = selectors[0]["currentValue"]

        def flatten(options, depth=0):
            for option in options:
                if not isinstance(option, dict):
                    continue
                if "value" in option:
                    yield option
                if isinstance(option.get("options"), list):
                    yield from flatten(option["options"], depth + 1)

        matches = [option for option in flatten(selectors[0].get("options", []))
                   if option.get("value") == current]
        facts = None
        if len(matches) == 1:
            metadata = matches[0].get("_meta")
            candidate = metadata.get("ordessaModel") if isinstance(metadata, dict) else None
            if isinstance(candidate, dict) and isinstance(candidate.get("model"), str):
                facts = candidate
        # The catalog identity when the native's own option metadata names it;
        # otherwise the raw observed value - both are real observations.
        return {"model": facts["model"] if facts else current,
                "provider": facts.get("provider") if facts else None,
                "nativeValue": current}

    def describe(self, harness_id: str):
        return None

    def apply(self, session_ref, choice):
        from ordessa_model_provider.ports import (
            SESSION_CONFIG_UNSUPPORTED, SessionConfigError,
        )
        raise SessionConfigError(
            SESSION_CONFIG_UNSUPPORTED,
            "queued model intent requires the trusted Agent binding and asynchronous "
            "recorded-native dispatch port; this eligibility port is read-only")

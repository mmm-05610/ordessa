"""The product's one real next-turn application seam (021 appendix §3.3).

Three composition-injected collaborators live here; none of them applies
anything on its own and none of them synthesizes a read-back:

- :class:`ProductTurnApplication` - the ``TurnApplicationPort`` (plus its
  optional :class:`~ordessa_model_provider.turn_application.RoutingIdentityPort`
  view) behind ``modelProvider.beginTurnApplication``. It resolves the exact
  native session through the neutral authority's backend binding facts
  (``ensure_native``), resolves the single ``("assets.model-provider",
  "choice")`` item through the domain's own public resolver
  (``ordessa_model_provider.profile_resolution``), and executes ONE owner-plan
  application through the shared C4 entry (``plan``/``apply_prepared``) with
  its journal, fences and fresh ``runtime.observe`` verification. The read
  back that gates ``ready`` is the shared C4 one: the service refuses to
  confirm unless the native adapter's own verification matched the observed
  native state, so a ``ready`` answer always cites a real read-back reference
  and never the request's own model id (B.2/M13).
- :class:`NativeModelEligibilityPort` - the queue-time structural verdict and
  the read-only reconcile observation (``read_back``), both over live native
  configuration observations. It deliberately implements no ``apply``: the
  only real application entry is the submit gate above, so the legacy
  ``resolve_next_turn`` pipeline (appendix §6b.3: no production consumer)
  conservatively refuses instead of reaching a second apply chain.
- :class:`ProfileTurnIntentSink` - the bound-mode bridge of appendix §3.1:
  when the target native session is a registered Profile session, a model
  choice is written into that session's overlay (facet
  ``assets.model-provider``, item ``choice``, source marked ``model-provider``,
  T02-A action_seq/revision semantics) and the sink takes the intent
  authority; otherwise it declines and the model-provider queue stays the
  authority. Bound is a backend registration fact, never a UI session id.
"""
from __future__ import annotations

from typing import Any, Callable, Mapping

from ordessa_harness_api import Confirmed, DesiredFragment, Plan, Refused, Unknown
from ordessa_harness.server_acp.registry import NativeConfigurationUnavailable
from ordessa_model_provider.turn_application import (
    SUBMIT_READY, SUBMIT_REFUSED, SUBMIT_UNKNOWN, SubmitResult,
    TurnIntentHandoverError,
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
        authority = self._authority_of()
        if authority is None:
            return SubmitResult(outcome=SUBMIT_REFUSED, reason=ADAPTER_MISSING,
                                sequence=expected_sequence)
        choice = dict(intent.get("choice") or {})
        harness_id = str(target.get("harnessId") or "")
        # the frozen queue choice is {providerConfigId, modelId, version}; the
        # resolver's atomic identity is exactly {harnessId, providerConfigId,
        # modelId} - the harness comes from the native target, never from the
        # client's projection.
        atomic = {"harnessId": harness_id,
                  "providerConfigId": str(choice.get("providerConfigId") or ""),
                  "modelId": str(choice.get("modelId") or "")}
        payload, _revisions = self._resolve_choice(atomic, harness_id)
        binding = authority.ensure_native(
            harness_id=harness_id,
            native_session_id=str(target.get("acpSessionId") or ""))
        if binding is None:
            raise _SubmissionRefused(f"{TARGET_STALE}: no live native session owner")
        snapshot = binding.snapshot
        service, native = authority.create_service(
            snapshot.target, credential_binding=self._credential_binding_of(payload, harness_id))
        expected_revision = self._before_revision(native, snapshot.target)
        plan = self._plan(service, snapshot.target, payload, expected_revision)
        outcome = self._apply_prepared(service, plan, operation_key)
        if isinstance(outcome, Refused):
            raise _SubmissionRefused(
                f"{outcome.code.value}: {'; '.join(outcome.diagnostics)}")
        if isinstance(outcome, Unknown):
            raise _SubmissionUnknown(
                f"native application outcome is undecided: {outcome.phase}: "
                + ", ".join(outcome.pending_checks))
        # ``ready`` is only reachable because the shared C4 entry verified a
        # fresh native read-back (its adapter Match over runtime.observe) and
        # journalled the operation; every field below cites that real record.
        return SubmitResult(
            outcome=SUBMIT_READY, sequence=expected_sequence,
            application={
                "operationId": outcome.operation_id,
                "nativeTarget": {
                    "owner": self._owner_identity(snapshot.owner),
                    "canonicalUid": binding.uid,
                    "generation": int(outcome.runtime_generation),
                },
                "appliedRevision": outcome.applied_revision,
                "evidenceRef": outcome.verification_evidence_ref,
            })

    # -- RoutingIdentityPort ---------------------------------------------------

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

    def _resolve_choice(self, choice: Mapping[str, Any], harness_id: str):
        """Resolve the atomic choice through the domain's public resolver.

        This is preparation with payload/revision separation; the admission
        boundary (the C4 plan/apply below) re-validates the catalogue and
        credential revisions again before any effect (M10 semantics reuse).
        """
        from ordessa_harness.configuration.model.bridge import choice_payload_schema
        from ordessa_model_provider.profile_resolution import ProfileModelChoiceResolver

        catalog = self._catalog_of()
        if catalog is None:
            raise _SubmissionRefused(ADAPTER_MISSING)
        resolver = ProfileModelChoiceResolver(catalog, payload_schema=choice_payload_schema())
        try:
            resolved = resolver.resolve(choice, harness_id=harness_id)
        except Exception as error:  # noqa: BLE001 - typed refusal, never a crash path
            raise _SubmissionRefused(f"model choice cannot be resolved: {error}") from error
        return resolved.payload, resolved.revisions

    def _credential_binding_of(self, payload: Mapping[str, Any], harness_id: str):
        """The native credential binding, only when the payload declares one.

        An anonymous model choice needs no binding route (the adapters skip
        the check); a declared credential ref must resolve through the
        catalogue's trusted in-memory application path against the retained
        native route, or the choice refuses. A managed-account route has no
        unbound production binding yet and refuses honestly instead of
        pretending support.
        """
        if payload.get("credentialRef") is None and payload.get("authentication") is None:
            return None

        def bind(snapshot, desired):
            catalog = self._catalog_of()
            if catalog is None:
                return False
            credential = catalog.application_credential(
                desired.get("credentialRef"), harness_id=harness_id)
            return self._authority_of().services.restoration.credential_binding(
                snapshot, desired, credential=credential) is True

        return bind

    def _before_revision(self, native: Any, target) -> str:
        try:
            return native.capture(target).before_revision
        except NativeConfigurationUnavailable:
            raise
        except Exception as error:  # noqa: BLE001 - no capture, no plan
            raise _SubmissionRefused(f"{TARGET_STALE}: {error}") from error

    def _plan(self, service, target, payload, expected_revision) -> Plan:
        source = f"model-provider@{payload.get('model')}"
        fragment = DesiredFragment(
            facet_id=FACET_ID, item_id=ITEM_ID, schema_version=SCHEMA_VERSION,
            business_ref=f"{FACET_ID}.{ITEM_ID}", source_revision=source,
            operation="set", value=dict(payload))
        try:
            planned = service.plan(target, (fragment,), expected_revision)
        except NativeConfigurationUnavailable:
            raise
        except Exception as error:  # noqa: BLE001
            raise _SubmissionRefused(f"native plan refused: {error}") from error
        if isinstance(planned, Refused):
            raise _SubmissionRefused(
                f"{planned.code.value}: {'; '.join(planned.diagnostics)}")
        if not isinstance(planned, Plan) or planned.target != target:
            raise _SubmissionRefused(f"{TARGET_STALE}: carrier plan does not bind this owner")
        return planned

    def _apply_prepared(self, service, plan: Plan, operation_key: str):
        try:
            return service.apply_prepared(plan.plan_id, operation_key)
        except NativeConfigurationUnavailable:
            raise
        except Exception as error:  # noqa: BLE001 - undecided, never a crash path
            raise _SubmissionUnknown(f"{type(error).__name__}: {error}") from error

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
            from ordessa_harness.configuration.model.bridge import ADAPTER_IDS
            adapter_id = ADAPTER_IDS.get(harness_id)
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
            "the product applies model intent only through the shared C4 "
            "turn-application entry (appendix §3.3)")


class ProfileTurnIntentSink:
    """The bound-mode intent bridge (appendix §3.1): a model choice for a
    registered Profile session is written into that session's overlay and the
    sink takes the authority; any other target declines so the model-provider
    queue stays the authority. Registration is a backend fact (the neutral
    authority's canonical UID minted at Profile registration), never a UI
    session id.

    Three-state answer (appendix §6c F2.1, codex review F2): ``True`` = the
    overlay now owns the intent; ``False`` = the target is genuinely unbound
    (no Profile assembly, or no registered session for this native reference)
    and the queue keeps the authority; anything else raises the typed
    :class:`TurnIntentHandoverError` — a bound target whose overlay write
    failed, or whose registration lookup failed, is UNKNOWN, never "unbound".
    """

    def __init__(self, *, core_of: Callable[[], Any],
                 sessions_of: Callable[[], Any]) -> None:
        self._core_of = core_of
        self._sessions_of = sessions_of

    def is_bound(self, target: Mapping[str, Any]) -> bool:
        sessions = self._sessions_of()
        if sessions is None or self._core_of() is None:
            return False
        ref = sessions.registered_ref_for_native(
            harness_id=str(target.get("harnessId") or ""),
            native_session_id=str(target.get("acpSessionId") or ""))
        if ref is None:
            return False
        sessions.require_registered(ref)
        return True

    def offer_turn_intent(self, target: Mapping[str, Any], *, operation_key: str,
                          sequence: int, intent: Mapping[str, Any]) -> bool:
        # Absent composition ports are an UNBOUND verdict, not a failure: the
        # model-provider queue is the authority exactly as without Profile
        # (FR-01/M02 - the sink object outlives a Profile deactivation).
        sessions = self._sessions_of()
        core = self._core_of()
        if sessions is None or core is None:
            return False
        harness_id = str(target.get("harnessId") or "")
        try:
            ref = sessions.registered_ref_for_native(
                harness_id=harness_id,
                native_session_id=str(target.get("acpSessionId") or ""))
        except Exception as error:  # noqa: BLE001 - a broken lookup is never "unbound"
            raise TurnIntentHandoverError(
                f"profile session registration lookup failed: "
                f"{type(error).__name__}: {error}") from error
        if ref is None:
            return False  # unbound: the queue keeps the authority
        choice = dict(intent.get("choice") or {})
        value = {"harnessId": harness_id,
                 "providerConfigId": str(choice.get("providerConfigId") or ""),
                 "modelId": str(choice.get("modelId") or "")}
        # The Profile service validates the item through the facet
        # provider, draws the session-level action_seq and bumps the row
        # revision - T02-A's "last user action wins" machinery, reused
        # verbatim; nothing new is invented for the overlay write.
        try:
            core.sessions.set_overlay(f"model-provider-intent:{operation_key}",
                session_id=ref.session_uid, facet_id=FACET_ID, item_id=ITEM_ID,
                value=value)
        except Exception as error:  # noqa: BLE001 - typed, never folded into False
            raise TurnIntentHandoverError(
                f"bound overlay handover failed: "
                f"{type(error).__name__}: {error}") from error
        return True

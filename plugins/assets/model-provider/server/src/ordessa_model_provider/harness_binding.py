"""PB-3: the ``HarnessConfigPort`` bound to the real C4
``ConfigurationApplicationService`` (the production submit gate, MP-05).

The 011-era port implementations were controlled fakes
(``testing.FakeHarnesses``); this module binds the same port protocol to the
real application chain: ``plan → apply(plan_id, operation_key,
submission_permit) → adapter verify → read-back``. Failure mapping is
fail-closed and typed:

- harness ``Refused(CAPABILITY_UNSUPPORTED/VERSION_UNVERIFIED/ADAPTER_MISSING)``
  → ``SESSION_CONFIG_UNSUPPORTED`` (the choice can never apply here);
- every other harness refusal (authorization, stale plan, target conflict, …)
  → ``SESSION_CONFIG_REJECTED``;
- harness ``Unknown`` → ``SESSION_CONFIG_OUTCOME_UNKNOWN`` (blocked, never
  retried by the caller).

Production honesty (dispatch PB-3, S-06): until the admission authority flips
``ready`` (core INT mechanism + P-E evidence), a composition without a permit
source is still constructible but every apply refuses — the port then relies
on the service's own one-use permit gate (a bare ``apply`` without a valid
permit is ``AUTHORIZATION_REFUSED`` before any native effect). The
controlled-level full chain runs with :class:`ControlledPermit`-shaped
mint/verify pairs in the tests; the production-level statement stays
"refused/unknown until S-06" and is asserted, not faked.

This module consumes harness-api/ordessa_harness read-only; it never imports
Server host internals beyond the port vocabulary it implements.
"""
from __future__ import annotations

import hashlib
from typing import Any, Callable, Mapping

from ordessa_harness_api import Confirmed, DesiredFragment, Refused, Unknown

from ordessa_model_provider.ports import (
    ELIGIBILITY_READY, ELIGIBILITY_UNKNOWN, ELIGIBILITY_UNSUPPORTED,
    SESSION_CONFIG_OUTCOME_UNKNOWN, SESSION_CONFIG_REJECTED,
    SESSION_CONFIG_UNSUPPORTED, SessionConfigError,
)

#: The facet this port drives (the adapters' declared facet, frozen in 011).
FACET_ID = "assets.model-provider"
SCHEMA_VERSION = "1"
ITEM_ID = "choice"

#: Codex's wire vocabulary spells the failure code on the wire; here the port
#: speaks the SESSION_CONFIG_* seam triad (ports.py contract).
_REFUSED_TO_SEAM = {
    "capability-unsupported": SESSION_CONFIG_UNSUPPORTED,
    "version-unverified": SESSION_CONFIG_UNSUPPORTED,
    "adapter-missing": SESSION_CONFIG_UNSUPPORTED,
}


class ConfigurationServiceHarnessPort:
    """The ``HarnessConfigPort`` backed by one C4 application service.

    ``permit_source(operation_key) -> str | None`` mints the one-use submit
    permit; a composition without an admission authority (S-06 open) supplies
    ``permit_source=None`` and every apply then refuses at the service's own
    permit gate — honestly refused, never silently applied.
    ``revision_source(session_ref) -> str`` supplies the optimistic-concurrency
    revision the C4 plan fence checks.
    """

    def __init__(self, service, *, target, permit_source: Callable[[str], str | None] | None,
                 revision_source: Callable[[Mapping[str, Any]], str],
                 harnesses: tuple[str, ...] = ("pi", "codex", "claude-code")) -> None:
        self._service = service
        self.target = target
        self._permit_source = permit_source
        self._revision_source = revision_source
        self._harnesses = tuple(harnesses)
        self._last_readback: dict[tuple[str, ...], Mapping[str, Any]] = {}
        #: The C4 journal binds one operation key to ONE plan forever; a
        #: replay must therefore come through the same plan id (the service
        #: re-checks every fence at apply, so reuse is safe).
        self._plans: dict[tuple[tuple[str, ...], str, str], str] = {}

    # -- HarnessConfigPort protocol -------------------------------------------

    def describe(self, harness_id: str) -> Mapping[str, Any] | None:
        if harness_id not in self._harnesses:
            return None
        return {
            "harnessId": harness_id,
            "facetId": FACET_ID,
            "facetSchemaVersion": SCHEMA_VERSION,
            "applicationService": "harness.configuration.v1",
        }

    def eligibility(self, harness_id: str, config_ref: Mapping[str, Any],
                    session_ref: Mapping[str, Any] | None) -> str:
        """The structural eligibility verdict: the facet's registered adapter
        matches THIS runtime (harness id, observed native version inside the
        pinned range, adapter entry) — that is the evidence ``ready`` carries.
        Per-choice evidence is never pre-granted: every apply goes through the
        C4 plan/apply gates (version fence, adapter assessment, permit).
        Absent facet → ``unknown``, version-range refusal → ``unsupported`` —
        never a guess."""
        if harness_id not in self._harnesses:
            return ELIGIBILITY_UNKNOWN
        capabilities = self._service.inspect(self.target)
        matching = [item for item in capabilities.capabilities
                    if item.facet_id == FACET_ID and item.harness_id == harness_id]
        if not matching:
            return ELIGIBILITY_UNKNOWN
        if any(item.status == "unsupported" for item in matching):
            return ELIGIBILITY_UNSUPPORTED
        if all(item.status == "unknown" and "publication unavailable" in (item.reason or "")
               for item in matching):
            return ELIGIBILITY_UNKNOWN
        return ELIGIBILITY_READY

    def apply(self, session_ref: Mapping[str, Any], choice: Mapping[str, Any]) -> Mapping[str, Any]:
        operation_key = _operation_key(session_ref, choice)
        session_key = _session_key(session_ref)
        choice_id = str(choice.get("providerConfigId") or choice.get("provider")), \
            str(choice.get("modelId") or choice.get("model"))
        plan_id = self._plans.get((session_key, *choice_id))
        if plan_id is None:
            revision = self._revision_source(session_ref)
            fragment = DesiredFragment(FACET_ID, ITEM_ID, SCHEMA_VERSION,
                                       choice_id[0], revision, "set", _choice_payload(choice))
            planned = self._service.plan(self.target, (fragment,), revision)
            if isinstance(planned, Refused):
                raise SessionConfigError(_seam_code(planned), _diagnostic(planned))
            plan_id = planned.plan_id
            self._plans[(session_key, *choice_id)] = plan_id
        permit = self._permit_source(operation_key) if self._permit_source else None
        result = self._service.apply(plan_id, operation_key, permit or "")
        if isinstance(result, Confirmed):
            readback = {"model": choice.get("modelId") or choice.get("model"),
                        "nativeSessionId": result.native_session_identity,
                        "evidenceRef": result.verification_evidence_ref}
            self._last_readback[_session_key(session_ref)] = readback
            return {
                "operationId": result.operation_id,
                "appliedRevision": result.applied_revision,
                "readBack": readback,
                "configOptions": {},
            }
        if isinstance(result, Unknown):
            raise SessionConfigError(SESSION_CONFIG_OUTCOME_UNKNOWN,
                                     _unknown_reason(result))
        raise SessionConfigError(_seam_code(result), _diagnostic(result))

    def read_back(self, session_ref: Mapping[str, Any]) -> Mapping[str, Any]:
        readback = self._last_readback.get(_session_key(session_ref))
        if readback is None:
            raise SessionConfigError(
                SESSION_CONFIG_OUTCOME_UNKNOWN,
                "no confirmed application is on record for this session")
        return dict(readback)


def _session_key(session_ref: Mapping[str, Any]) -> tuple[str, ...]:
    return tuple(str(session_ref.get(key)) for key in
                 ("serverInstanceId", "harnessId", "acpSessionId"))


def _operation_key(session_ref: Mapping[str, Any], choice: Mapping[str, Any]) -> str:
    basis = "|".join((
        *_session_key(session_ref),
        str(choice.get("providerConfigId") or choice.get("provider")),
        str(choice.get("modelId") or choice.get("model")),
    ))
    return f"mp-{hashlib.sha256(basis.encode('utf-8')).hexdigest()[:32]}"


def _choice_payload(choice: Mapping[str, Any]) -> dict[str, Any]:
    """The choice wire shape → the facet payload schema (bridge
    ``choice_payload_schema``). Endpoint/credential stay explicit Nones (the
    schema is nullable there); other absent keys drop out."""
    payload: dict[str, Any] = {
        "provider": choice.get("provider") or choice.get("providerConfigId"),
        "model": choice.get("modelId") or choice.get("model"),
        "endpoint": None,
        "protocol": choice.get("protocol"),
        "credentialRef": None,
    }
    if choice.get("endpoint") is not None:
        payload["endpoint"] = choice["endpoint"]
    if choice.get("credentialRef") is not None:
        payload["credentialRef"] = choice["credentialRef"]
    if choice.get("brandFields"):
        payload["brandFields"] = dict(choice["brandFields"])
    return payload


def _seam_code(refusal: Refused) -> str:
    return _REFUSED_TO_SEAM.get(refusal.code.value, SESSION_CONFIG_REJECTED)


def _diagnostic(refusal: Refused) -> str:
    return "; ".join(refusal.diagnostics) or refusal.code.value


def _unknown_reason(unknown: Unknown) -> str:
    return f"{unknown.phase}: " + ", ".join(unknown.pending_checks)

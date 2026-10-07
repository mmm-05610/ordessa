# migrated from plugins/model-provider@9305563719d25e04076b9221a7284660bd8f8642 (src/ordessa_model_provider/ports.py, verbatim)
"""The domain's optional port protocols — the lead-frozen seam (plan.md T1.5).

Every port is optional at runtime. Absence has a frozen, fail-closed meaning
per contract (`specs/002-model-provider/contracts/domain-ports.md`); a missing
port is never read as "no references" or "no objection". Implementations are
supplied by optional contributor plugins (profile-contribution) or the harness
side (integration wave), injected through constructor arguments or host
provided_ports.
"""
from __future__ import annotations

from typing import Any, Mapping, Protocol, runtime_checkable

#: Eligibility words (frozen vocabulary, data-model.md §2.2). ``ready`` is the
#: only selectable value and requires adapter evidence; a probe pass never
#: grants it.
ELIGIBILITY_READY = "ready"
ELIGIBILITY_UNSUPPORTED = "unsupported"
ELIGIBILITY_UNKNOWN = "unknown"

#: Typed archive refusal when the reference port is absent: "cannot prove
#: there are no references" is not "there are none" (spec FR-ARCH-2).
REFERENCE_STATE_UNKNOWN = "REFERENCE_STATE_UNKNOWN"

#: Session-config outcome codes (contracts/session-config-seam.md). The seam
#: triad maps onto the next-turn terminal states: UNSUPPORTED/REJECTED ->
#: ``refused``, OUTCOME_UNKNOWN -> ``unknown-outcome``.
SESSION_CONFIG_UNSUPPORTED = "SESSION_CONFIG_UNSUPPORTED"
SESSION_CONFIG_REJECTED = "SESSION_CONFIG_REJECTED"
SESSION_CONFIG_OUTCOME_UNKNOWN = "SESSION_CONFIG_OUTCOME_UNKNOWN"


class SessionConfigError(RuntimeError):
    """A typed session-config failure; ``code`` is one of the SESSION_CONFIG_*
    words above. The next-turn pipeline never lets a bare exception claim a
    state: anything outside these codes is a conservative ``refused``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


@runtime_checkable
class ReferencePort(Protocol):
    """Who references a provider config (active Profiles today).

    Absent port: ``archive`` refuses with ``REFERENCE_STATE_UNKNOWN`` (409) —
    fail-closed. Present port with a non-empty list: ``archive`` refuses with
    the legacy ``REFERENCE_CONFLICT`` (409) carrying the reference ids.
    """

    def references_of(self, provider_config_id: str) -> list[str]:
        """Return the ids of active objects referencing the config."""
        ...


@runtime_checkable
class HarnessConfigPort(Protocol):
    """The harness side's configuration description/application authority.

    The harness adapter owns the config format, the login/credential state and
    what "apply in this session's next turn" means for its harness; this
    plugin never guesses formats. Absent port: every eligibility answer is
    ``ELIGIBILITY_UNKNOWN`` — never ``ready``.
    """

    def describe(self, harness_id: str) -> Mapping[str, Any] | None:
        """The harness's configuration format description, or None if unknown."""
        ...

    def eligibility(
        self, harness_id: str, config_ref: Mapping[str, Any],
        session_ref: Mapping[str, Any] | None,
    ) -> str:
        """``ready`` | ``unsupported`` | ``unknown`` for one (config, session).

        The five evidence requirements of spec §4 are adjudicated here; a
        bare "the backend accepts a model id" is not sufficient evidence.
        """
        ...

    def apply(
        self, session_ref: Mapping[str, Any], choice: Mapping[str, Any],
    ) -> Mapping[str, Any]:
        """Apply the atomic choice in the owning session.

        Returns a receipt mapping (must include the post-apply read-back of
        the applied option). Raises ``SessionConfigError`` with one of the
        SESSION_CONFIG_* codes; success without a verified read-back is not a
        success (contract: read-back is part of apply).
        """
        ...

    def read_back(self, session_ref: Mapping[str, Any]) -> Mapping[str, Any]:
        """The session's current config-option values (post-apply verification)."""
        ...


@runtime_checkable
class CatalogView(Protocol):
    """The next-turn pipeline's read-only view of the provider-config store.

    ``catalog.ModelCatalogService`` provides this; the pipeline depends on the
    protocol, not the class, so the slice stays testable in isolation.
    ``config_version``/``model_ids`` raise the catalog's typed
    ``PROVIDER_MODEL_NOT_FOUND`` when the record does not exist.
    """

    def config_version(self, provider_config_id: str) -> int: ...

    def model_ids(self, provider_config_id: str) -> list[str]: ...

    def is_archived(self, provider_config_id: str) -> bool: ...


__all__ = [
    "ELIGIBILITY_READY", "ELIGIBILITY_UNSUPPORTED", "ELIGIBILITY_UNKNOWN",
    "REFERENCE_STATE_UNKNOWN",
    "SESSION_CONFIG_UNSUPPORTED", "SESSION_CONFIG_REJECTED",
    "SESSION_CONFIG_OUTCOME_UNKNOWN",
    "SessionConfigError", "ReferencePort", "HarnessConfigPort", "CatalogView",
]

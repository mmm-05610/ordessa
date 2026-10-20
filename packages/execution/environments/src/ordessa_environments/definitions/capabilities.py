"""The managed environment capability model.

One report describes what a managed environment backend **actually** provides
today. It is a report of fact, never a wish list and never a permission: a
requirement that is not ``supported`` is refused here rather than silently
downgraded.

The capability model is the managed path's single vocabulary and requirement
check. The retired legacy ``Capabilities`` / ``require_guarantees`` pair and its
``EnvironmentHandle`` path no longer exist: every consumer checks a
:class:`CapabilityReport` with :func:`require_capabilities`. Both views share the
same :class:`CapabilityStatus` values.

``values`` is bounded to the recognised key vocabulary. Absence of a key is not
a claim: a required key that is absent is refused exactly like an explicitly
``unavailable``/``unsupported`` one.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping

from ordessa_infrastructure.encoding.content_identity import digest

from .contracts import (
    BYTE_CHANNEL_CAPABILITY,
    FILE_AREA_CAPABILITY,
    PROCESS_CAPABILITY,
    STREAMING_STDERR_CAPABILITY,
    TERMINAL_CAPABILITY,
)
from .errors import EnvironmentGuaranteeUnmet, EnvironmentRefused

#: Outbound network access as a managed environment capability. It is separate
#: from the five legacy keys because a provider may expose processes and byte
#: channels without making any statement about egress.
OUTBOUND_NETWORK_CAPABILITY = "outbound-network"

#: The managed path's capability vocabulary: the five legacy keys plus the
#: explicit outbound-network key. Providers report only keys they can prove.
CAPABILITY_KEYS = frozenset(
    {
        PROCESS_CAPABILITY,
        BYTE_CHANNEL_CAPABILITY,
        FILE_AREA_CAPABILITY,
        STREAMING_STDERR_CAPABILITY,
        TERMINAL_CAPABILITY,
        OUTBOUND_NETWORK_CAPABILITY,
    }
)

_MAX_VALUES = 128
_MAX_DETAILS = 32
_MAX_KEY = 128
_MAX_DETAIL_VALUE = 512


class CapabilityStatus(str, Enum):
    """How a capability is provided, from proven to not implemented.

    ``supported`` is proven now; ``conditional`` is provided only under a stated
    condition; ``unavailable`` exists in the model but is not available here;
    ``unsupported`` is not implemented by this provider at all.
    """

    SUPPORTED = "supported"
    CONDITIONAL = "conditional"
    UNAVAILABLE = "unavailable"
    UNSUPPORTED = "unsupported"


def _text(value: str, name: str, limit: int, *, allow_empty: bool = False) -> str:
    if (
        not isinstance(value, str)
        or len(value) > limit
        or "\0" in value
        or (not value and not allow_empty)
    ):
        raise EnvironmentRefused(f"invalid {name}")
    return value


@dataclass(frozen=True)
class CapabilityReport:
    """What one managed environment backend reports it can really do.

    ``values`` maps recognised capability keys to their status. ``isolation``
    names the real isolation level, ``assurance`` names the evidence class
    behind the report (never a permission), and ``details`` carries bounded
    provider facts as strings. ``affinity`` is an opaque placement hint.
    """

    values: Mapping[str, CapabilityStatus]
    isolation: str
    assurance: str
    affinity: str = ""
    details: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        values = dict(self.values)
        if len(values) > _MAX_VALUES:
            raise EnvironmentRefused("capability report has too many entries")
        for key, status in values.items():
            if not isinstance(key, str) or not key or len(key) > _MAX_KEY or "\0" in key:
                raise EnvironmentRefused("capability report keys must be bounded non-empty strings")
            if key not in CAPABILITY_KEYS:
                raise EnvironmentRefused(f"unknown capability key: {key!r}")
            if not isinstance(status, CapabilityStatus):
                raise EnvironmentRefused(f"capability {key!r} requires a CapabilityStatus")
        object.__setattr__(self, "values", values)
        _text(self.isolation, "isolation", 64)
        _text(self.assurance, "assurance", 64)
        _text(self.affinity, "affinity", 256, allow_empty=True)
        details = dict(self.details)
        if len(details) > _MAX_DETAILS:
            raise EnvironmentRefused("capability report has too many detail facts")
        for key, value in details.items():
            if not isinstance(key, str) or not key or len(key) > _MAX_KEY or "\0" in key:
                raise EnvironmentRefused("capability detail keys must be bounded non-empty strings")
            if not isinstance(value, str) or len(value) > _MAX_DETAIL_VALUE or "\0" in value:
                raise EnvironmentRefused("capability detail values must be bounded strings")
        object.__setattr__(self, "details", details)

    @property
    def provides(self) -> frozenset[str]:
        """The keys this report proves right now (``supported`` only).

        This is the derived "actually provided" view the ``envctl`` example
        and :func:`require_capabilities` consumers read.
        """
        return frozenset(
            key for key, status in self.values.items() if status is CapabilityStatus.SUPPORTED
        )

    @property
    def detail(self) -> Mapping[str, str]:
        """Provider facts under the singular spelling the ``envctl`` example reads."""
        return self.details

    @property
    def digest(self) -> str:
        """Stable content digest over the whole report, independent of dict order."""
        return digest(
            {
                "values": {key: value.value for key, value in sorted(self.values.items())},
                "isolation": self.isolation,
                "assurance": self.assurance,
                "affinity": self.affinity,
                "details": dict(sorted(self.details.items())),
            }
        )


def require_capabilities(
    report: CapabilityReport,
    required,
    *,
    accept_conditional: bool = False,
) -> None:
    """Refuse unless the report proves every required capability.

    Only ``supported`` passes by default. ``conditional`` passes only with an
    explicit ``accept_conditional=True`` opt-in. ``unavailable``, ``unsupported``
    and absent keys always refuse. The refusal lists the missing keys.
    """
    if not isinstance(report, CapabilityReport):
        raise EnvironmentRefused("require_capabilities needs a CapabilityReport")
    if type(accept_conditional) is not bool:
        raise EnvironmentRefused("accept_conditional must be an explicit boolean policy")
    required_keys = set(required)
    if any(not isinstance(key, str) or not key for key in required_keys):
        raise EnvironmentRefused("required capability keys must be non-empty strings")
    missing = []
    for key in sorted(required_keys):
        status = report.values.get(key)
        if status is CapabilityStatus.SUPPORTED:
            continue
        if status is CapabilityStatus.CONDITIONAL and accept_conditional:
            continue
        missing.append(key)
    if missing:
        raise EnvironmentGuaranteeUnmet(
            f"capability report (isolation={report.isolation!r}) does not provide {missing}"
        )


__all__ = [
    "CAPABILITY_KEYS",
    "OUTBOUND_NETWORK_CAPABILITY",
    "CapabilityReport",
    "CapabilityStatus",
    "require_capabilities",
]

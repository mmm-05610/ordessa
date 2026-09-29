"""Bounded probe policy and the credential-less scopes it authorises.

Contracts (``docs/design/mcp/contracts.md`` §1, "probe" row): one probe runs
under an explicit bounded policy - a wall-clock timeout, a response byte
bound, a kill grace window and the client's supported protocol versions -
and a credential-less probe must never claim credentials (FR-02). This
module owns that policy shape plus the two derivations ``probe.py`` needs:

* the stdio child environment - a fixed legacy allowlist extended only with
  values explicitly typed ``{"literal": ...}``; every ``secretRef`` (and the
  legacy bare-string credential reference) is excluded and reported, never
  resolved here (credential resolution is T07's job);
* the remote header scope - the probe sends **none** of the definition's
  headers; every declared header name is reported as excluded.

Nothing in this module touches storage, spawns, or connects.
"""
from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, List, Mapping, Tuple

# Verbatim from the legacy probe (SC/assets/mcp_probe.py:56): the child never
# inherits the caller's environment, so no ambient secret can leak into it.
BASE_ENVIRONMENT = MappingProxyType({"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "HOME": "/tmp"})

_NEGOTIATION_BASELINE = "2025-11-25"  # docs/design/mcp/research-and-reuse.md


@dataclass(frozen=True)
class ProbePolicy:
    """One bounded, credential-less probe authorisation.

    ``supported_protocol_versions`` is the client capability list, newest
    first; ``supported_protocol_versions[0]`` is what the initialize request
    asks for, and the answer's own ``protocolVersion`` - never a stored
    field - is the negotiation result (research ledger: the old probe was
    pinned to ``2024-11-05``; T03 must distinguish the negotiated version).
    """

    timeout: float = 5.0
    max_bytes: int = 64 * 1024
    kill_grace: float = 2.0
    supported_protocol_versions: Tuple[str, ...] = (_NEGOTIATION_BASELINE, "2024-11-05")
    client_name: str = "ordessa-mcp-probe"
    client_version: str = "t03"

    def __post_init__(self) -> None:
        if not isinstance(self.timeout, (int, float)) or self.timeout <= 0:
            raise ValueError("a probe policy timeout must be positive")
        if not isinstance(self.max_bytes, int) or self.max_bytes < 1024:
            raise ValueError("a probe policy max_bytes must be an int >= 1024")
        if not isinstance(self.kill_grace, (int, float)) or self.kill_grace <= 0:
            raise ValueError("a probe policy kill_grace must be positive")
        if (not isinstance(self.supported_protocol_versions, tuple)
                or not self.supported_protocol_versions
                or any(not isinstance(v, str) or not v
                       for v in self.supported_protocol_versions)):
            raise ValueError("a probe policy needs a non-empty tuple of protocol versions")


DEFAULT_PROBE_POLICY = ProbePolicy()


def unproven_stdio_environment(
    env_values: Mapping[str, Any],
) -> Tuple[dict, List[str]]:
    """Split a definition's stdio env into (child environment, excluded keys).

    Only ``{"literal": value}`` entries join the fixed base allowlist. A
    ``{"secretRef": id}`` entry - or the legacy bare-string credential
    reference, or any unknown shape - is excluded from the child entirely and
    reported, so the result can state ``credentialScope: "unproven"`` with
    the exclusion list as its evidence.
    """
    environment = dict(BASE_ENVIRONMENT)
    excluded: List[str] = []
    for key, value in (env_values or {}).items():
        if (isinstance(value, Mapping) and set(value) == {"literal"}
                and isinstance(value["literal"], str)):
            environment[key] = value["literal"]
        else:
            excluded.append(str(key))
    return environment, sorted(excluded)


def unproven_remote_headers(header_values: Mapping[str, Any]) -> List[str]:
    """Names of every header the definition declares - all excluded.

    The probe never carries credentials (FR-02/FR-08): none of the declared
    headers, literal or secretRef, are ever sent on the probe request.
    """
    return sorted(str(key) for key in (header_values or {}))

"""Wire-family mapping for the Sandbox domain's stable refusal codes (T010b).

Contracts §C4: "错误须映射至既有 wire family，不修改核心错误分支". Every one of
the six stable codes in `SandboxErrorCode` resolves here to one of the twelve
families the platform already publishes — `server_plugin_api.wire_errors.FAMILIES`.
No row invents a family name and nothing in this module touches (or branches
inside) the platform's own error handling; the mapping is sandbox-side and
purely additive.

Derivation of each row (never a new family): each value is either a family
name the platform table answers for itself, or the family a same-shaped
existing platform row already answers with — the guard test
``tests/test_wire_family.py`` re-checks every row against
``server_plugin_api.wire_errors.family_for`` / ``converge_family`` /
``WireError`` at test time. §C4 forbids merging the `unsupported` and
`unknown` verdicts into one *code* (a missing probe must not read like a
documented limit); codes may share a family only where the platform
vocabulary says so — `SANDBOX_NATIVE_UNSUPPORTED` /
`SANDBOX_COVERAGE_UNPROVEN` / `SANDBOX_PLATFORM_UNSUPPORTED` all answer
`CAPABILITY_UNSUPPORTED` (the platform's documented-limit family, three
distinct codes), while `SANDBOX_EFFECT_UNKNOWN` stays in `OUTCOME_UNKNOWN`,
so the §C4 pair remains two spellings in two families.

`SANDBOX_INTENT_INVALID` is deliberately absent: it is Python-side input
validation only (errors.py's own comment), never a wire refusal, and asking
for its family is an unmapped-input error.

This package stays stdlib-only (its import-boundary guard forbids importing
`server_plugin_api` in src): the platform's own resolver — the one-argument
callable a composition injects, per `wire_errors.FamilyResolver` — is
therefore accepted as an *optional* `resolver` argument, so a host can have
the answer confirmed by its live composition table while the standalone
package reads no aggregate.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from enum import Enum

from .errors import SandboxApiError, SandboxErrorCode

#: What a composition injects for family resolution (mirrors
#: `server_plugin_api.wire_errors.FamilyResolver`, typed locally to keep the
#: stdlib-only import boundary).
FamilyResolver = Callable[[str], str]

#: The six stable sandbox codes -> the EXISTING wire/1 family each lands in.
#: Keys are the code spellings (the wire/`details.internalCode` vocabulary),
#: values are members of `server_plugin_api.wire_errors.FAMILIES`:
#:
#: - SANDBOX_NATIVE_UNSUPPORTED   -> CAPABILITY_UNSUPPORTED
#:       documented limit: the brand offers no native sandbox here.
#: - SANDBOX_COVERAGE_UNPROVEN    -> CAPABILITY_UNSUPPORTED
#:       documented limit: the claimed coverage is not a supported capability
#:       (distinct code from the row above — §C4 keeps the verdicts separate).
#: - SANDBOX_PLATFORM_UNSUPPORTED -> CAPABILITY_UNSUPPORTED
#:       documented limit: the platform cannot host the sandbox at all.
#: - SANDBOX_CONFIG_CONFLICT      -> CONFLICT_REQUEST
#:       platform precedent: state-conflict rows (`ENTERPRISE_STATE_CONFLICT`,
#:       `IDEMPOTENCY_CONFLICT`, `SESSION_BUSY`) answer `CONFLICT_REQUEST`;
#:       not `CONFLICT_VERSION`, which is optimistic-revision and the sandbox
#:       revision-badness case is schema-level (`SANDBOX_INTENT_INVALID`).
#: - SANDBOX_EFFECT_UNKNOWN       -> OUTCOME_UNKNOWN
#:       same word for the same verdict: a probe that did not resolve.
#: - PROVIDER_BUSY                -> UNAVAILABLE
#:       platform precedent: `SERVICE_UNAVAILABLE` answers `UNAVAILABLE`;
#:       not `WORKER_UNREACHABLE`, which is the connector-worker family.
SANDBOX_WIRE_FAMILIES: Mapping[str, str] = {
    SandboxErrorCode.SANDBOX_NATIVE_UNSUPPORTED.value: "CAPABILITY_UNSUPPORTED",
    SandboxErrorCode.SANDBOX_COVERAGE_UNPROVEN.value: "CAPABILITY_UNSUPPORTED",
    SandboxErrorCode.SANDBOX_PLATFORM_UNSUPPORTED.value: "CAPABILITY_UNSUPPORTED",
    SandboxErrorCode.SANDBOX_CONFIG_CONFLICT.value: "CONFLICT_REQUEST",
    SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN.value: "OUTCOME_UNKNOWN",
    SandboxErrorCode.PROVIDER_BUSY.value: "UNAVAILABLE",
}


def wire_family_for(code: "SandboxErrorCode | str",
                    *, resolver: FamilyResolver | None = None) -> str:
    """The existing wire family a stable sandbox refusal code maps to.

    `resolver` optionally re-answers the mapped family through the
    composition's platform resolver (`family_for` standalone, or an
    `ErrorFamilyAggregate.family_for` bound by the host): family names resolve
    to themselves, so injecting one can only confirm the row against the
    platform table — the mapping never routes a refusal through a new family.

    Raises `SandboxApiError(SANDBOX_INTENT_INVALID)` for any unmapped input
    (including `SANDBOX_INTENT_INVALID` itself, a Python-side-only code); the
    refusal message repeats only the code word — no paths, no secrets.
    """
    key = code.value if isinstance(code, Enum) else str(code)
    try:
        family = SANDBOX_WIRE_FAMILIES[key]
    except KeyError:
        raise SandboxApiError(
            SandboxErrorCode.SANDBOX_INTENT_INVALID,
            f"no wire family row for code {key!r}; the mapped domain is the "
            f"six stable sandbox codes",
            suggestion="use one of the six stable codes; schema-level "
                       "input refusals stay Python-side",
        ) from None
    return resolver(family) if resolver is not None else family

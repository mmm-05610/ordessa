"""The single Skills-domain brand capability registry (FR11, G10).

Every cell is graded `supported | unsupported | unknown` and MUST carry an
evidence string: either a repo `file:line` citation (into
`specs/011-q1-skills/research/brand-matrix.md`, the frozen in-repo evidence,
optionally quoting the underlying file itself) or the literal
`no in-repo evidence`. This module refuses to build a `supported` fact
without a citation — the rule inherited from the legacy
`harness_delivery/capabilities.py` ("没有证据就不声称",
docs/design/skills-v2/research-and-reuse.md §能力注册表).

Meaning of the two weak values (they are DISTINCT, per the design):

* ``unsupported`` — the repository carries first-hand evidence that the
  pinned brand/path CANNOT do this (e.g. an inspected artifact that lacks
  the mechanism entirely). Surfaced as "brand does not offer this".
* ``unknown`` — the repository has NO evidence either way. Vendor-doc
  claims live in `docs/design/skills-v2/harness-adapters.md` and are NOT
  capability; an `unknown` cell must never be presented as offered and must
  never be silently upgraded from vendor-doc reasoning
  (verification.md G10 counter-example: "官网新版能力误用于当前 pin").

This is the ONLY brand capability table in the Skills domain. The legacy
`harness_delivery/capabilities.py` is retired/empty
(docs/known-issues.md; research-and-reuse.md:28 says not to maintain a
second static brand table), and `api/ports.py` only carries a structural
Protocol consumed by the Harness delivery port — no cells. The guard test
`tests/test_harness_adapters_boundaries.py::
test_the_capability_registry_is_the_only_brand_table` pins this.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

#: The three gradings a capability cell may hold (contracts.md 能力矩阵).
SUPPORTED = "supported"
UNSUPPORTED = "unsupported"
UNKNOWN = "unknown"
CAPABILITY_VALUES = (SUPPORTED, UNSUPPORTED, UNKNOWN)

#: The literal every evidence-less cell must carry instead of a citation.
NO_EVIDENCE = "no in-repo evidence"

#: A citation is a repo path plus line number(s), e.g.
#: ``specs/011-q1-skills/research/brand-matrix.md:40``.
_CITATION = re.compile(r"[\w./+-]+:\d+")

BM = "specs/011-q1-skills/research/brand-matrix.md"

#: The required design axes (verification.md 品牌矩阵字段 plus the
#: namespacing axis that conflict evaluation consults).
AXES = (
    "native_version",
    "adapter_version",
    "discovery_mechanism",
    "isolation",
    "reload",
    "reset",
    "resume",
    "explicit_invocation",
    "loaded_evidence",
    "native_namespacing",
)


def _check_evidence(axis: str, value: str, evidence: str) -> None:
    if not isinstance(evidence, str) or not evidence.strip():
        raise ValueError(f"capability {axis}: evidence must be a non-empty string")
    if evidence != NO_EVIDENCE and _CITATION.search(evidence) is None:
        raise ValueError(
            f"capability {axis}: evidence must cite a repo file:line or be "
            f"the literal {NO_EVIDENCE!r}, got {evidence!r}")
    if value == SUPPORTED and evidence == NO_EVIDENCE:
        raise ValueError(
            f"capability {axis}: a supported claim without in-repo evidence "
            "is refused (G10 — no in-repo evidence就不声称)")


@dataclass(frozen=True)
class CapabilityFact:
    axis: str
    value: str
    evidence: str

    def __post_init__(self) -> None:
        if self.axis not in AXES:
            raise ValueError(f"unknown capability axis {self.axis!r}")
        if self.value not in CAPABILITY_VALUES:
            raise ValueError(
                f"capability {self.axis}: value must be one of "
                f"{CAPABILITY_VALUES}, got {self.value!r}")
        _check_evidence(self.axis, self.value, self.evidence)

    @property
    def is_offered(self) -> bool:
        """Only a proven `supported` cell is ever offered to UI or planning.

        `unknown` and `unsupported` both stay unoffered but keep distinct
        meanings — see the module docstring and verification.md G10.
        """
        return self.value == SUPPORTED


@dataclass(frozen=True)
class CapabilityStatement:
    harness_id: str
    facts: Mapping[str, CapabilityFact]
    #: True for the synthesized all-`unknown` shape handed to unregistered
    #: brands; such a brand has no pinned version either.
    synthesized: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "facts", MappingProxyType(dict(self.facts)))
        missing = [axis for axis in AXES if axis not in self.facts]
        if missing:
            raise ValueError(f"capability statement missing axes: {missing}")
        for axis, fact in self.facts.items():
            if fact.axis != axis:
                raise ValueError(f"capability fact key {axis} names {fact.axis}")

    def fact(self, axis: str) -> CapabilityFact:
        return self.facts[axis]

    def value(self, axis: str) -> str:
        return self.facts[axis].value

    def offered_axes(self) -> tuple[str, ...]:
        return tuple(axis for axis in AXES if self.facts[axis].is_offered)


def _unknown_fact(axis: str) -> CapabilityFact:
    return CapabilityFact(axis=axis, value=UNKNOWN, evidence=NO_EVIDENCE)


def _unknown_statement(harness_id: str) -> CapabilityStatement:
    """The honest shape for a brand with no registered evidence at all."""
    return CapabilityStatement(
        harness_id=harness_id,
        facts={axis: _unknown_fact(axis) for axis in AXES},
        synthesized=True,
    )


def _fact(axis: str, value: str, evidence: str) -> CapabilityFact:
    return CapabilityFact(axis=axis, value=value, evidence=evidence)


def _statement(harness_id: str, facts: tuple[CapabilityFact, ...]) -> CapabilityStatement:
    return CapabilityStatement(harness_id=harness_id,
                               facts={fact.axis: fact for fact in facts})


#: The one and only static brand table. Cells mirror the frozen matrix rows
#: (research/brand-matrix.md §2 and §6); nothing here is upgraded from
#: vendor-doc reasoning. `resume` is the only non-version axis with
#: in-repo observations for all three brands; `discovery_mechanism`,
#: `isolation`, `reload`, `reset`, `explicit_invocation`, `loaded_evidence`
#: and `native_namespacing` stay `unknown` for every brand because the
#: repo has no first-hand runtime evidence ("all runtime skill cells
#: unknown", brand-matrix.md:40,46,52).
BRAND_STATEMENTS: Mapping[str, CapabilityStatement] = MappingProxyType({
    "pi": _statement("pi", (
        _fact("native_version", SUPPORTED,
              f"{BM}:16,40 (plugins/harness/packaging/pi/package-lock.json:45-46;"
              " run chain itself PATH-resolved, brand-matrix.md:19)"),
        _fact("adapter_version", SUPPORTED,
              f"{BM}:17,40 (plugins/harness/packaging/pi/package.json:13)"),
        _fact("discovery_mechanism", UNKNOWN,
              f"{BM}:40 — no brand loader observation exists in-repo;"
              " project .pi discovery is vendor-doc only"),
        _fact("isolation", UNKNOWN,
              f"{BM}:40 — ro mount declaration proven,"
              " enforcement not in-repo-verifiable"),
        _fact("reload", UNKNOWN,
              f"{BM}:40 — /reload is vendor-doc only, no in-repo observation"),
        _fact("reset", UNKNOWN, NO_EVIDENCE),
        _fact("resume", SUPPORTED,
              f"{BM}:40 (plugins/harness/tests/test_capability_declarations.py:134-137;"
              " plugins/harness/src/ordessa_harness/pi/projection.py:29-33)"),
        _fact("explicit_invocation", UNKNOWN,
              f"{BM}:40 — /skill:name is vendor-doc; the pi-acp 0.5.0 bundle"
              " was never observed serving it"),
        _fact("loaded_evidence", UNKNOWN,
              f"{BM}:40,56-62 — skill_observation.py has zero callers and"
              " zero tests in-repo"),
        _fact("native_namespacing", UNKNOWN, NO_EVIDENCE),
    )),
    "codex": _statement("codex", (
        _fact("native_version", SUPPORTED,
              f"{BM}:20,46 (plugins/harness/src/ordessa_harness/codex/production.py:88)"),
        _fact("adapter_version", SUPPORTED,
              f"{BM}:21,46 (plugins/harness/packaging/codex/package.json:13)"),
        _fact("discovery_mechanism", UNKNOWN,
              f"{BM}:46 — skills/list is protocol-schema declaration only;"
              " zero runtime calls in-repo"),
        _fact("isolation", UNKNOWN,
              f"{BM}:46 — projections declared; bwrap enforcement retired"),
        _fact("reload", UNKNOWN,
              f"{BM}:46 — skills/changed + forceReload are schema declarations"
              " only, zero runtime calls"),
        _fact("reset", UNKNOWN, NO_EVIDENCE),
        _fact("resume", SUPPORTED,
              f"{BM}:46 (plugins/harness/tests/test_capability_declarations.py:100-101,"
              " 110-112)"),
        _fact("explicit_invocation", UNKNOWN,
              f"{BM}:46 — command/defaultPrompt fields exist in the schema"
              " only; no invocation-event plumbing in-repo"),
        _fact("loaded_evidence", UNKNOWN,
              f"{BM}:46,65 — projected only; approval schema never handled"
              " by Go code; legacy verify_load-as-loaded ruling retired"),
        _fact("native_namespacing", UNKNOWN, NO_EVIDENCE),
    )),
    "claude-code": _statement("claude-code", (
        _fact("native_version", UNKNOWN,
              f"{BM}:24,52 — CLI 2.1.274 is a comment-only first-hand"
              " observation, not a machine pin; §6 does not list it as proven"),
        _fact("adapter_version", SUPPORTED,
              f"{BM}:22,52 (plugins/harness/packaging/claude/package.json:13;"
              " plugins/harness/src/ordessa_harness/claude/production.py:66-67)"),
        _fact("discovery_mechanism", UNKNOWN,
              f"{BM}:52 — every skill cell (roots actually scanned, reload,"
              " loaded) is unknown; profile.py writer is orphaned"),
        _fact("isolation", UNKNOWN,
              f"{BM}:52 — provider isolation verified against fake loopback"
              " endpoints only"),
        _fact("reload", UNKNOWN, f"{BM}:52 — no in-repo evidence"),
        _fact("reset", UNKNOWN, NO_EVIDENCE),
        _fact("resume", SUPPORTED,
              f"{BM}:52 (plugins/harness/tests/test_capability_declarations.py:207-235)"),
        _fact("explicit_invocation", UNKNOWN, f"{BM}:52 — no in-repo evidence"),
        _fact("loaded_evidence", UNKNOWN,
              f"{BM}:52 — projected only; the live production chain never"
              " observes a Claude skill load"),
        _fact("native_namespacing", UNKNOWN,
              f"{BM}:52; docs/design/skills-v2/harness-adapters.md:12 — the"
              " plugin namespace is vendor-doc, therefore treated as unknown"
              " and refused by conflict evaluation"),
    )),
})


def statement_for(harness_id: str) -> CapabilityStatement:
    """The registered statement, or an all-`unknown` shape for others.

    Unregistered brands (Hermes, OpenCode, …) never receive a guessed cell:
    "Hermes/OpenCode 等可在同一注册点以后接入，无空模块冒充支持"
    (docs/design/skills-v2/harness-adapters.md).
    """
    statement = BRAND_STATEMENTS.get(harness_id)
    if statement is None:
        return _unknown_statement(harness_id)
    return statement


def registered_brands() -> tuple[str, ...]:
    return tuple(BRAND_STATEMENTS)


@dataclass(frozen=True)
class VersionPin:
    """The pinned native/adapter versions the matrix froze, per brand.

    `assess` refuses any other version (fail closed, harness-adapters.md
    "运行版本不符时拒绝能力"). `native_pin_is_machine_enforced` records that
    Claude's CLI pin is comment-only and Pi's run chain resolves via PATH —
    those pins are the only evidenced values, not enforcement.
    """

    harness_id: str
    native_version: str
    adapter_version: str
    native_evidence: str
    adapter_evidence: str
    native_pin_is_machine_enforced: bool

    def __post_init__(self) -> None:
        _check_evidence("native_version", SUPPORTED, self.native_evidence)
        _check_evidence("adapter_version", SUPPORTED, self.adapter_evidence)


BRAND_PINS: Mapping[str, VersionPin] = MappingProxyType({
    "pi": VersionPin(
        harness_id="pi",
        native_version="0.84.2",
        adapter_version="0.5.0",
        native_evidence=f"{BM}:16 (plugins/harness/packaging/pi/package-lock.json:45-46)",
        adapter_evidence=f"{BM}:17 (plugins/harness/packaging/pi/package.json:13)",
        native_pin_is_machine_enforced=False,
    ),
    "codex": VersionPin(
        harness_id="codex",
        native_version="0.147.0",
        adapter_version="1.1.14",
        native_evidence=f"{BM}:20 (plugins/harness/src/ordessa_harness/codex/production.py:88)",
        adapter_evidence=f"{BM}:21 (plugins/harness/packaging/codex/package.json:13)",
        native_pin_is_machine_enforced=True,
    ),
    "claude-code": VersionPin(
        harness_id="claude-code",
        native_version="2.1.274",
        adapter_version="0.81.2",
        native_evidence=f"{BM}:24,52 (plugins/harness/src/ordessa_harness/harnesses.toml:111-113)",
        adapter_evidence=f"{BM}:22 (plugins/harness/packaging/claude/package.json:13)",
        native_pin_is_machine_enforced=False,
    ),
})


def pin_for(harness_id: str) -> VersionPin | None:
    return BRAND_PINS.get(harness_id)

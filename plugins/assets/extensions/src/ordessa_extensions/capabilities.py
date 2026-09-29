"""EXT-4 — the one hooks capability table for the eight brands.

Every cell is graded `supported | unsupported | unknown` and MUST carry an
in-repo citation (repo `file:line`) or the literal `no in-repo evidence`
— the rule inherited from the Skills domain registry ("没有证据就不声称",
specs/011-q1-skills/research/brand-matrix.md). Vendor-doc claims live in
`docs/design/harness-configuration/harnesses.md` and are cited as such;
they never grade a `supported` cell alone.

Distinct weak values (NOT conflated):

* ``unsupported`` — first-hand in-repo evidence that THIS pin/path cannot
  do it (including: the registry registers no hooks slot at all);
* ``unknown`` — no evidence either way; never presented as offered.

Implementation dispositions are kept SEPARATE from capability cells: the
brand priority ruling (specs/016-overnight-batch/spec.md §品牌优先级)
sends hermes/opencode/dsh/kilo to phase-2 design (NOT implemented
tonight) and REMOVES qwen entirely ("qwen 已除名" — its row records the
removal, not a capability grade).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

SUPPORTED = "supported"
UNSUPPORTED = "unsupported"
UNKNOWN = "unknown"
CAPABILITY_VALUES = (SUPPORTED, UNSUPPORTED, UNKNOWN)

NO_EVIDENCE = "no in-repo evidence"

_CITATION = re.compile(r"[\w./+-]+:\d+")

TOML = "plugins/harness/src/ordessa_harness/harnesses.toml"
HM = "docs/design/harness-configuration/harnesses.md"

AXES = (
    "native_slot",        # the brand registry declares a hooks slot
    "projection_path",    # the harness runtime supplies hooks targets
    "blocking_semantics", # EXT-6: observational-only on every face
    "load_evidence",      # any in-repo observation of a hook actually loading
)

#: Brands with hooks slot in the registry (grep `identity =` + `slots =`):
#: codex (harnesses.toml:31) and claude (harnesses.toml:107) carry "hooks";
#: opencode:163, hermes:215, dsh:270, kilo:357, pi:405 do not; qwen:311
#: carried mcp/skill only and is removed by user ruling anyway.
_BRANDS = ("pi", "codex", "claude", "hermes", "opencode", "dsh", "kilo",
           "qwen")


def _check_evidence(axis: str, value: str, evidence: str) -> None:
    if not isinstance(evidence, str) or not evidence.strip():
        raise ValueError(f"capability {axis}: evidence must be a non-empty "
                         "string")
    if evidence != NO_EVIDENCE and _CITATION.search(evidence) is None:
        raise ValueError(f"capability {axis}: evidence must cite a repo "
                         f"file:line or be {NO_EVIDENCE!r}, got {evidence!r}")
    if value == SUPPORTED and evidence == NO_EVIDENCE:
        raise ValueError(f"capability {axis}: a supported claim without "
                         "in-repo evidence is refused")


@dataclass(frozen=True)
class HookCapabilityFact:
    axis: str
    value: str
    evidence: str

    def __post_init__(self) -> None:
        if self.axis not in AXES:
            raise ValueError(f"unknown capability axis {self.axis!r}")
        if self.value not in CAPABILITY_VALUES:
            raise ValueError(f"capability {self.axis}: value must be one of "
                             f"{CAPABILITY_VALUES}, got {self.value!r}")
        _check_evidence(self.axis, self.value, self.evidence)

    @property
    def is_offered(self) -> bool:
        return self.value == SUPPORTED


@dataclass(frozen=True)
class HookSupportStatement:
    harness_id: str
    facts: Mapping[str, HookCapabilityFact]

    def __post_init__(self) -> None:
        object.__setattr__(self, "facts",
                           MappingProxyType(dict(self.facts)))
        missing = [axis for axis in AXES if axis not in self.facts]
        if missing:
            raise ValueError(f"hook statement missing axes: {missing}")

    def value(self, axis: str) -> str:
        return self.facts[axis].value

    def fact(self, axis: str) -> HookCapabilityFact:
        return self.facts[axis]


def _statement(harness_id: str,
               facts: tuple[HookCapabilityFact, ...]) -> HookSupportStatement:
    return HookSupportStatement(
        harness_id=harness_id,
        facts={fact.axis: fact for fact in facts})


# The registry runtime gap is first-hand greppable: `hooks_target` /
# `hooks_key` are parsed in registry/schema.py:90-104 and consumed by
# NOTHING else under plugins/harness/src (EXT 016 verification; the
# registry-runtime seam is registered as AR-3).
_RUNTIME_GAP = (f"{TOML}:38-40,117-120 (registry declares the targets); "
                "plugins/harness/src/ordessa_harness/registry/schema.py:90-104"
                " (parsed); zero consumers elsewhere in"
                " plugins/harness/src — runtime supplies no hooks targets"
                " (AR-3)")

BRAND_STATEMENTS: Mapping[str, HookSupportStatement] = MappingProxyType({
    "codex": _statement("codex", (
        HookCapabilityFact("native_slot", SUPPORTED,
                           f"{TOML}:38-40 (Order 59 stage A: pinned codex"
                           " reads hooks/hooks.json, claude event names);"
                           " docs/design/harness-configuration/"
                           "source-index.json:196-203 (codex config"
                           " reference extraction: hooks.<Event> key"
                           " family, fetched 2026-09-27 with sha256)"),
        HookCapabilityFact("projection_path", UNSUPPORTED, _RUNTIME_GAP),
        HookCapabilityFact("blocking_semantics", UNSUPPORTED,
                           "docs/design/harness-configuration/"
                           "classification.md:52 (§四.4: hook 失败不阻断;"
                           " observational only, enforcement inexpressible)"),
        HookCapabilityFact("load_evidence", UNKNOWN,
                           "plugins/harness/src/ordessa_harness/codex/"
                           "hooks.py:16 (a session-start recording helper"
                           " exists in the pinned closure, but no managed-"
                           "hook load observation exists; cell stays"
                           " unknown)"))),
    "claude": _statement("claude", (
        HookCapabilityFact("native_slot", SUPPORTED,
                           f"{TOML}:117-120 (Order 59 stage A: settings.json"
                           " hooks key, PreToolUse 108 refs);"
                           " docs/design/harness-configuration/"
                           "source-index.json:552 (claude config"
                           " extraction carries the bare hooks key only)"),
        HookCapabilityFact("projection_path", UNSUPPORTED, _RUNTIME_GAP),
        HookCapabilityFact("blocking_semantics", UNSUPPORTED,
                           "docs/design/harness-configuration/"
                           "classification.md:52 (§四.4; no in-repo"
                           " blocking observation for claude either)"),
        HookCapabilityFact("load_evidence", UNKNOWN, NO_EVIDENCE))),
    "pi": _statement("pi", (
        HookCapabilityFact("native_slot", UNSUPPORTED,
                           f"{TOML}:405 (pi slots = instruction/mcp/skill,"
                           " no hooks; vendor docs describe native hooks —"
                           f" {HM}:177 — but no registry slot is declared)"),
        HookCapabilityFact("projection_path", UNSUPPORTED,
                           f"{TOML}:405 (no hooks slot to target; AR-3"
                           " logged)"),
        HookCapabilityFact("blocking_semantics", UNSUPPORTED,
                           "docs/design/harness-configuration/"
                           "classification.md:52 (§四.4)"),
        HookCapabilityFact("load_evidence", UNKNOWN, NO_EVIDENCE))),
    "hermes": _statement("hermes", (
        HookCapabilityFact("native_slot", UNSUPPORTED,
                           f"{TOML}:215 (hermes slots, no hooks; gateway"
                           f" hooks dir is another mechanism, {HM}:105)"),
        HookCapabilityFact("projection_path", UNSUPPORTED,
                           f"{TOML}:215 (no hooks slot)"),
        HookCapabilityFact("blocking_semantics", UNSUPPORTED,
                           "docs/design/harness-configuration/"
                           "classification.md:52 (§四.4)"),
        HookCapabilityFact("load_evidence", UNKNOWN, NO_EVIDENCE))),
    "opencode": _statement("opencode", (
        HookCapabilityFact("native_slot", UNSUPPORTED,
                           f"{TOML}:163 (opencode slots, no hooks)"),
        HookCapabilityFact("projection_path", UNSUPPORTED,
                           f"{TOML}:163 (no hooks slot)"),
        HookCapabilityFact("blocking_semantics", UNSUPPORTED,
                           "docs/design/harness-configuration/"
                           "classification.md:52 (§四.4)"),
        HookCapabilityFact("load_evidence", UNKNOWN, NO_EVIDENCE))),
    "dsh": _statement("dsh", (
        HookCapabilityFact("native_slot", UNSUPPORTED,
                           f"{TOML}:270 (dsh slots = provider/instruction)"),
        HookCapabilityFact("projection_path", UNSUPPORTED,
                           f"{TOML}:270 (no hooks slot)"),
        HookCapabilityFact("blocking_semantics", UNSUPPORTED,
                           "docs/design/harness-configuration/"
                           "classification.md:52 (§四.4)"),
        HookCapabilityFact("load_evidence", UNKNOWN, NO_EVIDENCE))),
    "kilo": _statement("kilo", (
        HookCapabilityFact("native_slot", UNSUPPORTED,
                           f"{TOML}:357 (kilo slots = provider/instruction)"),
        HookCapabilityFact("projection_path", UNSUPPORTED,
                           f"{TOML}:357 (no hooks slot)"),
        HookCapabilityFact("blocking_semantics", UNSUPPORTED,
                           "docs/design/harness-configuration/"
                           "classification.md:52 (§四.4)"),
        HookCapabilityFact("load_evidence", UNKNOWN, NO_EVIDENCE))),
})

#: qwen is NOT in BRAND_STATEMENTS: removed by user ruling
#: (specs/016-overnight-batch/spec.md §品牌优先级 2). The removal note is
#: the row — a capability grade would imply we still serve the brand.
QWEN_REMOVAL_NOTE = (
    "qwen 已除名 (user ruling 2026-09-28, spec.md §品牌优先级 2; harness"
    " facet removal itself is PE2-8's same-tree job)")

#: Implementation dispositions per the brand priority ruling (kept apart
#: from capability cells on purpose).
IMPLEMENTATION_DISPOSITION: Mapping[str, str] = MappingProxyType({
    "codex": "implement",
    "claude": "implement",
    "pi": "ar-registered",        # native hooks documented; no registry slot
    "hermes": "phase2-design",
    "opencode": "phase2-design",
    "dsh": "phase2-design",
    "kilo": "phase2-design",
    "qwen": "removed-by-ruling",
})

#: The registry ids this domain actually builds adapters for tonight.
IMPLEMENTED_BRANDS: tuple[str, ...] = ("codex", "claude")


def statement_for(harness_id: str) -> HookSupportStatement:
    statement = BRAND_STATEMENTS.get(harness_id)
    if statement is None:
        raise KeyError(f"no hooks statement for {harness_id!r} (removed or"
                       " unregistered brands get no synthesized row here)")
    return statement


def all_brand_rows() -> tuple[str, ...]:
    """Every brand the table must account for, qwen included (its row is
    the removal note)."""
    return _BRANDS


__all__ = [
    "AXES", "BRAND_STATEMENTS", "CAPABILITY_VALUES",
    "IMPLEMENTATION_DISPOSITION", "IMPLEMENTED_BRANDS",
    "HookCapabilityFact", "HookSupportStatement", "NO_EVIDENCE",
    "QWEN_REMOVAL_NOTE", "UNKNOWN", "UNSUPPORTED", "SUPPORTED",
    "all_brand_rows", "statement_for",
]

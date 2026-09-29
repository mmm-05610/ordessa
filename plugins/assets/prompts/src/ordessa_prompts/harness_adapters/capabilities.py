"""EXT-01/EXT-05 (brand-narrowed) — the prompts three-semantic table.

Eight brands × three semantics (instruction / persona / systemReplacement),
every cell graded `supported | unsupported | unknown` WITH an in-repo
citation (or the literal `no in-repo evidence`). The grading rules are the
domain's own (docs/design/prompts/harness-adapters.md):

* `unsupported` — first-hand in-repo evidence that THIS pin/path cannot
  do it (including a design rule that refuses the semantic on the
  evidenced face);
* `unknown` — no in-repo first-hand evidence either way; vendor-doc
  mechanism listings (harness-adapters.md §2) are cited as such and
  never upgrade a cell on their own.

Implementation dispositions (user ruling 2026-09-28, spec.md §品牌优先级)
are kept SEPARATE from capability cells: pi/codex/claude implemented
tonight; hermes/opencode/dsh/kilo → phase-2 design packages; qwen
REMOVED — its row is the removal note, not a capability grade.
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

SEMANTICS = ("instruction", "persona", "systemReplacement")

HM = "docs/design/prompts/harness-adapters.md"
TOML = "plugins/harness/src/ordessa_harness/harnesses.toml"
GAP = ("plugins/harness/src/ordessa_harness/registry/schema.py:64"
       " (slots parsed; no instruction_target/instruction_key field"
       " exists in the registry schema — grep: zero instruction target"
       " declarations in harnesses.toml, zero consumers in"
       " plugins/harness/src; AR-6)")

_BRANDS = ("pi", "codex", "claude", "hermes", "opencode", "dsh", "kilo",
           "qwen")


def _check(axis: str, value: str, evidence: str) -> None:
    if not isinstance(evidence, str) or not evidence.strip():
        raise ValueError(f"{axis}: evidence must be a non-empty string")
    if evidence != NO_EVIDENCE and _CITATION.search(evidence) is None:
        raise ValueError(f"{axis}: evidence must cite repo file:line or be "
                         f"{NO_EVIDENCE!r}, got {evidence!r}")
    if value == SUPPORTED and evidence == NO_EVIDENCE:
        raise ValueError(f"{axis}: a supported claim without in-repo "
                        "evidence is refused")


@dataclass(frozen=True)
class SemanticCell:
    semantic: str
    value: str
    evidence: str
    #: the standing counterexample that keeps this cell honest (EXT-01
    #: demands 反例 per cell; empty string = none recorded).
    counterexample: str = ""

    def __post_init__(self) -> None:
        if self.semantic not in SEMANTICS:
            raise ValueError(f"unknown semantic {self.semantic!r}")
        if self.value not in CAPABILITY_VALUES:
            raise ValueError(f"{self.semantic}: value must be one of "
                             f"{CAPABILITY_VALUES}")
        _check(f"{self.semantic}", self.value, self.evidence)


@dataclass(frozen=True)
class PromptsBrandStatement:
    harness_id: str
    cells: Mapping[str, SemanticCell]

    def __post_init__(self) -> None:
        object.__setattr__(self, "cells", MappingProxyType(dict(self.cells)))
        missing = [s for s in SEMANTICS if s not in self.cells]
        if missing:
            raise ValueError(f"{self.harness_id}: missing semantics {missing}")

    def value(self, semantic: str) -> str:
        return self.cells[semantic].value


def _row(harness_id: str, cells: tuple[SemanticCell, ...]
         ) -> PromptsBrandStatement:
    return PromptsBrandStatement(
        harness_id=harness_id,
        cells={cell.semantic: cell for cell in cells})


#: instruction cells for the three implemented brands: the registry
#: declares the slot but NO target path/key anywhere (unlike skills'
#: skill_target or the hooks slot), and the append/replace routes are
#: vendor-doc listings — `unknown`, never offered tonight.
_INSTRUCTION_IMPLEMENTED = (
    "registry declares the instruction slot but no target: "
    f"{TOML}:31,107,405 (slots lists) vs {GAP}; route is vendor-doc: "
    f"{HM}:15-17")

BRAND_STATEMENTS: Mapping[str, PromptsBrandStatement] = MappingProxyType({
    "pi": _row("pi", (
        SemanticCell("instruction", UNKNOWN, _INSTRUCTION_IMPLEMENTED,
                     counterexample=(
                         f"{HM}:15 — project-level files may override the"
                         " user-level ones; a managed append cannot tell"
                         " the two baselines apart, so guessing a merge is"
                         " refused (§3)")),
        SemanticCell("persona", UNSUPPORTED,
                     f"{HM}:9 (no evidenced independent persona interface;"
                     " only a provable removable role/style layer that"
                     " keeps message roles may carry persona)",
                     counterexample=(
                         "pi exposes no native persona slot in-repo;"
                         " auto-degrading persona into a user message is"
                         " forbidden by the same rule")),
        SemanticCell("systemReplacement", UNKNOWN,
                     f"{HM}:15 (SYSTEM.md replacement is vendor-doc; the"
                     f" pinned loader's resource handling is unevidenced;"
                     f" {GAP})",
                     counterexample=(
                         "replacement must never touch host-mandatory"
                         " safety rules or project discovery (HM:7)")))),
    "codex": _row("codex", (
        SemanticCell("instruction", UNKNOWN, _INSTRUCTION_IMPLEMENTED,
                     counterexample=(
                         f"{HM}:16 — whether the current bridge passes"
                         " developer_instructions at all, and whether"
                         " thread resume re-reads it, is unevidenced")),
        SemanticCell("persona", UNSUPPORTED,
                     f"{HM}:9 (no evidenced persona interface)",
                     counterexample=(
                         "developer_instructions is an instruction append"
                         " face, not an independent persona slot — using"
                         " it as one would mislabel the semantic")),
        SemanticCell("systemReplacement", UNKNOWN,
                     f"{HM}:16 (model_instructions_file is vendor-doc;"
                     f" {GAP})",
                     counterexample=(
                         "replacement scope excludes host-mandatory safety"
                         " rules and project instruction discovery"
                         " (HM:7)")))),
    "claude": _row("claude", (
        SemanticCell("instruction", UNKNOWN, _INSTRUCTION_IMPLEMENTED,
                     counterexample=(
                         f"{HM}:17 — the SDK preset+append route needs the"
                         " ACP adapter to expose/update the option and the"
                         " fingerprint to include it; a provider-env"
                         " fingerprint probe must NOT be used as evidence")),
        SemanticCell("persona", UNSUPPORTED,
                     f"{HM}:9 (no evidenced persona interface)",
                     counterexample=(
                         "CLAUDE.md is a project-context mechanism, not a"
                         " persona slot (HM:17)")),
        SemanticCell("systemReplacement", UNKNOWN,
                     f"{HM}:17 (custom system prompt via SDK options is"
                     f" vendor-doc; {GAP})",
                     counterexample=(
                         "replacement scope excludes host-mandatory safety"
                         " rules (HM:7)")))),
    "hermes": _row("hermes", (
        SemanticCell("instruction", UNKNOWN,
                     f"{HM}:18 (SOUL identity vs session personality are"
                     f" different things); {TOML}:215 (slot, no target;"
                     f" {GAP})",
                     counterexample=(
                         "Hermes 的 HOME/SOUL 模型不可搬进平台 (HM:18):"
                         " writing project-instruction content into SOUL"
                         " or personality files would conflate instance"
                         " identity with instruction layering")),
        SemanticCell("persona", UNKNOWN,
                     f"{HM}:18 (session personality exists vendor-doc; the"
                     f" mapping ruling — prefer the session layer, never"
                     f" SOUL — is design-grade only)",
                     counterexample=(
                         "persona 优先后者、不借 persona 名义覆盖 SOUL"
                         " (HM:6): mapping a managed persona onto the SOUL"
                         " identity file is the exact conflation the ruling"
                         " refuses")),
        SemanticCell("systemReplacement", UNKNOWN, NO_EVIDENCE))),
    "opencode": _row("opencode", (
        SemanticCell("instruction", UNKNOWN,
                     f"{HM}:19 (`instructions` field + AGENTS-compatible"
                     f" discovery, merge-not-replace — vendor-doc;"
                     f" {TOML}:163 slot, no target; {GAP})",
                     counterexample=(
                         "层叠是合并非整文件替换 (HM:19): a managed"
                         " projection must never overwrite the project's"
                         " AGENTS discovery face — inject via the"
                         " instructions field only")),
        SemanticCell("persona", UNKNOWN, NO_EVIDENCE),
        SemanticCell("systemReplacement", UNKNOWN,
                     f"{HM}:19 (layer stacking is MERGE, not whole-file"
                     " replacement — a replacement claim would contradict"
                     " the documented face)",
                     counterexample=(
                         "documented merge semantics contradict a clean"
                         " systemReplacement; until disproven the cell"
                         " stays unknown, never supported")))),
    "dsh": _row("dsh", (
        SemanticCell("instruction", UNKNOWN,
                     f"{HM}:20 (agent-instructions file candidates/budget/"
                     f"root discovery — vendor-doc; {TOML}:270 slot, no"
                     f" target; {GAP})",
                     counterexample=(
                         "候选发现顺序与预算语义未核 (HM:20): a managed"
                         " file dropped outside the evidenced candidate"
                         " order may be silently ignored or crowd out user"
                         " files — phase-2 must pin discovery before"
                         " projecting")),
        SemanticCell("persona", UNKNOWN,
                     f"{HM}:20 (persona prefix/suffix is the ONLY native"
                     f" persona of the eight — vendor-doc; composition"
                     f" order + removal-restore baseline need dedicated"
                     f" counterexamples, phase-2 design)",
                     counterexample=(
                         "prefix/suffix composition must preserve the"
                         " fixed order replacement→persona→instructions"
                         " and removal must restore baseline (HM:20,"
                         " §3)")),
        SemanticCell("systemReplacement", UNKNOWN,
                     f"{HM}:20 (system-prompt/runtime context —"
                     " vendor-doc)",
                     counterexample=(
                         "runtime context 边界未核 (HM:20): a replacement"
                         " that reaches runtime context could touch more"
                         " than the base system prompt — scope must be"
                         " pinned before the cell leaves unknown")))),
    "kilo": _row("kilo", (
        SemanticCell("instruction", UNKNOWN,
                     f"{HM}:22 (instructions field, kilo.jsonc stacking —"
                     f" vendor-doc; {TOML}:357 slot, no target; {GAP})",
                     counterexample=(
                         "kilo.jsonc 用户/项目层叠与 schema 深度未核,且不再"
                         " 隐式读 OpenCode 目录 (HM:22): projecting through"
                         " an assumed OpenCode-compat path is refused until"
                         " the stacking order is pinned")),
        SemanticCell("persona", UNKNOWN, NO_EVIDENCE),
        SemanticCell("systemReplacement", UNKNOWN, NO_EVIDENCE))),
})

#: qwen is NOT in BRAND_STATEMENTS — removed by user ruling (2026-09-28,
#: spec.md §品牌优先级 2). Everything qwen (QWEN.md, context.fileName,
#: import/includeDirectories, rules files) is skipped; the harness-side
#: removal itself is PE2-8's same-tree job.
QWEN_REMOVAL_NOTE = (
    "qwen 已除名 (user ruling 2026-09-28, spec.md §品牌优先级 2): QWEN.md /"
    " context.fileName / import / includeDirectories / rules-file rows all"
    " SKIPPED, registered here line-by-line; harness facet removal is"
    " PE2-8's same-tree job")

IMPLEMENTATION_DISPOSITION: Mapping[str, str] = MappingProxyType({
    "pi": "implement",
    "codex": "implement",
    "claude": "implement",
    "hermes": "phase2-design",
    "opencode": "phase2-design",
    "dsh": "phase2-design",
    "kilo": "phase2-design",
    "qwen": "removed-by-ruling",
})

IMPLEMENTED_BRANDS: tuple[str, ...] = ("pi", "codex", "claude")


def statement_for(harness_id: str) -> PromptsBrandStatement:
    statement = BRAND_STATEMENTS.get(harness_id)
    if statement is None:
        raise KeyError(f"no prompts statement for {harness_id!r} (removed or"
                       " unregistered brands get no synthesized row)")
    return statement


def all_brand_rows() -> tuple[str, ...]:
    return _BRANDS


__all__ = ["BRAND_STATEMENTS", "CAPABILITY_VALUES",
           "IMPLEMENTATION_DISPOSITION", "IMPLEMENTED_BRANDS",
           "NO_EVIDENCE", "PromptsBrandStatement", "QWEN_REMOVAL_NOTE",
           "SEMANTICS", "SemanticCell", "UNSUPPORTED", "UNKNOWN",
           "SUPPORTED", "all_brand_rows", "statement_for"]

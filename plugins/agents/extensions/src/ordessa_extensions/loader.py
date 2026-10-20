"""EXT-3 — the load pipeline: an unapproved definition is NEVER loaded.

One boundary owns the fail-closed rule so tests and reviewers read a
single place: validate → security scan → approval gate. Every refusal is
typed and counted; the report never flattens a refusal into a skip.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from .approval import ApprovalLedger
from .definitions import ExtensionDefinitionError, HookDefinition
from .security import has_high, scan_definition


@dataclass(frozen=True)
class LoadRefusal:
    hook_id: str
    code: str
    detail: str


@dataclass(frozen=True)
class LoadReport:
    loaded: tuple[HookDefinition, ...]
    refusals: tuple[LoadRefusal, ...]


class HookLoader:
    """Validate → scan → approve-gate; the only door to "loaded"."""

    def __init__(self, ledger: ApprovalLedger) -> None:
        self._ledger = ledger

    def load(self, definitions: Sequence[HookDefinition]) -> LoadReport:
        loaded: list[HookDefinition] = []
        refusals: list[LoadRefusal] = []
        for definition in definitions:
            refusal = self._gate(definition)
            if refusal is None:
                loaded.append(definition)
            else:
                refusals.append(refusal)
        return LoadReport(loaded=tuple(loaded), refusals=tuple(refusals))

    def _gate(self, definition: HookDefinition) -> LoadRefusal | None:
        try:
            # construction already validated; re-touch to surface typed
            # errors for hand-built instances with mutated slots — any
            # validation crash is typed, never a batch-killing escape
            # (round 18)
            definition.__post_init__()
        except ExtensionDefinitionError as exc:
            return LoadRefusal(definition.hook_id, exc.code, str(exc))
        except (TypeError, ValueError) as exc:
            return LoadRefusal(definition.hook_id, "DEFINITION_INVALID",
                               f"definition slot tampered beyond the typed"
                               f" vocabulary: {exc!r}")
        if definition.action_kind == "handler":
            # the in-process handler registry does not exist tonight —
            # the route is modelled, never loadable (definitions.py
            # docstring contract, round 16)
            return LoadRefusal(
                definition.hook_id, "HANDLER_ROUTE_UNAVAILABLE",
                "no handler registry exists tonight — handler actions are"
                " modelled but never loadable; use a command action")
        findings = scan_definition(definition)
        if has_high(findings):
            worst = next(f for f in findings if f.severity == "high")
            return LoadRefusal(
                definition.hook_id, "SHELL_INJECTION_SURFACE",
                f"{worst.rule}: {worst.detail} — no approval can bless this;"
                " rewrite as a clean argv")
        if not self._ledger.matches(definition):
            state = self._ledger.state(definition.hook_id)
            return LoadRefusal(
                definition.hook_id, "NOT_APPROVED",
                f"approval state is {state!r} and does not match this exact"
                " content+pin (机制 D: 未批准定义=不装载)")
        return None


__all__ = ["HookLoader", "LoadRefusal", "LoadReport"]

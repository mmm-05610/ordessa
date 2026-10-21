"""Server-owned Decision owner: original runner, filesystem evidence, CEL engine.

The rules engine is the installed CEL provider; its absence is an explicit refusal,
never a hand-written substitute. Ask providers need explicit configuration and are
not invented here. Evidence records stay in the owner's own directory under the
locked data root; the capability's invocation and evidence-scope resolvers are the
Server's trusted mappings (no decision ACL is duplicated).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ordessa_decision import DecisionError, DecisionRunner, FilesystemEvidenceStore, load_rules_engine
from ordessa_decision.capability import build_capability
from ordessa_decision.evidence import EvidenceScope
from ordessa_decision.settings import DecisionsSettings
from ordessa_server.composition.agent_owner import AgentOwnerUnavailable
from ordessa_server.composition.invocation import ServerInvocation

#: The exact decision operations this product exposes; grants name these ids.
DECISION_OPERATIONS: "tuple[str, ...]" = (
    'decisions.validate', 'decisions.run', 'decisions.get',
    'decisions.evidence', 'decisions.query',
)


@dataclass
class ServerDecisionOwner:
    """The single retained Decision owner for this runtime."""

    evidence_root: Path
    capability: object
    engine_error: str | None = None

    def close(self) -> None:
        # The filesystem evidence store holds no open handle; nothing to close.
        return


def build_decision_owner(root: Path, *, invocation_resolver) -> ServerDecisionOwner:
    if not isinstance(root, Path) or not root.is_absolute():
        raise AgentOwnerUnavailable('explicit absolute product root required')
    evidence_root = root / 'state' / 'decisions'
    evidence_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    evidence = FilesystemEvidenceStore(evidence_root)
    engine = None
    engine_error = None
    try:
        engine = load_rules_engine('cel')
    except DecisionError as error:
        engine_error = error.code
    settings = DecisionsSettings(
        runner_factory=DecisionRunner,
        evidence=evidence,
        default_engine=engine,
        engines={'cel': engine} if engine is not None else {},
        provider=None,
    )

    def scope(invocation, operation):
        if operation not in DECISION_OPERATIONS:
            raise DecisionError('permission_denied')
        if type(invocation) is not ServerInvocation:
            raise DecisionError('permission_denied')
        return EvidenceScope('principal', invocation.owner_scope.ref)

    capability = build_capability(settings, invocation_resolver=invocation_resolver,
                                  evidence_scope_resolver=scope)
    return ServerDecisionOwner(evidence_root=evidence_root, capability=capability,
                               engine_error=engine_error)


__all__ = ["DECISION_OPERATIONS", "ServerDecisionOwner", "build_decision_owner"]

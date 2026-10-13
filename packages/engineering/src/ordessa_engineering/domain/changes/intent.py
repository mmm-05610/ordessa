"""Implementation requests bind frozen bounds; they do not grant authority."""
from dataclasses import dataclass, field, asdict
from ordessa_infrastructure.encoding import canonical_bytes
from ..approvals.scope import ACTIONS, ActionScope
from ..common.models.values import (Digest, validate_id)
from ..common.outcomes.diagnostics import (ReferenceError)
from ordessa_engineering.domain.changes.baselines import (RepositorySnapshotRef)
from ..common.mechanisms.hashing import (record_digest)
from ..common.models.values import (validate_items, ordered_unique, validate_text)
from ..reviews.requirements import ReviewRequirementTemplateRef


@dataclass(frozen=True)
class ImplementationIntentSpec:
    implementation_intent_id: str
    requested_actions: tuple[str,...]
    scope: ActionScope
    expected_baselines: tuple[RepositorySnapshotRef,...]
    acceptance_requirement_refs: tuple[ReviewRequirementTemplateRef,...]
    instruction_constraints: tuple[str,...]
    digest: Digest = field(init=False)

    def __post_init__(self):
        validate_id(self.implementation_intent_id)
        if type(self.scope) is not ActionScope or self.scope.implementation_intent_id!=self.implementation_intent_id:
            raise ReferenceError('INVALID_IMPLEMENTATION_INTENT')
        validate_items(self.requested_actions,str,nonempty=True)
        if any(action not in ACTIONS for action in self.requested_actions):
            raise ReferenceError('INVALID_IMPLEMENTATION_INTENT')
        object.__setattr__(self,'requested_actions',ordered_unique(self.requested_actions,lambda x:x, code='DUPLICATE_CHECK'))
        validate_items(self.expected_baselines,RepositorySnapshotRef,nonempty=True)
        object.__setattr__(self,'expected_baselines',ordered_unique(self.expected_baselines,lambda x:x.repository_id, code='DUPLICATE_CHECK'))
        repository_ids={r.repository_id for r in self.scope.repository_scopes}
        if (any(r.project_id!=self.scope.project_id for r in self.expected_baselines) or
                len({r.realm_id for r in self.expected_baselines})!=1 or
                {r.repository_id for r in self.expected_baselines}!=repository_ids):
            raise ReferenceError('INVALID_IMPLEMENTATION_BASELINE')
        validate_items(self.acceptance_requirement_refs,ReviewRequirementTemplateRef)
        object.__setattr__(self,'acceptance_requirement_refs',ordered_unique(self.acceptance_requirement_refs,
            lambda x:canonical_bytes(asdict(x)), code='DUPLICATE_CHECK'))
        validate_items(self.instruction_constraints,str)
        for constraint in self.instruction_constraints:
            validate_text(constraint)
        # Preserve instruction order; it is part of the requested meaning.
        object.__setattr__(self,'digest',record_digest('implementation-intent-spec',self.hash_payload()))

    def hash_payload(self):
        return {name:asdict(getattr(self,name)) if name=='scope' else
            [asdict(x) for x in getattr(self,name)] if name in {'expected_baselines','acceptance_requirement_refs'} else
            list(getattr(self,name)) if name in {'requested_actions','instruction_constraints'} else getattr(self,name)
            for name in ('implementation_intent_id','requested_actions','scope','expected_baselines',
                         'acceptance_requirement_refs','instruction_constraints')}

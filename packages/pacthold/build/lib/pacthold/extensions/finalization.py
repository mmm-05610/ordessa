"""Host-neutral orchestration for provider finalization contributions."""
from __future__ import annotations

from typing import Any, Iterable

from ..work_core.finalization import ExecutionFinalizationRequest
from ..work_core.registry import ResourceResolutionContext
from .api import FinalizationContributor


class HostFinalizationCoordinator:
    """Collect external contributions, then call Core's one finalization API."""

    def __init__(self, execution_service: Any, registry: Any,
                 contributors: Iterable[FinalizationContributor] = ()) -> None:
        self.execution = execution_service
        self.registry = registry
        self.contributors = tuple(contributors)

    def finalize(self, facts: Any, terminal_observation: Any, *, idempotency_key: str):
        by_key = {
            (getattr(item, "id", ""), contract): item
            for item in self.contributors
            for contract in getattr(item, "supported_contract_ids", ())
        }
        outputs = list(getattr(terminal_observation, "output_refs", ()))
        observations = list(getattr(terminal_observation, "resource_observations", ()))
        for contract_id, frozen_ref in facts.inputs:
            contributor = by_key.get((frozen_ref.provider, contract_id))
            if contributor is None:
                continue
            provider = self.registry.get_resource_provider(frozen_ref.provider)
            context = ResourceResolutionContext(facts.execution.id, facts.dispatch["id"] if facts.dispatch else None)
            try:
                resolved = provider.resolve(contract_id, frozen_ref, context=context)
            except TypeError as exc:
                if "context" not in str(exc):
                    raise
                resolved = provider.resolve(contract_id, frozen_ref)
            contribution = contributor.prepare_finalization(
                execution_id=facts.execution.id,
                dispatch_id=facts.dispatch["id"] if facts.dispatch else None,
                frozen_input_ref=frozen_ref, resolved_resource=resolved,
                contract_id=contract_id,
            )
            outputs.extend(contribution.output_refs)
            observations.extend(contribution.resource_observations)
        return self.execution.apply_finalization(ExecutionFinalizationRequest(
            facts.execution.id, idempotency_key, terminal_observation.projection,
            native_refs=tuple(terminal_observation.native_refs),
            output_refs=tuple(outputs), resource_observations=tuple(observations),
        ))

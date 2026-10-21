"""Trusted, process-local decision services for the capability factory."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from .definitions.values import DecisionError, job_document_bound
from .job import default_host_limits, validate_job


def _check_runner(value):
    if not hasattr(value, "run_async"):
        raise DecisionError("invalid_settings")
    return value


@dataclass(frozen=True)
class DecisionsSettings:
    """Exactly the services the capability needs; never endpoint/secret in JSON."""

    runner_factory: object
    evidence: object
    provider: object | None = None
    default_engine: object | None = None
    engines: dict = field(default_factory=dict)
    host_limits: Mapping | None = None
    job_document_max_bytes: int | None = None

    def __post_init__(self):
        job_document_bound(self.job_document_max_bytes)
        if not callable(self.runner_factory) or not hasattr(self.evidence, "put") \
                or not hasattr(self.evidence, "get"):
            raise DecisionError("invalid_settings")
        if self.default_engine is not None and not hasattr(self.default_engine, "evaluate"):
            raise DecisionError("invalid_settings")

        if self.host_limits is not None:
            if (not isinstance(self.host_limits, Mapping)
                    or set(self.host_limits) != set(default_host_limits())):
                raise DecisionError("invalid_settings")
            limits = dict(self.host_limits)
            # Reuse the job owner's absolute bounds and exact value types.
            # This validates trusted configuration only; it runs no engine.
            try:
                validate_job({
                    "spec_version": "decision-job/1", "job_id": "host-limit-check", "version": 1,
                    "input": {}, "limits": limits,
                    "steps": [{"id": "check", "type": "rules", "engine": None,
                               "when": {"fact": "input", "op": "eq", "value": {}}, "payload": {}}],
                    "result": {"from": "check", "path": []},
                }, host_limits=limits)
            except DecisionError:
                raise DecisionError("invalid_settings") from None
            object.__setattr__(self, "host_limits", MappingProxyType(limits))

    def runner(self, *, provider):
        arguments = dict(default_engine=self.default_engine,
                         engines=dict(self.engines), provider=provider)
        # Preserve existing factory calls when no host override was configured.
        if self.host_limits is not None:
            arguments["host_limits"] = dict(self.host_limits)
        if self.job_document_max_bytes is not None:
            arguments["job_document_max_bytes"] = self.job_document_max_bytes
        return _check_runner(self.runner_factory(**arguments))

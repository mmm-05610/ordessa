"""Rules engine resolution: explicit job engine > host default > refuse."""
from __future__ import annotations

from importlib.metadata import entry_points

from .definitions.values import DecisionError

ENTRY_POINT_GROUP = "ordessa.decision.rules"
DEFAULT_ALLOWLIST = frozenset({"cel"})


def _candidates():
    return {item.name: item for item in entry_points(group=ENTRY_POINT_GROUP)}


def load_rules_engine(engine_id: str, *, allowlist=None):
    """Load one allowlisted entry point; no ambient default, no fallback."""
    if type(engine_id) is not str or not engine_id:
        raise DecisionError("invalid_engine")
    allowed = DEFAULT_ALLOWLIST if allowlist is None else frozenset(allowlist)
    if engine_id not in allowed:
        raise DecisionError("engine_not_allowed")
    matches = _candidates().get(engine_id)
    if matches is None:
        raise DecisionError("engine_unavailable")
    try:
        loaded = matches.load()
    except Exception as exc:  # import failure is a refusal, never a fallback
        raise DecisionError("engine_unavailable") from exc
    factory = getattr(loaded, "build", None)
    if factory is None and callable(loaded):
        # The installed plugin publishes ``module:build``; loading the entry
        # point therefore yields the factory function itself.
        factory = loaded
    if not callable(factory):
        raise DecisionError("engine_unavailable")
    engine = factory()
    if not callable(getattr(engine, "validate", None)) or not callable(
            getattr(engine, "evaluate", None)):
        raise DecisionError("engine_unavailable")
    return engine


def resolve_engine(job_step, *, default_engine=None, loader=load_rules_engine):
    """The job may name an engine; otherwise the host default must exist."""
    engine_id = job_step.get("engine")
    if engine_id is None:
        if default_engine is None:
            raise DecisionError("engine_required")
        return default_engine, "host-default"
    return loader(engine_id), "job-explicit"

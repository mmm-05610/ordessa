"""Pure validation for a fixed Unit preparation carrier."""
from collections.abc import Mapping

from ordessa_execution_api.environment.operations import sealed_mapping
from ordessa_execution_agents.profiles.definitions.codec import decode_revision
from ordessa_units.lifecycle.unit_lifecycle import plain


def fixed_profile_plan(snapshot, context, correlation):
    """Validate and freeze a complete Profile revision and private-root context.

    This helper reads caller-provided values only. It does not consult records,
    create a Unit, acquire resources, or perform native effects.
    """
    if not isinstance(snapshot, Mapping) or not isinstance(context, Mapping):
        raise ValueError("fixed Profile snapshot and preparation context required")
    if not isinstance(correlation, Mapping):
        raise ValueError("fixed preparation correlation required")
    roots = context.get("privateRootFacts")
    if not isinstance(roots, Mapping) or not roots:
        raise ValueError("private preparation root facts required")
    frozen_snapshot = plain(snapshot)
    frozen_context = plain(context)
    frozen_correlation = plain(correlation)
    decode_revision({"ref": frozen_snapshot.get("ref"),
                     "content": frozen_snapshot.get("manifest")})
    return sealed_mapping({"profileSnapshot": frozen_snapshot,
                           "context": frozen_context,
                           "correlation": frozen_correlation})


__all__ = ["fixed_profile_plan"]

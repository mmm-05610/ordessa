"""Final composition supplies resolution and authority; Unit assembly owns IO."""
from .instance import UnitAssembly
from ordessa_units.api.manager import UnitManager


def build_unit_manager(original_manager, bindings):
    """Bind the existing factory/records owner once; import causes no effects.

    bindings.resolve_plan(spec, authorization) resolves a fixed preparation.
    bindings.authorize(action, subject, authorization) supplies the original
    InvocationContext or ConnectionGrant. This function issues neither.
    """
    return UnitManager(UnitAssembly(original_manager, bindings))

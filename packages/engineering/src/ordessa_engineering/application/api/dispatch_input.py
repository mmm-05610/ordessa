"""Public method-owned dispatch task reader over the original run bindings."""
from ..orchestration.dispatch_inputs import MethodDispatchInputs


def build_method_dispatch_inputs(method_runs, blobs, access):
    """Return a read-only task producer; no Unit or action is authorized here."""
    return MethodDispatchInputs(method_runs, blobs, access)


__all__ = ['build_method_dispatch_inputs']

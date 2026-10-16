"""Harness-internal C2 context, populated only by native owner readback.

Resource plugins never supply this object or its native facts. The public C2
context remains unchanged; the brand implementation and runtime share it.
"""
def PiLiveModelContext(*args, context_factory, **kwargs):
    """Construct the original owner context; this factory owns no new facts.

    The injected constructor must preserve the shared live-context identity
    consumed by the native compiler. A resource request cannot select it.
    """
    if not callable(context_factory):
        raise ValueError("Pi live model context factory required")
    return context_factory(*args, **kwargs)

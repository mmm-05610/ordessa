"""Exact original deployment selection, independent of kernel runtime startup."""
from typing import Any

SERVER_PRODUCT_ENTRY_POINT="ordessa.server_product"

def _resolve_product_composition() -> Any:
    """The deployment's composition, resolved once per build.

    Exactly one installed product may answer. Zero is a typed refusal — a
    bare host is a deliberate choice (`server_plugins=()`), never the
    accident of a missing package; several candidates are a refusal too.
    The composition object exposes `default_plugins(**composition_kwargs)`
    returning the plugin selection for this deployment.
    """
    from importlib import metadata

    discovered = metadata.entry_points()
    group = list(
        discovered.select(group=SERVER_PRODUCT_ENTRY_POINT)
        if hasattr(discovered, "select")
        else discovered.get(SERVER_PRODUCT_ENTRY_POINT, ())
    )
    if not group:
        raise RuntimeError(
            "SERVER_PRODUCT_MISSING: no installed product provides the "
            f"{SERVER_PRODUCT_ENTRY_POINT!r} composition; pass server_plugins=() "
            "explicitly to compose a bare host")
    if len(group) > 1:
        raise RuntimeError(
            f"SERVER_PRODUCT_AMBIGUOUS: {len(group)} products provide the "
            f"{SERVER_PRODUCT_ENTRY_POINT!r} composition")
    return group[0].load()()

"""The generic host composition root. Business composition lives in the
product package (`products/server`) and the domain plugins; nothing here
imports either."""
from ordessa_server.bootstrap.runtime import (
    SERVER_PRODUCT_ENTRY_POINT,
    DataRootOwner,
    EventNotifier,
    ServerRuntime,
    _resolve_product_composition,
    build_runtime,
)

__all__ = [
    "SERVER_PRODUCT_ENTRY_POINT", "DataRootOwner", "EventNotifier",
    "ServerRuntime", "build_runtime", "_resolve_product_composition",
]

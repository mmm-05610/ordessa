"""Business-neutral SQLite connection and generic SQL migration mechanisms.

Public entries include :func:`create_connection` with :class:`SQLiteOptions`
and the explicitly caller-configured migration registry/runner. This package
owns no business schema, source selection, repository, unit of work or second
store authority. Connections remain native and their lifecycle belongs to the
caller.
"""
from .options import SQLiteOptions, UNSET
from .sqlite import SQLiteConfigurationError, create_connection

__all__ = ["SQLiteOptions", "UNSET", "create_connection", "SQLiteConfigurationError"]

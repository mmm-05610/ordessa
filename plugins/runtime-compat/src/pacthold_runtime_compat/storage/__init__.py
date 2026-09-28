"""Product storage surface: the schema-validated ``Database`` facade.

specs/010 T009: ``Database``/``FutureSchemaError`` (the ``server_*`` product
schema and the ``PRODUCT_SCHEMA_VERSION`` chain) were relocated out of
``pacthold.storage`` into this assembly; the neutral object/secret
primitives stay kernel-owned and are re-exported so one import gives the
full product storage surface.
"""

from pacthold.storage import (
    MemorySecretStore,
    ObjectRecord,
    ObjectStore,
    SecretStore,
    WindowsDpapiSecretStore,
)

from .database import Database, FutureSchemaError, PRODUCT_SCHEMA_VERSION

__all__ = [
    "Database", "FutureSchemaError", "PRODUCT_SCHEMA_VERSION",
    "ObjectRecord", "ObjectStore",
    "MemorySecretStore", "SecretStore", "WindowsDpapiSecretStore",
]

"""Local durable storage primitives shared by hosts.

specs/010 T009: the product ``Database`` facade (schema-validated,
``server_*`` aware) lives in the compatibility assembly
(``pacthold_runtime_compat.storage``); the kernel keeps only the neutral
object/secret primitives.
"""

from .objects import ObjectStore, ObjectRecord
from .secrets import MemorySecretStore, SecretStore, WindowsDpapiSecretStore

__all__ = [
    "ObjectRecord", "ObjectStore",
    "MemorySecretStore", "SecretStore", "WindowsDpapiSecretStore",
]

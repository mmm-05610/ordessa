"""Pure byte digest mechanism. Record prefixes and projections belong to owners."""
import hashlib


def sha256(data: bytes) -> bytes:
    if type(data) is not bytes:
        raise TypeError("digest_requires_bytes")
    return hashlib.sha256(data).digest()

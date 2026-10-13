"""Domain-prefixed digest v1 over projections supplied by business owners."""
import re
from ordessa_infrastructure.encoding import canonical_bytes, sha256
from ordessa_engineering.domain.common.outcomes.diagnostics import (ReferenceError)
from ordessa_engineering.domain.common.models.values import (Digest)

def record_digest(record_type: str, payload: object) -> Digest:
    if type(record_type) is not str or not re.fullmatch(r"[a-z][a-z0-9_-]{0,127}", record_type):
        raise ReferenceError("INVALID_SCHEMA")
    try:
        encoded = canonical_bytes(payload)
    except (ValueError, TypeError, RecursionError, OverflowError):
        raise ReferenceError("INVALID_SCHEMA") from None
    return Digest("sha256", sha256(f"ordessa/{record_type}/v1\n".encode() + encoded).hex())


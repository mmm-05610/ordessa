"""One bounded byte mechanism for method and business blobs, on supplied SQL.

No connection, registry or transaction is owned here. Both adapters retain the
original eng_method_blobs table and engineering-blob locator format.
"""
import hashlib
from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.domain.common.models.refs import (BlobRef)
from ordessa_engineering.domain.common.models.values import (Digest)
from ordessa_engineering.domain.common.outcomes.diagnostics import (ReferenceError)

MAX_BLOB_BYTES = 16 * 1024 * 1024


class BlobBytesError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def object_id(authority_id, digest):
    owner = hashlib.sha256(canonical_bytes(authority_id)).hexdigest()
    return f"engineering-blob:{owner}:{digest}"


def validate_ref(authority_id, ref):
    if type(ref) is not BlobRef:
        raise BlobBytesError("REF_INVALID")
    try:
        detached = BlobRef(ref.digest, ref.byte_length, ref.media_type, ref.storage_object_id)
    except (ReferenceError, TypeError, ValueError):
        raise BlobBytesError("REF_INVALID") from None
    if detached.storage_object_id != object_id(authority_id, detached.digest.hex):
        raise BlobBytesError("REF_INVALID")
    return detached


def reference_for(authority_id, raw_bytes, expected_digest, media_type):
    if (type(raw_bytes) is not bytes or len(raw_bytes) > MAX_BLOB_BYTES
            or type(expected_digest) is not Digest
            or hashlib.sha256(raw_bytes).hexdigest() != expected_digest.hex):
        raise BlobBytesError("INVALID")
    try:
        return BlobRef(expected_digest, len(raw_bytes), media_type,
                       object_id(authority_id, expected_digest.hex))
    except (ReferenceError, TypeError, ValueError):
        raise BlobBytesError("INVALID") from None


def read_bytes(connection, authority_id, ref):
    ref = validate_ref(authority_id, ref)
    # SQL itself bounds corrupt bodies before they cross into Python.
    row = connection.execute(
        "SELECT byte_length, length(body), typeof(body), "
        "CASE WHEN typeof(body)='blob' AND length(body)<=? THEN body ELSE NULL END "
        "FROM eng_method_blobs WHERE digest=?", (MAX_BLOB_BYTES, ref.digest.hex)).fetchone()
    if row is None:
        raise BlobBytesError("NOT_FOUND")
    size, stored_size, stored_type, body = row
    if (type(size) is not int or size != ref.byte_length or stored_size != size
            or stored_type != "blob" or type(body) is not bytes or len(body) != size
            or hashlib.sha256(body).hexdigest() != ref.digest.hex):
        raise BlobBytesError("CORRUPT")
    return body


def put_bytes(connection, authority_id, ref, raw_bytes):
    ref = validate_ref(authority_id, ref)
    row = connection.execute("SELECT byte_length FROM eng_method_blobs WHERE digest=?",
                             (ref.digest.hex,)).fetchone()
    if row is None:
        connection.execute("INSERT INTO eng_method_blobs VALUES (?, ?, ?)",
                           (ref.digest.hex, ref.byte_length, raw_bytes))
    elif read_bytes(connection, authority_id, ref) != raw_bytes:
        raise BlobBytesError("CORRUPT")

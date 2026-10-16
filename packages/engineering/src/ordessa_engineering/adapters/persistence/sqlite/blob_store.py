"""Application BlobStorePort on the original Library byte authority."""
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.common.outcomes.library_failures import EngineeringError
from .engineering_library import EngineeringLibrary
from .submission_schema import SUBMISSION_SCHEMA_VERSION, SUBMISSION_DDL, IMPLEMENTATION_APPLY_DDL
from .dispatch_schema import (DISPATCH_SCHEMA_VERSION, DISPATCH_DDL,
                              WORK_DISPATCH_SCHEMA_VERSION)
from .acceptance_schema import ACCEPTANCE_SCHEMA_VERSION
from .reviewer_assignment_schema import REVIEWER_ASSIGNMENT_SCHEMA_VERSION
from .external_record_schema import EXTERNAL_RECORD_SCHEMA_VERSION
from .blob_bytes import BlobBytesError, reference_for, validate_ref, read_bytes, put_bytes
from .unit_of_work import _read_transaction


def _failure(exc):
    if isinstance(exc, BlobBytesError):
        raise ApplicationError("BLOB_" + exc.code) from None
    if isinstance(exc, EngineeringError) and exc.code == "library_commit_unknown":
        raise ApplicationError("BLOB_COMMIT_UNKNOWN", retry="reconcile") from exc
    raise ApplicationError("BLOB_STORAGE_UNAVAILABLE", retry="reconcile") from exc


class SQLiteBlobStore:
    def __init__(self, library):
        if not isinstance(library, EngineeringLibrary):
            raise ApplicationError("BLOB_AUTHORITY_REQUIRED")
        with library._read_connection():
            if library._schema_version not in {3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION}:
                raise ApplicationError("BLOB_SCHEMA_REQUIRED")
        self.library = library
        self.authority_id = library.library_id

    def put_verified(self, raw_bytes, expected_digest, media_type):
        try:
            ref = reference_for(self.authority_id, raw_bytes, expected_digest, media_type)
            # This IO port is never usable inside an application transaction.
            with self.library._read_connection() as connection:
                if connection.in_transaction:
                    raise ApplicationError("BLOB_IO_IN_BUSINESS_TX")
                with self.library.transaction() as connection:
                    put_bytes(connection, self.authority_id, ref, raw_bytes)
            return ref
        except ApplicationError:
            raise
        except Exception as exc:
            _failure(exc)

    def read_verified(self, ref):
        try:
            validate_ref(self.authority_id, ref)
            with self.library._read_connection() as connection:
                if connection.in_transaction:
                    raise ApplicationError("BLOB_IO_IN_BUSINESS_TX")
                with _read_transaction(self.library) as connection:
                    return read_bytes(connection, self.authority_id, ref)
        except ApplicationError:
            raise
        except Exception as exc:
            _failure(exc)

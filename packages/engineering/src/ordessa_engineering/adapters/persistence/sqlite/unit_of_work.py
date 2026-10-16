"""Application repositories share the original EngineeringLibrary transaction."""
from contextlib import contextmanager
import sqlite3
import threading

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.common.models.identity import (Scope)
from ordessa_engineering.domain.common.outcomes.library_failures import EngineeringError
from .engineering_library import EngineeringLibrary
from .application_schema import APPLICATION_SCHEMA_VERSION
from .review_schema import REVIEW_SCHEMA_VERSION
from .material_schema import MATERIAL_SCHEMA_VERSION
from .proposal_schema import PROPOSAL_SCHEMA_VERSION
from .authorization_schema import AUTHORIZATION_SCHEMA_VERSION
from .apply_schema import APPLY_SCHEMA_VERSION, APPLY_DDL
from .method_schema import METHOD_SCHEMA_VERSION, METHOD_DDL
from .implementation_schema import IMPLEMENTATION_SCHEMA_VERSION, IMPLEMENTATION_DDL, IMPLEMENTATION_TABLES
from .submission_repository import SQLiteSubmissionRepository
from .submission_schema import SUBMISSION_SCHEMA_VERSION, SUBMISSION_DDL, IMPLEMENTATION_APPLY_DDL
from .dispatch_schema import (DISPATCH_SCHEMA_VERSION, DISPATCH_DDL,
                              WORK_DISPATCH_SCHEMA_VERSION)
from .acceptance_schema import ACCEPTANCE_SCHEMA_VERSION
from .reviewer_assignment_schema import REVIEWER_ASSIGNMENT_SCHEMA_VERSION
from .external_record_schema import EXTERNAL_RECORD_SCHEMA_VERSION


class _RollbackOnly(Exception):
    pass


def _read_cleanup_error(library, primary):
    error = ApplicationError("TRANSACTION_UNCERTAIN", retry="reconcile")
    error.primary = primary
    try:
        library.close()
    except BaseException as close_error:
        error.close_error = close_error
    finally:
        library._closed = True
    return error


class _RepositoryAccess:
    def __init__(self, connection, scope, mode, authority_id):
        self._connection = connection
        self.scope = scope
        self.authority_id = authority_id
        self._mode = mode
        self._thread = threading.get_ident()
        self._active = True

    def check_active(self):
        if not self._active or threading.get_ident() != self._thread:
            raise ApplicationError("UOW_NOT_ACTIVE")
        try:
            active = self._connection.in_transaction
        except sqlite3.DatabaseError:
            raise ApplicationError("UOW_NOT_ACTIVE") from None
        if not active:
            raise ApplicationError("UOW_NOT_ACTIVE")

    def require_write(self):
        self.check_active()
        if self._mode != "write":
            raise ApplicationError("READ_ONLY_UOW")

    def execute(self, sql, parameters=()):
        self.check_active()
        try:
            return self._connection.execute(sql, parameters)
        except sqlite3.IntegrityError as exc:
            raise ApplicationError("STORAGE_CONSTRAINT") from exc
        except sqlite3.DatabaseError as exc:
            raise ApplicationError("STORAGE_UNAVAILABLE", retry="reconcile") from exc


@contextmanager
def _read_transaction(library):
    with library._read_connection() as connection:
        if connection.in_transaction:
            raise ApplicationError("UOW_NESTED")
        previous = connection.execute("PRAGMA query_only").fetchone()[0]
        primary = None
        try:
            # SQLite itself enforces no writes, including accidental adapter
            # SQL that bypasses the public repository require_write guard.
            connection.execute("PRAGMA query_only=ON")
            connection.execute("BEGIN")
            yield connection
            library._check_bound_state(allow_journal=True)
        except BaseException as exc:
            primary = exc
            library._rollback_failure(exc)
            raise
        else:
            try:
                connection.rollback()
            except BaseException as exc:
                primary = exc
                library._rollback_failure(exc)
                raise _read_cleanup_error(library, primary) from exc
        finally:
            if not library._closed:
                try:
                    connection.execute("PRAGMA query_only=" + str(int(previous)))
                except BaseException as cleanup:
                    raise _read_cleanup_error(library, primary) from cleanup


class SQLiteUoWFactory:
    def __init__(self, library: EngineeringLibrary):
        if not isinstance(library, EngineeringLibrary):
            raise ApplicationError("UOW_AUTHORITY_REQUIRED")
        with library._read_connection():
            if library._schema_version not in {APPLICATION_SCHEMA_VERSION, REVIEW_SCHEMA_VERSION, MATERIAL_SCHEMA_VERSION, PROPOSAL_SCHEMA_VERSION, AUTHORIZATION_SCHEMA_VERSION, APPLY_SCHEMA_VERSION, METHOD_SCHEMA_VERSION, IMPLEMENTATION_SCHEMA_VERSION, SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION}:
                raise ApplicationError("APPLICATION_SCHEMA_REQUIRED")
        self.library = library
        self.authority_id = library.library_id
        with library._lock:
            if not hasattr(library, '_read_set_guard_fences'):
                library._read_set_guard_fences = threading.local()

    @contextmanager
    def guard_read_set(self, read_set):
        """Recheck original owner reads inside every nested original UoW.

        The fence carries no state/permission authority. The actual SQLite
        transaction resolves versions before its write/COMMIT, including
        writers from another connection or process.
        """
        from ordessa_engineering.application.contracts.commands import ReadSet
        if type(read_set) is not ReadSet:
            raise ApplicationError('INVALID_ARGUMENT')
        fences = self.library._read_set_guard_fences
        previous = getattr(fences, 'values', ())
        fences.values = previous + (read_set,)
        try:
            yield
        finally:
            fences.values = previous

    def begin(self, scope: Scope, mode: str = "write"):
        if type(scope) is not Scope or type(mode) is not str or mode not in {"read", "write"}:
            raise ApplicationError("INVALID_ARGUMENT")
        return SQLiteEngineeringUoW(self.library, scope, mode)

    def begin_effect_cut(self, scope: Scope):
        """Same original authority/connection, fail-fast writable acquisition."""
        if type(scope) is not Scope:
            raise ApplicationError("INVALID_ARGUMENT")
        return SQLiteEngineeringUoW(self.library, scope, "write", effect_cut=True)


class SQLiteEngineeringUoW:
    def __init__(self, library, scope, mode, *, effect_cut=False):
        if not isinstance(library, EngineeringLibrary):
            raise ApplicationError("UOW_AUTHORITY_REQUIRED")
        if type(scope) is not Scope or type(mode) is not str or mode not in {"read", "write"}:
            raise ApplicationError("INVALID_ARGUMENT")
        self._library = library
        self.scope = scope
        self.authority_id = library.library_id
        self._mode = mode
        self._effect_cut = effect_cut
        self._manager = None
        self._access = None
        self._done = False
        self._savepoint = False
        self._poison = None

    def __enter__(self):
        if self._manager is not None or self._done:
            raise ApplicationError("UOW_REUSED")
        self._manager = self._library.transaction(nonblocking=self._effect_cut) if self._mode == "write" else _read_transaction(self._library)
        entered = False
        try:
            connection = self._manager.__enter__()
            entered = True
            self._access = _RepositoryAccess(connection, self.scope, self._mode, self.authority_id)
            from .artifact_repository import SQLiteArtifactRepository
            from .command_journal import SQLiteCommandJournal
            self.engineering = SQLiteArtifactRepository(self._access)
            self.commands = SQLiteCommandJournal(self._access)
            read_fences = getattr(self._library, '_read_set_guard_fences', None)
            for reads in getattr(read_fences, 'values', ()):
                self.engineering.check_read_set(reads)
            from .method_repository import SQLiteMethodRepository
            self._methods = SQLiteMethodRepository(self._access) if self._library._schema_version in (METHOD_SCHEMA_VERSION, IMPLEMENTATION_SCHEMA_VERSION, SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION) else None
            fences = getattr(self._library, "_method_guard_fences", None)
            for control, selection in getattr(fences, "values", ()):
                if self._methods is None:
                    raise ApplicationError("METHOD_CONTROL_SCHEMA_REQUIRED")
                self._methods.check_guard(control, selection)
            self._reviews = None
            self._proposals = None
            self._authorization = None
            if self._library._schema_version in (AUTHORIZATION_SCHEMA_VERSION, APPLY_SCHEMA_VERSION, METHOD_SCHEMA_VERSION, IMPLEMENTATION_SCHEMA_VERSION, SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION):
                from .authorization_repository import SQLiteAuthorizationRepository
                self._authorization = SQLiteAuthorizationRepository(self._access)
            if self._library._schema_version in (PROPOSAL_SCHEMA_VERSION, AUTHORIZATION_SCHEMA_VERSION, APPLY_SCHEMA_VERSION, METHOD_SCHEMA_VERSION, IMPLEMENTATION_SCHEMA_VERSION, SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION):
                from .proposal_repository import SQLiteProposalRepository
                self._proposals = SQLiteProposalRepository(self._access)
            if self._library._schema_version in (REVIEW_SCHEMA_VERSION, MATERIAL_SCHEMA_VERSION, PROPOSAL_SCHEMA_VERSION, AUTHORIZATION_SCHEMA_VERSION, APPLY_SCHEMA_VERSION, METHOD_SCHEMA_VERSION, IMPLEMENTATION_SCHEMA_VERSION, SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION):
                from .review_repository import SQLiteReviewRepository
                self._reviews = SQLiteReviewRepository(self._access)
            from .implementation_repository import SQLiteImplementationRepository
            from .dispatch_repository import SQLiteDispatchRepository, SQLiteWorkDispatchRepository
            from .workflow_transactions import _TransactionScope
            self._workflow = _TransactionScope(self._library, connection, self.scope)
            self._dispatch = SQLiteDispatchRepository(self._access) if self._library._schema_version in (DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION) else None
            # The declared-Work dispatch relation is its own relation on schema 17:
            # a declared Work has no run row, so it is never the run repository.
            self._work_dispatch = SQLiteWorkDispatchRepository(self._access) if self._library._schema_version == WORK_DISPATCH_SCHEMA_VERSION else None
            self._submissions = SQLiteSubmissionRepository(self._access) if self._library._schema_version in (SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION) else None
            self._implementation = SQLiteImplementationRepository(self._access) if self._library._schema_version in (IMPLEMENTATION_SCHEMA_VERSION, SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION) else None
            from .acceptance_repository import SQLiteAcceptanceRepository
            self._acceptance = SQLiteAcceptanceRepository(self._access) if self._library._schema_version in (ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION, EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION) else None
            from .reviewer_assignment_repository import SQLiteReviewerAssignmentRepository
            self._reviewer_assignments = (SQLiteReviewerAssignmentRepository(self._access)
                if self._library._schema_version in (REVIEWER_ASSIGNMENT_SCHEMA_VERSION,
                                                     EXTERNAL_RECORD_SCHEMA_VERSION, WORK_DISPATCH_SCHEMA_VERSION) else None)
            return self
        except BaseException as exc:
            try:
                if entered:
                    try:
                        self._manager.__exit__(type(exc), exc, exc.__traceback__)
                    except EngineeringError as cleanup:
                        code = "COMMIT_UNKNOWN" if cleanup.code == "library_rollback_failed" else "STORAGE_UNAVAILABLE"
                        raise ApplicationError(code, retry="reconcile") from cleanup
            finally:
                # Cleanup itself may fail. Leaked repository handles must
                # remain invalid and this failed UoW must never be reusable.
                if self._access is not None:
                    self._access._active = False
                self._done = True
            if isinstance(exc, EngineeringError):
                code = ("EFFECT_WRITE_BUSY" if exc.code == "library_effect_busy" else
                        "UOW_NESTED" if exc.code == "library_transaction_nested" else "STORAGE_UNAVAILABLE")
                raise ApplicationError(code) from exc
            raise

    @property
    def workflow(self):
        self._access.check_active()
        return self._workflow

    @property
    def dispatch(self):
        self._access.check_active()
        if self._dispatch is None:
            raise ApplicationError('DISPATCH_SCHEMA_REQUIRED')
        return self._dispatch

    @property
    def work_dispatch(self):
        """The declared-Work dispatch relation (schema 17), never the run one."""
        self._access.check_active()
        if self._work_dispatch is None:
            raise ApplicationError('WORK_DISPATCH_SCHEMA_REQUIRED')
        return self._work_dispatch

    @property
    def implementation(self):
        if self._access is None:
            raise ApplicationError('UOW_NOT_ACTIVE')
        self._access.check_active()
        if self._implementation is None:
            raise ApplicationError('IMPLEMENTATION_SCHEMA_REQUIRED')
        return self._implementation

    @property
    def submissions(self):
        if self._access is None:
            raise ApplicationError('UOW_NOT_ACTIVE')
        self._access.check_active()
        if self._submissions is None:
            raise ApplicationError('SUBMISSION_SCHEMA_REQUIRED')
        return self._submissions

    @property
    def acceptance(self):
        if self._access is None:
            raise ApplicationError('UOW_NOT_ACTIVE')
        self._access.check_active()
        if self._acceptance is None:
            raise ApplicationError('ACCEPTANCE_SCHEMA_REQUIRED')
        return self._acceptance

    @property
    def reviewer_assignments(self):
        if self._access is None:
            raise ApplicationError("UOW_NOT_ACTIVE")
        self._access.check_active()
        if self._reviewer_assignments is None:
            raise ApplicationError("REVIEWER_ASSIGNMENT_SCHEMA_REQUIRED")
        return self._reviewer_assignments

    @property
    def methods(self):
        if self._access is None:
            raise ApplicationError('UOW_NOT_ACTIVE')
        self._access.check_active()
        if self._methods is None:
            raise ApplicationError('METHOD_CONTROL_SCHEMA_REQUIRED')
        return self._methods

    @property
    def authorization(self):
        if self._access is None:
            raise ApplicationError('UOW_NOT_ACTIVE')
        self._access.check_active()
        if self._authorization is None:
            raise ApplicationError('AUTHORIZATION_SCHEMA_REQUIRED')
        return self._authorization

    @property
    def reviews(self):
        if self._access is None:
            raise ApplicationError("UOW_NOT_ACTIVE")
        self._access.check_active()
        if self._reviews is None:
            raise ApplicationError("REVIEW_SCHEMA_REQUIRED")
        return self._reviews

    @property
    def proposals(self):
        if self._access is None:
            raise ApplicationError('UOW_NOT_ACTIVE')
        self._access.check_active()
        if self._proposals is None:
            raise ApplicationError('PROPOSAL_SCHEMA_REQUIRED')
        return self._proposals

    def _finish(self, error=None):
        if self._done or self._access is None:
            raise ApplicationError("UOW_NOT_ACTIVE")
        if threading.get_ident() != self._access._thread:
            raise ApplicationError("UOW_NOT_ACTIVE")
        if self._savepoint:
            raise ApplicationError("UOW_SAVEPOINT_ACTIVE")
        poison = self._poison
        try:
            if error is None and poison is not None:
                self._manager.__exit__(type(poison), poison, poison.__traceback__)
                raise ApplicationError("TRANSACTION_UNCERTAIN", retry="reconcile") from poison
            if error is None:
                # Source declarations retain control through COMMIT, including
                # changes made in this same TX. Historical compiled-method
                # guards keep their existing begin-time contract.
                method_fences = getattr(self._library, "_method_guard_fences", None)
                try:
                    for control, selection in getattr(method_fences, "values", ()):
                        if control.method_ref.schema_version != 2:
                            continue
                        if self._methods is None:
                            raise ApplicationError("METHOD_CONTROL_SCHEMA_REQUIRED")
                        self._methods.check_guard(control, selection)
                except BaseException as fence_error:
                    try:
                        self._manager.__exit__(type(fence_error), fence_error,
                                               fence_error.__traceback__)
                    except EngineeringError as cleanup:
                        code = ("COMMIT_UNKNOWN" if cleanup.code == "library_rollback_failed"
                                else "STORAGE_UNAVAILABLE")
                        raise ApplicationError(code, retry="reconcile") from cleanup
                    raise
                # Reviewer assignments are security-sensitive role evidence.
                # Re-read just those owner versions in this same transaction
                # immediately before commit; other read-set kinds retain their
                # existing begin-time behavior (and may be intentionally
                # updated by the current transaction).
                from ordessa_engineering.application.contracts.commands import ReadSet
                read_fences = getattr(self._library, "_read_set_guard_fences", None)
                for guarded in getattr(read_fences, "values", ()):
                    assignment_versions = tuple(
                        item for item in guarded.versions
                        if item.kind == "unit_reviewer_assignment")
                    if assignment_versions:
                        try:
                            self.engineering.check_read_set(ReadSet(guarded.scope, assignment_versions))
                        except BaseException as fence_error:
                            # A failed final fence must roll back the current
                            # transaction and preserve the original refusal.
                            try:
                                self._manager.__exit__(type(fence_error), fence_error,
                                                       fence_error.__traceback__)
                            except EngineeringError as cleanup:
                                code = ("COMMIT_UNKNOWN" if cleanup.code == "library_rollback_failed"
                                        else "STORAGE_UNAVAILABLE")
                                raise ApplicationError(code, retry="reconcile") from cleanup
                            raise
                self._manager.__exit__(None, None, None)
            else:
                self._manager.__exit__(type(error), error, error.__traceback__)
        except EngineeringError as exc:
            if exc.code in {"library_commit_unknown", "library_rollback_failed"}:
                raise ApplicationError("COMMIT_UNKNOWN", retry="reconcile") from exc
            raise ApplicationError("STORAGE_UNAVAILABLE", retry="reconcile") from exc
        finally:
            self._done = True
            self._access._active = False

    def commit(self):
        self._finish()

    def rollback(self):
        self._finish(_RollbackOnly())

    def _poison_transaction(self, error):
        self._poison = error
        self._access._active = False

    @contextmanager
    def isolate(self):
        """Rollback refused mutations; uncertain savepoints poison the whole UoW."""
        if self._access is None:
            raise ApplicationError("UOW_NOT_ACTIVE")
        self._access.require_write()
        if self._savepoint:
            raise ApplicationError("UOW_SAVEPOINT_NESTED")
        try:
            self._access.execute("SAVEPOINT engineering_mutation")
        except BaseException as exc:
            self._poison_transaction(exc)
            raise ApplicationError("TRANSACTION_UNCERTAIN", retry="reconcile") from exc
        self._savepoint = True
        try:
            yield
        except BaseException as primary:
            try:
                self._access.execute("ROLLBACK TO engineering_mutation")
                self._access.execute("RELEASE engineering_mutation")
            except BaseException as cleanup:
                error = ApplicationError("TRANSACTION_UNCERTAIN", retry="reconcile")
                error.primary = primary
                self._poison_transaction(error)
                raise error from cleanup
            raise
        else:
            try:
                self._access.execute("RELEASE engineering_mutation")
            except BaseException as exc:
                self._poison_transaction(exc)
                raise ApplicationError("TRANSACTION_UNCERTAIN", retry="reconcile") from exc
        finally:
            self._savepoint = False

    def __exit__(self, exc_type, exc, tb):
        if not self._done:
            self._finish(exc or _RollbackOnly())
        return False

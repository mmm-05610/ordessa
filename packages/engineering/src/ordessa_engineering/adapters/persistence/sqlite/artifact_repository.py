"""Scope-bound artifact/revision persistence on the caller's SQLite UoW."""
from __future__ import annotations

import sqlite3

from ordessa_engineering.application.contracts.commands import ReadSet, ReadVersion
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.artifacts.models import (
    ARTIFACT_KINDS, MAX_RECORD_BYTES, Artifact, ArtifactRevision,
)
from ordessa_engineering.domain.artifacts.codec import decode_revision, encode_revision
from ordessa_engineering.domain.artifacts.refs import (ArtifactRevisionRef)
from ordessa_engineering.domain.common.models.values import (Digest, validate_id)
from ordessa_engineering.domain.common.models.identity import (Scope)
from ordessa_engineering.domain.common.outcomes.diagnostics import (ReferenceError)
from ordessa_engineering.domain.changes.adoption import AcceptancePlan

from .material_schema import MATERIAL_SCHEMA_VERSION
from .proposal_schema import PROPOSAL_SCHEMA_VERSION
from .authorization_schema import AUTHORIZATION_SCHEMA_VERSION
from .apply_schema import APPLY_SCHEMA_VERSION, APPLY_DDL
from .method_schema import METHOD_SCHEMA_VERSION, METHOD_DDL
from .implementation_schema import IMPLEMENTATION_SCHEMA_VERSION, IMPLEMENTATION_DDL, IMPLEMENTATION_TABLES
from .submission_schema import SUBMISSION_SCHEMA_VERSION, SUBMISSION_DDL, IMPLEMENTATION_APPLY_DDL
from .dispatch_schema import DISPATCH_SCHEMA_VERSION, DISPATCH_DDL
from .acceptance_schema import ACCEPTANCE_SCHEMA_VERSION
from .reviewer_assignment_schema import REVIEWER_ASSIGNMENT_SCHEMA_VERSION
from .material_validation import MaterialBudget
from ordessa_engineering.application.contracts.access import revision_validation_key
from ordessa_engineering.application.usecases.material_closure import verify_material

_MAX_I64 = (1 << 63) - 1


def _fail(code: str) -> None:
    raise ApplicationError(code)


class SQLiteArtifactRepository:
    """Use only the active scope/UoW access; this adapter owns no connection."""

    def __init__(self, access):
        self.access = access
        self._material_budget = MaterialBudget(access)

    def require_material_schema(self):
        self.access.check_active()
        if getattr(self.access._connection, '_ordessa_schema_version', None) not in {MATERIAL_SCHEMA_VERSION, PROPOSAL_SCHEMA_VERSION, AUTHORIZATION_SCHEMA_VERSION, APPLY_SCHEMA_VERSION, METHOD_SCHEMA_VERSION, IMPLEMENTATION_SCHEMA_VERSION, SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION}:
            _fail('MATERIAL_SCHEMA_REQUIRED')

    def create(self, artifact: Artifact) -> None:
        self._material_budget = MaterialBudget(self.access)
        self.access.require_write()
        scope = self._scope()
        if type(artifact) is not Artifact:
            _fail("INVALID_ARGUMENT")
        self._validate_id(artifact.artifact_id)
        self._validate_id(artifact.kind)
        self._validate_id(artifact.created_at)
        if type(artifact.scope) is not Scope or artifact.scope != scope:
            _fail("SCOPE_MISMATCH")
        try:
            if Artifact(artifact.scope, artifact.artifact_id, artifact.kind,
                        artifact.created_at, artifact.head_revision_id,
                        artifact.version) != artifact:
                _fail("INVALID_ARGUMENT")
        except (ReferenceError, TypeError, ValueError, OverflowError):
            _fail("INVALID_ARGUMENT")
        if artifact.kind not in ARTIFACT_KINDS:
            _fail("UNSUPPORTED_ARTIFACT_KIND")
        if artifact.head_revision_id is not None or type(artifact.version) is not int or artifact.version != 0:
            _fail("INVALID_ARGUMENT")
        try:
            cursor = self.access.execute(
                "INSERT INTO eng_artifacts "
                "(realm_id, project_id, artifact_id, kind, created_at, head_revision_id, version) "
                "VALUES (?, ?, ?, ?, ?, NULL, 0)",
                (scope.realm_id, scope.project_id, artifact.artifact_id,
                 artifact.kind, artifact.created_at),
            )
        except ApplicationError as exc:
            if exc.code != "STORAGE_CONSTRAINT":
                raise
            _fail("VERSION_CONFLICT")
        if getattr(cursor, "rowcount", None) != 1:
            _fail("VERSION_CONFLICT")

    def get_artifact(self, artifact_id: str) -> Artifact:
        self._material_budget = MaterialBudget(self.access)
        scope = self._scope()
        self._validate_id(artifact_id)
        artifact = self._select_artifact(scope, artifact_id)
        if artifact is None:
            _fail("NOT_FOUND")
        return artifact

    def validated_budget(self):
        """Open a short-lived per-operation validation budget on this UoW/readset.

        The caller validates one operation against it; ``append_revision`` then
        requires that same budget to carry the validation. The next independent
        operation opens a fresh budget (per-operation accounting is preserved).
        """
        self._material_budget = MaterialBudget(self.access)
        return self._material_budget

    def apply_head_plan(self, plan):
        """Finite whole-batch CAS. Never a public single-artifact set_head."""
        from ordessa_engineering.domain.changes.application_plan import ChangeMutationPlan
        self.access.require_write()
        if getattr(self.access._connection, '_ordessa_schema_version', None) not in (APPLY_SCHEMA_VERSION, METHOD_SCHEMA_VERSION, IMPLEMENTATION_SCHEMA_VERSION, SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION):
            _fail('APPLY_SCHEMA_REQUIRED')
        if type(plan) is not ChangeMutationPlan:
            _fail('INVALID_ARGUMENT')
        scope = self._scope()
        for mutation in plan.mutations:
            target, expected = mutation.proposed_ref, mutation.expected
            if (target.realm_id, target.project_id) != (scope.realm_id, scope.project_id):
                _fail('SCOPE_MISMATCH')
            owner = self.get_artifact(expected.artifact_id)
            current = None if owner.head_revision_id is None else self._select_revision(
                scope, owner.artifact_id, owner.head_revision_id, missing_code='RECORD_CORRUPT')[0].ref
            if owner.version != expected.version or current != expected.head_ref:
                _fail('VERSION_CONFLICT')
            graph = self.resolve_graph((target,), budget=self.validated_budget())
            if current is not None and current not in {r.ref for r in graph}:
                _fail('BASE_NOT_ANCESTOR')
        for mutation in plan.mutations:
            expected = mutation.expected
            cursor = self.access.execute(
                'UPDATE eng_artifacts SET head_revision_id=?,version=version+1 '
                'WHERE realm_id=? AND project_id=? AND artifact_id=? AND version=? AND head_revision_id IS ?',
                (mutation.proposed_ref.revision_id, scope.realm_id, scope.project_id,
                 expected.artifact_id, expected.version,
                 None if expected.head_ref is None else expected.head_ref.revision_id))
            if cursor.rowcount != 1:
                _fail('VERSION_CONFLICT')

    def apply_acceptance_plan(self, plan):
        """Verify exact accepted material and optionally adopt it atomically.

        This owner remains distinct from ChangeMutationPlan: reference use
        validates CAS and material without changing heads; adopt_content also
        requires each current head in the target's parent closure.
        """
        self.access.require_write()
        if getattr(self.access._connection, '_ordessa_schema_version', None) not in (ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION):
            _fail('ACCEPTANCE_SCHEMA_REQUIRED')
        if type(plan) is not AcceptancePlan or plan.scope != self._scope():
            _fail('INVALID_ACCEPTANCE_PLAN')
        checked = []
        for target in plan.targets:
            expectation = target.expected
            artifact = self._select_artifact(plan.scope, target.target_ref.artifact_id)
            if artifact is None:
                _fail('NOT_FOUND')
            if artifact.version != expectation.version:
                _fail('VERSION_CONFLICT')
            current_ref = None
            if artifact.head_revision_id is not None:
                selected = self._select_revision(plan.scope, artifact.artifact_id,
                                                 artifact.head_revision_id)
                if selected is None:
                    _fail('RECORD_CORRUPT')
                current_ref = selected[0].ref
            if current_ref != expectation.head_ref:
                _fail('VERSION_CONFLICT')
            target_revision = self.resolve_revision(target.target_ref)
            if target_revision.scope != plan.scope or target_revision.ref != target.target_ref:
                _fail('RECORD_CORRUPT')
            if plan.acceptance_use == 'adopt_content':
                graph = self.resolve_graph((target.target_ref,), budget=self.validated_budget())
                if current_ref is not None and current_ref not in {item.ref for item in graph}:
                    _fail('ACCEPTANCE_TARGET_NOT_DESCENDANT')
            checked.append((expectation, target.target_ref))
        if plan.acceptance_use == 'adopt_content':
            for expectation, target_ref in checked:
                cursor = self.access.execute(
                    'UPDATE eng_artifacts SET head_revision_id=?,version=version+1 '
                    'WHERE realm_id=? AND project_id=? AND artifact_id=? AND version=? AND head_revision_id IS ?',
                    (target_ref.revision_id, plan.scope.realm_id, plan.scope.project_id,
                     expectation.artifact_id, expectation.version,
                     None if expectation.head_ref is None else expectation.head_ref.revision_id))
                if cursor.rowcount != 1:
                    _fail('VERSION_CONFLICT')
        return tuple(target.target_ref for target in plan.targets)

    def append_revision(
        self, revision: ArtifactRevision, *, expected_version: int,
    ) -> ArtifactRevisionRef:
        self.access.require_write()
        scope = self._scope()
        if type(revision) is not ArtifactRevision:
            _fail("INVALID_ARGUMENT")
        if type(expected_version) is not int or not 0 <= expected_version <= _MAX_I64:
            _fail("INVALID_ARGUMENT")
        if type(revision.scope) is not Scope or revision.scope != scope:
            _fail("SCOPE_MISMATCH")
        self._validate_id(revision.artifact_id)
        self._validate_id(revision.revision_id)
        db_version = getattr(self.access._connection, '_ordessa_schema_version', None)
        if db_version in {MATERIAL_SCHEMA_VERSION, PROPOSAL_SCHEMA_VERSION, AUTHORIZATION_SCHEMA_VERSION, APPLY_SCHEMA_VERSION, METHOD_SCHEMA_VERSION, IMPLEMENTATION_SCHEMA_VERSION, SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION}:
            if revision.schema_version != 2:
                _fail('MATERIAL_REVISION_REQUIRED')
        elif revision.schema_version != 1:
            _fail('MATERIAL_SCHEMA_REQUIRED')

        artifact = self._select_artifact(scope, revision.artifact_id)
        if artifact is None:
            _fail("NOT_FOUND")
        if artifact.kind not in ARTIFACT_KINDS:
            _fail("UNSUPPORTED_ARTIFACT_KIND")

        try:
            encoded = encode_revision(revision)
            if decode_revision(encoded) != revision:
                _fail("INVALID_ARGUMENT")
        except (ReferenceError, TypeError, ValueError, OverflowError, RecursionError):
            _fail("INVALID_ARGUMENT")

        if (revision.schema_version != 1
                and not self._material_budget.is_validated(revision_validation_key(revision))):
            _fail('MATERIAL_VALIDATION_REQUIRED')

        # A replay is recognized before the version CAS. It returns the
        # original immutable identity and never increments artifact.version.
        existing = self._select_revision_by_id(scope, revision.revision_id)
        if existing is not None:
            existing_artifact_id, existing_record, existing_bytes = existing
            if existing_artifact_id != revision.artifact_id or existing_bytes != encoded:
                _fail("REVISION_IDENTITY_CONFLICT")
            self._verify_parent_closure(scope, revision.artifact_id,
                                        existing_record.parent_revision_refs,
                                        missing_code="RECORD_CORRUPT")
            return existing_record.ref

        if artifact.version != expected_version:
            _fail("VERSION_CONFLICT")
        if artifact.version == _MAX_I64:
            _fail("VERSION_EXHAUSTED")
        self._verify_parent_closure(scope, revision.artifact_id,
                                    revision.parent_revision_refs,
                                    missing_code="NOT_FOUND")

        try:
            cursor = self.access.execute(
                "INSERT INTO eng_artifact_revisions "
                "(realm_id, project_id, revision_id, artifact_id, digest, schema_version, canonical_bytes) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (scope.realm_id, scope.project_id, revision.revision_id,
                 revision.artifact_id, revision.digest.hex, revision.schema_version, encoded),
            )
            if getattr(cursor, "rowcount", None) != 1:
                _fail("VERSION_CONFLICT")
            for parent in revision.parent_revision_refs:
                self.access.execute(
                    "INSERT INTO eng_revision_parents "
                    "(realm_id, project_id, artifact_id, revision_id, parent_revision_id) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (scope.realm_id, scope.project_id, revision.artifact_id,
                     revision.revision_id, parent.revision_id),
                )
            cursor = self.access.execute(
                "UPDATE eng_artifacts SET version=version+1 "
                "WHERE realm_id=? AND project_id=? AND artifact_id=? AND version=?",
                (scope.realm_id, scope.project_id, revision.artifact_id, expected_version),
            )
        except ApplicationError as exc:
            if exc.code != "STORAGE_CONSTRAINT":
                raise
            _fail("VERSION_CONFLICT")
        if getattr(cursor, "rowcount", None) != 1:
            _fail("VERSION_CONFLICT")

        stored = self._select_revision(scope, revision.artifact_id, revision.revision_id)
        if stored is None or stored[1] != encoded:
            _fail("RECORD_CORRUPT")
        return stored[0].ref

    def resolve_revision(self, ref: ArtifactRevisionRef) -> ArtifactRevision:
        self._material_budget = MaterialBudget(self.access)
        scope = self._scope()
        self._validate_ref(ref, scope)
        resolved = self._select_revision(scope, ref.artifact_id, ref.revision_id)
        if resolved is None:
            _fail("NOT_FOUND")
        record, _ = resolved
        if record.ref != ref:
            _fail("RECORD_CORRUPT")
        self._verify_parent_closure(scope, ref.artifact_id,
                                    record.parent_revision_refs,
                                    missing_code="RECORD_CORRUPT")
        return record

    def check_read_set(self, read_set: ReadSet) -> None:
        self._material_budget = MaterialBudget(self.access)
        scope = self._scope()
        if type(read_set) is not ReadSet:
            _fail("INVALID_ARGUMENT")
        if type(read_set.scope) is not Scope or read_set.scope != scope:
            _fail("SCOPE_MISMATCH")
        if type(read_set.versions) is not tuple:
            _fail("INVALID_ARGUMENT")
        seen: set[tuple[str, str]] = set()
        for item in read_set.versions:
            if type(item) is not ReadVersion:
                _fail("INVALID_ARGUMENT")
            if type(item.kind) is not str:
                _fail("INVALID_ARGUMENT")
            if item.kind in ('proposal_control', 'change'):
                from .proposal_repository import SQLiteProposalRepository
                proposals = SQLiteProposalRepository(self.access)
                current = (proposals.control_by_digest(item.identifier)
                    if item.kind == 'proposal_control' else proposals.get_change(item.identifier))
                if current.version != item.version:
                    _fail('READ_SET_CHANGED')
                continue
            if item.kind in ('method_control', 'method_selection'):
                from .method_repository import SQLiteMethodRepository
                methods=SQLiteMethodRepository(self.access)
                if item.kind=='method_control':
                    current_version=methods.control_by_digest(item.identifier).version
                else:
                    if item.identifier!='current':
                        _fail('UNSUPPORTED_READ_KIND')
                    current_version=methods.selected().version
                if current_version!=item.version:
                    _fail('READ_SET_CHANGED')
                continue
            if item.kind == 'unit_reviewer_assignment':
                key = (item.kind, item.identifier)
                if key in seen:
                    _fail('INVALID_ARGUMENT')
                seen.add(key)
                if (getattr(self.access._connection, '_ordessa_schema_version', None)
                        != REVIEWER_ASSIGNMENT_SCHEMA_VERSION):
                    _fail('REVIEWER_ASSIGNMENT_SCHEMA_REQUIRED')
                from .reviewer_assignment_repository import SQLiteReviewerAssignmentRepository
                SQLiteReviewerAssignmentRepository(self.access).check_active_control(
                    item.identifier, item.version)
                continue
            if item.kind != "artifact":
                _fail("UNSUPPORTED_READ_KIND")
            self._validate_id(item.identifier)
            key = (item.kind, item.identifier)
            if key in seen:
                _fail("INVALID_ARGUMENT")
            seen.add(key)
            if type(item.version) is not int or not 0 <= item.version <= _MAX_I64:
                _fail("INVALID_ARGUMENT")
            expectation = item.expectation(scope)
            current = self._select_artifact(scope, expectation.object_id)
            if current is None or current.version != expectation.expected_version:
                _fail("READ_SET_CHANGED")

        if read_set.review_sets or read_set.review_controls or read_set.review_requests:
            # The same original UoW connection resolves the predicate; an old
            # schema must refuse it rather than silently ignoring expectations.
            from .review_schema import REVIEW_SCHEMA_VERSION
            if getattr(self.access._connection, "_ordessa_schema_version", None) not in {REVIEW_SCHEMA_VERSION, MATERIAL_SCHEMA_VERSION, PROPOSAL_SCHEMA_VERSION, AUTHORIZATION_SCHEMA_VERSION, APPLY_SCHEMA_VERSION, METHOD_SCHEMA_VERSION, IMPLEMENTATION_SCHEMA_VERSION, SUBMISSION_SCHEMA_VERSION, DISPATCH_SCHEMA_VERSION, ACCEPTANCE_SCHEMA_VERSION, REVIEWER_ASSIGNMENT_SCHEMA_VERSION}:
                _fail("REVIEW_SCHEMA_REQUIRED")
            from .review_repository import SQLiteReviewRepository
            SQLiteReviewRepository(self.access).check_expectations(read_set.review_sets, read_set.review_controls, read_set.review_requests)

    def resolve_graph(self, refs, *, budget=None):
        """Resolve one bounded exact closure on this same active connection."""
        if type(refs) is not tuple or len(refs)>4096:
            _fail('INVALID_ARGUMENT')
        self._material_budget=MaterialBudget(self.access) if budget is None else budget
        scope=self._scope()
        graph={}
        visiting=set()
        stack=[(ref,False) for ref in reversed(refs)]
        edges=0
        while stack:
            ref,leaving=stack.pop()
            self._validate_ref(ref,scope)
            identity=(ref.artifact_id,ref.revision_id)
            if leaving:
                visiting.remove(identity)
                continue
            edges+=1
            if edges>10000:
                _fail('ANCESTRY_LIMIT')
            if identity in visiting:
                _fail('RECORD_CORRUPT')
            if identity in graph:
                if graph[identity].ref!=ref:
                    _fail('RECORD_CORRUPT')
                continue
            cached=self._material_budget.revisions.get(identity)
            if cached is None:
                selected=self._select_revision(scope,ref.artifact_id,ref.revision_id)
                if selected is None:
                    _fail('NOT_FOUND')
                record,raw=selected
                self._material_budget.record(('revision',ref),raw)
            else:
                record=cached
            if record.ref!=ref:
                _fail('RECORD_CORRUPT')
            graph[identity]=record
            self._material_budget.revisions[identity]=record
            visiting.add(identity)
            stack.append((ref,True))
            stack.extend((parent,False) for parent in reversed(record.parent_revision_refs))
        return tuple(graph[key] for key in sorted(graph))

    def _scope(self) -> Scope:
        scope = getattr(self.access, "scope", None)
        if type(scope) is not Scope:
            _fail("SCOPE_MISMATCH")
        return scope

    @staticmethod
    def _validate_id(value: str) -> None:
        try:
            validate_id(value)
        except (ReferenceError, TypeError, ValueError):
            _fail("INVALID_ARGUMENT")

    def _validate_ref(self, ref: ArtifactRevisionRef, scope: Scope) -> None:
        if type(ref) is not ArtifactRevisionRef:
            _fail("INVALID_ARGUMENT")
        try:
            validate_id(ref.realm_id)
            validate_id(ref.project_id)
            validate_id(ref.artifact_id)
            validate_id(ref.revision_id)
        except (ReferenceError, TypeError, ValueError):
            _fail("INVALID_ARGUMENT")
        if type(ref.digest) is not Digest or ref.kind != "artifact_revision":
            _fail("INVALID_ARGUMENT")
        try:
            Digest(ref.digest.algorithm, ref.digest.hex)
        except (ReferenceError, TypeError, ValueError):
            _fail("INVALID_ARGUMENT")
        if ref.realm_id != scope.realm_id or ref.project_id != scope.project_id:
            _fail("SCOPE_MISMATCH")

    def _select_artifact(self, scope: Scope, artifact_id: str) -> Artifact | None:
        row = self.access.execute(
            "SELECT realm_id, project_id, artifact_id, kind, created_at, head_revision_id, version "
            "FROM eng_artifacts WHERE realm_id=? AND project_id=? AND artifact_id=?",
            (scope.realm_id, scope.project_id, artifact_id),
        ).fetchone()
        if row is None:
            return None
        try:
            realm_id, project_id, stored_id, kind, created_at, head_id, version = row
            if (type(realm_id) is not str or type(project_id) is not str
                    or type(stored_id) is not str or type(kind) is not str
                    or type(created_at) is not str
                    or (head_id is not None and type(head_id) is not str)
                    or type(version) is not int or not 0 <= version <= _MAX_I64
                    or (realm_id, project_id, stored_id) !=
                    (scope.realm_id, scope.project_id, artifact_id)):
                _fail("RECORD_CORRUPT")
            artifact = Artifact(Scope(realm_id, project_id), stored_id, kind,
                                created_at, head_id, version)
            if head_id is not None:
                current = self._select_revision(scope, artifact_id, head_id,
                                                missing_code="RECORD_CORRUPT")
                if current is None:
                    _fail("RECORD_CORRUPT")
                self._verify_parent_closure(scope, artifact_id,
                                            current[0].parent_revision_refs,
                                            missing_code="RECORD_CORRUPT")
            return artifact
        except ApplicationError:
            raise
        except (ReferenceError, TypeError, ValueError, OverflowError, RecursionError):
            _fail("RECORD_CORRUPT")

    def _select_revision_by_id(self, scope: Scope, revision_id: str):
        row = self.access.execute(
            "SELECT artifact_id FROM eng_artifact_revisions "
            "WHERE realm_id=? AND project_id=? AND revision_id=?",
            (scope.realm_id, scope.project_id, revision_id),
        ).fetchone()
        if row is None:
            return None
        if type(row[0]) is not str:
            _fail("RECORD_CORRUPT")
        selected = self._select_revision(scope, row[0], revision_id)
        if selected is None:
            _fail("RECORD_CORRUPT")
        return row[0], selected[0], selected[1]

    def _select_revision(
        self, scope: Scope, artifact_id: str, revision_id: str, *,
        missing_code: str = "NOT_FOUND",
    ):
        row = self.access.execute(
            "SELECT realm_id, project_id, revision_id, artifact_id, digest, schema_version, "
            "length(canonical_bytes), typeof(canonical_bytes), "
            "substr(canonical_bytes, 1, ?) FROM eng_artifact_revisions "
            "WHERE realm_id=? AND project_id=? AND artifact_id=? AND revision_id=?",
            (MAX_RECORD_BYTES + 1, scope.realm_id, scope.project_id, artifact_id, revision_id),
        ).fetchone()
        if row is None:
            if missing_code == "RECORD_CORRUPT":
                _fail("RECORD_CORRUPT")
            return None
        try:
            (realm_id, project_id, stored_revision_id, stored_artifact_id,
             digest_hex, schema_version, byte_length, storage_type, raw) = row
            if (type(realm_id) is not str or type(project_id) is not str
                    or type(stored_revision_id) is not str or type(stored_artifact_id) is not str
                    or type(digest_hex) is not str or type(schema_version) is not int
                    or type(byte_length) is not int or not 0 <= byte_length <= MAX_RECORD_BYTES
                    or storage_type != "blob" or type(raw) is not bytes or len(raw) != byte_length
                    or (realm_id, project_id, stored_revision_id, stored_artifact_id) !=
                    (scope.realm_id, scope.project_id, revision_id, artifact_id)):
                _fail("RECORD_CORRUPT")
            record = decode_revision(raw)
            if getattr(self.access._connection, '_ordessa_schema_version', None) == PROPOSAL_SCHEMA_VERSION:
                self._material_budget.record(('revision',record.ref),raw)
            if (record.scope != scope or record.artifact_id != artifact_id
                    or record.revision_id != revision_id or record.digest.hex != digest_hex
                    or record.schema_version != schema_version):
                _fail("RECORD_CORRUPT")
            expected_parents = tuple(parent.revision_id for parent in record.parent_revision_refs)
            parent_rows = self.access.execute(
                "SELECT parent_revision_id FROM eng_revision_parents "
                "WHERE realm_id=? AND project_id=? AND artifact_id=? AND revision_id=? "
                "ORDER BY parent_revision_id",
                (scope.realm_id, scope.project_id, artifact_id, revision_id),
            ).fetchall()
            stored_parents = tuple(item[0] for item in parent_rows)
            if (any(type(item[0]) is not str for item in parent_rows)
                    or stored_parents != tuple(sorted(expected_parents))):
                _fail("RECORD_CORRUPT")
            try:
                verify_material(record, self._material_budget)
            except ApplicationError as exc:
                if exc.code == 'MATERIAL_LIMIT':
                    raise
                raise ApplicationError('RECORD_CORRUPT') from exc
            return record, raw
        except ApplicationError:
            raise
        except (ReferenceError, TypeError, ValueError, KeyError, AttributeError,
                OverflowError, RecursionError):
            _fail("RECORD_CORRUPT")

    def _verify_parent_closure(
        self, scope: Scope, artifact_id: str,
        parents: tuple[ArtifactRevisionRef, ...], *, missing_code: str,
    ) -> None:
        if type(parents) is not tuple:
            _fail("RECORD_CORRUPT")
        visiting: set[str] = set()
        verified: set[str] = set()

        # Iterative DFS also validates long persisted histories without using
        # Python's call stack. Exhausting the explicit budget is a refusal,
        # never a partially verified success.
        stack = [(ref, True, False) for ref in reversed(parents)]
        visited_edges = 0
        total_bytes = 0
        while stack:
            ref, direct, leaving = stack.pop()
            if leaving:
                visiting.remove(ref.revision_id)
                verified.add(ref.revision_id)
                continue
            if type(ref) is not ArtifactRevisionRef:
                _fail("RECORD_CORRUPT" if not direct else "INVALID_ARGUMENT")
            visited_edges += 1
            if visited_edges > 10000 or len(stack) > 10000:
                _fail("ANCESTRY_LIMIT")
            self._validate_ref(ref, scope)
            if ref.artifact_id != artifact_id:
                _fail("SCOPE_MISMATCH")
            revision_id = ref.revision_id
            if revision_id in visiting:
                _fail("RECORD_CORRUPT")
            resolved = self._select_revision(
                scope, artifact_id, revision_id,
                missing_code=missing_code if direct else "RECORD_CORRUPT")
            if resolved is None:
                _fail(missing_code if direct else "RECORD_CORRUPT")
            record, raw = resolved
            total_bytes += len(raw)
            if total_bytes > 64 * 1024 * 1024:
                _fail("ANCESTRY_LIMIT")
            if record.ref != ref:
                _fail("RECORD_CORRUPT")
            if revision_id in verified:
                continue
            if len(verified) + len(visiting) >= 10000:
                _fail("ANCESTRY_LIMIT")
            visiting.add(revision_id)
            stack.append((ref, direct, True))
            if len(stack) + len(record.parent_revision_refs) > 10000:
                _fail("ANCESTRY_LIMIT")
            stack.extend((parent, False, False) for parent in reversed(record.parent_revision_refs))

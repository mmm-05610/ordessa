"""Deterministic, method-declared invariants over the original Engineering UoW.

These checks correlate immutable method/schema/review/submission identities.
They do not inspect source trees, tests, native effects, semantic truth, or
acceptance state.
"""
from __future__ import annotations

import base64
import hashlib
from contextlib import contextmanager
from dataclasses import asdict
from urllib.parse import urljoin

from ordessa_infrastructure.encoding import canonical_bytes

from ...contracts.errors import ApplicationError
from ...contracts.mixed_reviews import (
    CheckSourceAdmission, FrozenCheckRequest, VerifiedCheckResponse,
)
from ...contracts.reviewer_admission import CriterionAnswer
from ....domain.artifacts.codec import encode_revision
from ....domain.artifacts.method_binding import MethodRef
from ....domain.artifacts.models import MethodPayload
from ....domain.artifacts.refs import ArtifactRevisionRef
from ....domain.changes.submission_codec import encode_submission
from ....domain.changes.submission_binding import validate_submission_graph
from ....domain.common.models.refs import BlobRef
from ....domain.common.models.values import Digest
from ....domain.common.outcomes.diagnostics import ReferenceError
from ....domain.packages.models import package_payload_projection
from ....domain.reviews.models import ReviewPlan
from ....domain.reviews.refs import SubmissionRef
from ....methods.definitions.models.compiled import thaw_value
from ...orchestration.method_content import (
    document_type_for_payload, validate_document_content,
)
from ...orchestration.steps.implementation_dispatch import resolve_dispatch_submission_binding
from ..material_closure import verify_material


_SCHEMA_CHECK = 'ordessa.schema.validate'
_SUBMISSION_CHECK = 'ordessa.submission.binding'
_INTERFACE = '1.0.0'
_CONTRACT = 'ordessa.declared-invariant-review/1'
_MAX_PROOF_BYTES = 2 * 1024 * 1024


def _deny(code='REVIEW_SOURCE_INVALID'):
    raise ApplicationError(code)


def _digest(raw):
    return Digest('sha256', hashlib.sha256(raw).hexdigest())


def _method_ref(snapshot):
    ref = snapshot.ref
    return MethodRef(ref.method_id, ref.release_version, ref.schema_version,
                     Digest('sha256', ref.snapshot_digest))


def _key_sort(key):
    from ....domain.reviews.models import CheckKey
    if type(key) is not CheckKey:
        _deny()
    return key.sort_key


class DeclaredInvariantReviewCheckSource:
    """Frozen method check source using only exact original-library facts."""

    def __init__(self, factory, methods, blobs):
        if (getattr(methods, 'factory', None) is not factory
                or getattr(blobs, 'authority_id', None) != getattr(factory, 'authority_id', None)):
            _deny('REVIEW_SOURCE_AUTHORITY_MISMATCH')
        self.factory, self.methods, self.blobs = factory, methods, blobs

    @staticmethod
    def _standard(snapshot, plan):
        matches = [item for item in snapshot.program.standard_definitions
            if item.standard_id == plan.requirement.criterion_set_ref.criterion_set_id
            and item.resource_ref.sha256 == plan.requirement.criterion_set_ref.digest.hex]
        if len(matches) != 1:
            _deny('METHOD_REQUIREMENTS_CHANGED')
        return matches[0]

    @staticmethod
    def _check_definition(standard, key, capability):
        criteria = [item for item in standard.criteria if item.criterion_id == key.criterion_id]
        if len(criteria) != 1 or len(criteria[0].checks) != 1:
            _deny('REVIEW_CHECK_EXECUTION_UNAVAILABLE')
        check = criteria[0].checks[0]
        if check.capability_id != capability or check.interface_version != _INTERFACE:
            _deny('REVIEW_CHECK_EXECUTION_UNAVAILABLE')
        return criteria[0], check

    @staticmethod
    def _validate_request(plan, request, standard, check_keys):
        if (type(plan) is not ReviewPlan or type(request) is not FrozenCheckRequest
                or request.plan_digest != plan.plan_digest
                or type(check_keys) is not tuple or not check_keys
                or len(set(check_keys)) != len(check_keys)
                or not set(check_keys) <= set(plan.check_keys)
                or type(request.request_version) is not int
                or not 0 <= request.request_version <= 9007199254740991
                or type(request.fence) is not int or not 1 <= request.fence <= 9007199254740991):
            _deny()
        if (standard.standard_id != plan.requirement.criterion_set_ref.criterion_set_id
                or standard.resource_ref.sha256 != plan.requirement.criterion_set_ref.digest.hex):
            _deny('METHOD_REQUIREMENTS_CHANGED')
        for key in check_keys:
            if key not in plan.check_keys:
                _deny('REVIEW_CHECK_OUT_OF_PLAN')
            criterion = next((item for item in standard.criteria
                              if item.criterion_id == key.criterion_id), None)
            if criterion is None or len(criterion.checks) != 1:
                _deny('REVIEW_CHECK_EXECUTION_UNAVAILABLE')
            check = criterion.checks[0]
            if (check.interface_version != _INTERFACE
                    or check.capability_id not in {_SCHEMA_CHECK, _SUBMISSION_CHECK}):
                _deny('REVIEW_CHECK_EXECUTION_UNAVAILABLE')

    @staticmethod
    def _content_document(snapshot, content):
        """Resolve content type solely from its exact frozen MethodContent schema ref."""
        exact = content.schema_ref
        method = _method_ref(snapshot)
        if exact.method_ref != method:
            _deny('REVIEW_SCHEMA_METHOD_MISMATCH')
        resources = [item for item in snapshot.resources if item.resource_id == exact.resource_id]
        if (len(resources) != 1 or resources[0].logical_path != exact.logical_path
                or resources[0].digest != exact.resource_digest.hex):
            _deny('REVIEW_SCHEMA_RESOURCE_MISMATCH')
        documents = [item for item in snapshot.program.document_definitions
            if item.validation_target == 'method_content'
            and item.schema_resource.resource_id == exact.resource_id
            and item.schema_resource.sha256 == exact.resource_digest.hex]
        if len(documents) != 1:
            _deny('REVIEW_SCHEMA_DOCUMENT_TYPE_UNAVAILABLE')
        document = documents[0]
        schema = resources[0]
        # The snapshot's source bytes remain in the same original BlobStore.
        # Their identity is checked again by the active UoW below.
        value_schema = thaw_value(document.value_schema)
        location = 'https://ordessa.invalid/method/' + schema.logical_path
        schema_id = urljoin(location, value_schema.get('$id', location))
        payload = MethodPayload('application/json', schema_id, content)
        try:
            if document_type_for_payload(snapshot, payload) != document.document_type:
                _deny('REVIEW_SCHEMA_DOCUMENT_TYPE_MISMATCH')
        except ApplicationError:
            # The helper also validates the body. Exact reference and schema-id
            # checks above make a body-validation error a reportable violation;
            # resource/method mismatch errors remain refusals.
            validation = validate_document_content(snapshot, document.document_type,
                {'value': content.value})
            if validation.ok:
                raise
        return document, schema

    @staticmethod
    def _schema_binding(snapshot,standard,key,document_type):
        _,check=DeclaredInvariantReviewCheckSource._check_definition(standard,key,_SCHEMA_CHECK)
        bindings=thaw_value(check.bindings)
        if type(bindings) is not dict:
            _deny('REVIEW_SCHEMA_BINDING_INVALID')
        def exact(value,kind):
            if type(value) is not dict or set(value)!={'resource_id','sha256','kind'} or value['kind']!=kind:
                _deny('REVIEW_SCHEMA_BINDING_INVALID')
            resources=[r for r in snapshot.resources if r.resource_id==value['resource_id'] and r.digest==value['sha256']]
            if len(resources)!=1:
                _deny('REVIEW_SCHEMA_BINDING_UNAVAILABLE')
            return value['resource_id']
        if set(bindings)=={'schema'}:
            return exact(bindings['schema'],'document_schema')
        if set(bindings)=={'schema_by_document_type'}:
            table=bindings['schema_by_document_type']
            if type(table) is not dict or not table:
                _deny('REVIEW_SCHEMA_BINDING_INVALID')
            for frozen_type,value in table.items():
                exact(value,'document_schema')
                documents=[d for d in snapshot.program.document_definitions if d.document_type==frozen_type]
                if len(documents)!=1 or asdict(documents[0].schema_resource)!=value:
                    _deny('REVIEW_SCHEMA_BINDING_INVALID')
            if document_type not in table:
                _deny('REVIEW_SCHEMA_BINDING_UNAVAILABLE')
            return exact(table[document_type],'document_schema')
        _deny('REVIEW_SCHEMA_BINDING_INVALID')

    def _schema_answer(self, uow, snapshot, standard, key):
        target = key.target.ref
        revision = None
        content = None
        submission_bytes = None
        if type(target) is ArtifactRevisionRef:
            if (target.realm_id, target.project_id) != (uow.scope.realm_id, uow.scope.project_id):
                _deny('SCOPE_MISMATCH')
            revision = uow.engineering.resolve_revision(target)
            if revision.scope != uow.scope or revision.ref != target:
                _deny('REVIEW_SUBJECT_BINDING_MISMATCH')
            if revision.schema_version != 2:
                _deny('REVIEW_MATERIAL_SCHEMA_REQUIRED')
            verify_material(revision, uow.engineering.validated_budget())
            if type(revision.payload) is not MethodPayload:
                return CriterionAnswer(key, 'insufficient', (target,),
                    'The exact target has no MethodContent payload; no schema pass is inferred.'), {
                        'target_ref': asdict(target), 'status': 'insufficient',
                        'reason': 'METHOD_CONTENT_UNAVAILABLE'}
            content = revision.payload.content
        elif type(target) is SubmissionRef:
            record = uow.submissions.resolve(target)
            if record.scope != uow.scope or record.ref != target:
                _deny('REVIEW_SUBJECT_BINDING_MISMATCH')
            if record.method_content is None:
                return CriterionAnswer(key, 'insufficient', (),
                    'The exact Submission has no MethodContent; no schema pass is inferred.'), {
                        'target_ref': asdict(target), 'submission_digest': record.digest.hex,
                        'status': 'insufficient', 'reason': 'METHOD_CONTENT_UNAVAILABLE'}
            content = record.method_content
            submission_bytes = encode_submission(record)
        else:
            return CriterionAnswer(key, 'insufficient', (),
                'This target type has no declared MethodContent reader; no schema pass is inferred.'), {
                    'target_ref': asdict(key.target), 'status': 'insufficient',
                    'reason': 'METHOD_CONTENT_OWNER_UNAVAILABLE'}

        document, schema_resource = self._content_document(snapshot, content)
        expected_resource_id = self._schema_binding(snapshot, standard, key, document.document_type)
        if expected_resource_id != document.schema_resource.resource_id:
            return CriterionAnswer(key, 'violated', () if revision is None else (target,),
                'The exact MethodContent schema differs from the frozen check binding.'), {
                    'target_ref': asdict(target), 'schema_ref': asdict(content.schema_ref),
                    'document_type': document.document_type, 'status': 'violated',
                    'reason': 'FROZEN_SCHEMA_BINDING_MISMATCH'}
        method_blob = schema_resource.blob_ref
        content_ref = BlobRef(Digest('sha256',method_blob.digest), method_blob.byte_length,
            method_blob.media_type, method_blob.storage_object_id)
        raw_schema = uow.implementation.read_blob(content_ref)
        if (type(raw_schema) is not bytes or hashlib.sha256(raw_schema).hexdigest()
                != schema_resource.digest or len(raw_schema) != schema_resource.byte_length):
            _deny('REVIEW_SCHEMA_BYTES_MISMATCH')
        validation = validate_document_content(snapshot, document.document_type,
            {'value': content.value})
        status = 'satisfied' if validation.ok else 'violated'
        answer = CriterionAnswer(key, status, () if revision is None else (target,),
            'Exact frozen schema resource and original MethodContent body were validated.'
            if validation.ok else 'The exact MethodContent body violates its frozen method schema: '
            + validation.error.code)
        evidence = {'target_ref': asdict(target), 'submission_bytes': None if submission_bytes is None
                else base64.b64encode(submission_bytes).decode('ascii'),
            'revision_bytes': None if revision is None else base64.b64encode(encode_revision(revision)).decode('ascii'),
            'schema_ref': asdict(content.schema_ref), 'schema_resource_ref': asdict(schema_resource),
            'schema_bytes': base64.b64encode(raw_schema).decode('ascii'),
            'schema_digest': hashlib.sha256(raw_schema).hexdigest(),
            'document_type': document.document_type,
            'method_content_bytes': base64.b64encode(content.value_bytes).decode('ascii'),
            'method_content_digest': hashlib.sha256(content.value_bytes).hexdigest(),
            'status': status, 'validation_error': None if validation.ok else validation.error.code}
        return answer, evidence

    @staticmethod
    def _submission_answer(uow, snapshot, plan, standard, key):
        _, check = DeclaredInvariantReviewCheckSource._check_definition(
            standard, key, _SUBMISSION_CHECK)
        bindings = thaw_value(check.bindings)
        if bindings != {}:
            _deny('REVIEW_SUBMISSION_BINDING_INVALID')
        target = key.target.ref
        if type(target) is not SubmissionRef or (target.realm_id, target.project_id) != (
                uow.scope.realm_id, uow.scope.project_id):
            return CriterionAnswer(key, 'insufficient', (),
                'The exact target is not a same-scope Submission; no binding pass is inferred.'), {
                    'target_ref': asdict(key.target), 'status': 'insufficient',
                    'reason': 'SUBMISSION_TARGET_UNAVAILABLE'}
        record = uow.submissions.resolve(target)
        if record.scope != uow.scope or record.ref != target:
            _deny('REVIEW_SUBMISSION_BINDING_MISMATCH')
        package = uow.implementation.resolve_package(record.package_ref)
        if package.ref != record.package_ref or package.scope != uow.scope:
            _deny('REVIEW_SUBMISSION_BINDING_MISMATCH')
        if package.payload.method_ref != plan.requirement.method_ref:
            _deny('REVIEW_SUBMISSION_METHOD_MISMATCH')
        if type(record.authorization_refs) is not tuple or len(record.authorization_refs) != 1:
            _deny('REVIEW_SUBMISSION_GRANT_MISMATCH')
        grant_ref, = record.authorization_refs
        grant = uow.authorization.get_grant(grant_ref)
        control = uow.authorization.get_control(grant_ref)
        if (grant.ref != grant_ref or grant.intent.method_ref != plan.requirement.method_ref
                or package.payload.authorization_refs != (grant_ref,)):
            _deny('REVIEW_SUBMISSION_GRANT_MISMATCH')
        before = tuple(uow.implementation.resolve_repository_baseline(ref)
                       for ref in record.baseline_snapshots)
        resulting = tuple(uow.implementation.resolve_repository_baseline(ref)
                          for ref in record.resulting_snapshots)
        graph_error = None
        try:
            validate_submission_graph(record, package, grant, before, resulting)
        except ReferenceError as exc:
            graph_error = getattr(exc, 'code', str(exc))
        output_facts = []
        for ref in record.output_refs:
            if type(ref) is ArtifactRevisionRef:
                revision = uow.engineering.resolve_revision(ref)
                if revision.ref != ref or revision.scope != uow.scope:
                    _deny('REVIEW_SUBMISSION_OUTPUT_MISMATCH')
                verify_material(revision, uow.engineering.validated_budget())
                output_facts.append({'ref': asdict(ref), 'digest': revision.digest.hex})
            elif type(ref) is BlobRef:
                raw = uow.implementation.read_blob(ref)
                if len(raw) != ref.byte_length or hashlib.sha256(raw).hexdigest() != ref.digest.hex:
                    _deny('REVIEW_SUBMISSION_OUTPUT_MISMATCH')
                output_facts.append({'ref': asdict(ref), 'digest': hashlib.sha256(raw).hexdigest()})
            else:
                _deny('REVIEW_SUBMISSION_OUTPUT_MISMATCH')
        dispatch = resolve_dispatch_submission_binding(uow, record)
        if dispatch.package_ref != package.ref or dispatch.approval_ref != grant_ref:
            _deny('REVIEW_SUBMISSION_DISPATCH_MISMATCH')
        if graph_error is None:
            answer = CriterionAnswer(key, 'satisfied', (),
                'Original package, grant, baseline/output, and native dispatch references correlate. '
                'This does not establish code, tree, test, effect truth, or acceptance.')
            status = 'satisfied'
        else:
            answer = CriterionAnswer(key, 'violated', (),
                'The original Submission graph does not match its package, grant, baselines, or outputs: '
                + graph_error)
            status = 'violated'
        evidence = {'target_ref': asdict(target), 'submission_bytes': base64.b64encode(
                encode_submission(record)).decode('ascii'), 'submission_digest': record.digest.hex,
            'package_bytes': base64.b64encode(canonical_bytes(package_payload_projection(
                package.payload, identity=True))).decode('ascii'), 'package_ref': asdict(package.ref),
            'grant_ref': asdict(grant.ref), 'grant_digest': grant.ref.grant_digest.hex,
            'grant_control_state': control['state'], 'grant_control_version': control['version'],
            'method_ref': asdict(package.payload.method_ref),
            'baselines': [{'ref': asdict(item.ref), 'files': [asdict(f) for f in item.files]}
                          for item in before],
            'resulting_snapshots': [{'ref': asdict(item.ref), 'files': [asdict(f) for f in item.files]}
                                    for item in resulting],
            'outputs': output_facts, 'dispatch_binding_digest': asdict(dispatch.digest),
            'dispatch_phase': uow.dispatch.by_operation(record.execution_ref.operation_ref,
                uow.scope)['dispatch_phase'], 'graph_error': graph_error, 'status': status,
            'accepted': False}
        return answer, evidence

    def _proof(self, context, plan, request, standard, check_keys, snapshot):
        if plan.scope != context.scope:
            _deny('SCOPE_MISMATCH')
        self._validate_request(plan, request, standard, check_keys)
        if _method_ref(snapshot) != plan.requirement.method_ref:
            _deny('METHOD_REQUIREMENTS_CHANGED')
        answers, evidence = [], []
        with self.factory.begin(context.scope, 'read') as uow:
            for key in sorted(check_keys, key=_key_sort):
                criterion = next(item for item in standard.criteria
                                 if item.criterion_id == key.criterion_id)
                check = criterion.checks[0]
                if check.capability_id == _SCHEMA_CHECK:
                    answer, facts = self._schema_answer(uow, snapshot, standard, key)
                elif check.capability_id == _SUBMISSION_CHECK:
                    answer, facts = self._submission_answer(uow, snapshot, plan, standard, key)
                else:
                    _deny('REVIEW_CHECK_EXECUTION_UNAVAILABLE')
                answers.append(answer)
                evidence.append({'check_key': asdict(key), 'capability_id': check.capability_id,
                                 'bindings': thaw_value(check.bindings), 'facts': facts})
        proof = canonical_bytes({'contract': _CONTRACT, 'plan_digest': asdict(plan.plan_digest),
            'request': asdict(request), 'standard': {'id': standard.standard_id,
            'resource_digest': standard.resource_ref.sha256},
            'check_keys': [asdict(key) for key in sorted(check_keys, key=_key_sort)],
            'answers': [asdict(answer) for answer in answers], 'evidence': evidence})
        if len(proof) > _MAX_PROOF_BYTES:
            _deny('REVIEW_MATERIAL_LIMIT')
        return proof, tuple(answers)

    def capture_proof(self, context, plan, request, *, standard, check_keys):
        with self.methods.guard_method(context, plan.requirement.method_ref) as snapshot:
            exact = self._standard(snapshot, plan)
            if exact != standard:
                _deny('METHOD_REQUIREMENTS_CHANGED')
            raw, _ = self._proof(context, plan, request, exact, check_keys, snapshot)
        return self.blobs.put_verified(raw, _digest(raw),
            'application/vnd.ordessa.declared-invariant-proof+json')

    def verify_checks(self, context, plan, request, raw_response_ref, *, standard, check_keys):
        if type(raw_response_ref) is not BlobRef:
            _deny()
        try:
            stored = self.blobs.read_verified(raw_response_ref)
        except (OSError, ValueError, TypeError):
            _deny('REVIEW_SOURCE_BYTES_MISMATCH')
        with self.methods.guard_method(context, plan.requirement.method_ref) as snapshot:
            exact = self._standard(snapshot, plan)
            if exact != standard:
                _deny('METHOD_REQUIREMENTS_CHANGED')
            expected, answers = self._proof(context, plan, request, exact, check_keys, snapshot)
        if stored != expected:
            _deny('REVIEW_SOURCE_PROOF_CHANGED')
        return VerifiedCheckResponse(answers, _digest(expected))

    @contextmanager
    def guard_checks(self, context, admissions):
        if (type(admissions) is not tuple or not admissions
                or any(type(item) is not CheckSourceAdmission for item in admissions)):
            _deny()
        method_refs = {item.plan.requirement.method_ref for item in admissions}
        if len(method_refs) != 1:
            _deny('REVIEW_SOURCE_INVALID')
        with self.methods.guard_method(context, next(iter(method_refs))) as snapshot:
            for item in admissions:
                standard = self._standard(snapshot, item.plan)
                expected, answers = self._proof(context, item.plan, item.request,
                    standard, item.check_keys, snapshot)
                if (self.blobs.read_verified(item.raw_response_ref) != expected
                        or answers != item.response.answers
                        or _digest(expected) != item.response.provenance_digest):
                    _deny('REVIEW_SOURCE_PROOF_CHANGED')
            yield

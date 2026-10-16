"""Mechanical provenance checks over the original Engineering material owner.

These checks establish byte and reference integrity only. They do not decide
whether source text semantically supports a claim or whether content is complete.
"""
from __future__ import annotations

import base64
import hashlib
from contextlib import contextmanager
from dataclasses import asdict

from ordessa_infrastructure.encoding import canonical_bytes
from ...contracts.errors import ApplicationError
from ...contracts.mixed_reviews import FrozenCheckRequest, VerifiedCheckResponse
from ...contracts.reviewer_admission import CriterionAnswer
from ....domain.artifacts.codec import encode_revision
from ....domain.artifacts.models import BlobPayload, MethodPayload
from ....domain.artifacts.provenance import ExcerptCapture
from ....domain.artifacts.refs import ArtifactRevisionRef
from ....domain.common.models.refs import BlobRef
from ....domain.common.models.values import Digest
from ....domain.reviews.models import CheckKey, ReviewPlan
from ..material_closure import verify_material

_CONTRACT = 'ordessa.mechanical-review-proof/1'
_MAX_PROOF_BYTES = 2 * 1024 * 1024
_CAPABILITIES = {'ordessa.sources.integrity', 'ordessa.claims.coverage'}
_INTERFACE = '1.0.0'


def _deny(code='REVIEW_SOURCE_INVALID'):
    raise ApplicationError(code)


def _ref_projection(ref):
    return asdict(ref)


class MechanicalReviewCheckSource:
    """Original-library mechanical source; no user, role, or semantic authority."""

    def __init__(self, factory, method_control, blobs):
        if (getattr(method_control, 'factory', None) is not factory
                or getattr(blobs, 'authority_id', None) != getattr(factory, 'authority_id', None)):
            _deny('REVIEW_SOURCE_AUTHORITY_MISMATCH')
        self.factory, self.methods, self.blobs = factory, method_control, blobs

    @staticmethod
    def _validate(plan, request, standard, check_keys):
        if (type(plan) is not ReviewPlan or type(request) is not FrozenCheckRequest
                or request.plan_digest != plan.plan_digest
                or type(check_keys) is not tuple or not check_keys
                or len(set(check_keys)) != len(check_keys) or not set(check_keys) <= set(plan.check_keys)
                or type(request.request_version) is not int or not 0 <= request.request_version <= 9007199254740991
                or type(request.fence) is not int or not 1 <= request.fence <= 9007199254740991):
            _deny()
        if (getattr(standard, 'standard_id', None) != plan.requirement.criterion_set_ref.criterion_set_id
                or getattr(getattr(standard, 'resource_ref', None), 'sha256', None)
                != plan.requirement.criterion_set_ref.digest.hex):
            _deny('METHOD_REQUIREMENTS_CHANGED')
        criteria = {item.criterion_id: item for item in getattr(standard, 'criteria', ())}
        for key in check_keys:
            criterion = criteria.get(key.criterion_id)
            checks = getattr(criterion, 'checks', ()) if criterion is not None else ()
            if len(checks) != 1 or checks[0].capability_id not in _CAPABILITIES or checks[0].interface_version != _INTERFACE:
                _deny('REVIEW_CHECK_EXECUTION_UNAVAILABLE')

    @staticmethod
    def _standard(snapshot, plan):
        matches = [item for item in snapshot.program.standard_definitions
            if item.standard_id == plan.requirement.criterion_set_ref.criterion_set_id
            and item.resource_ref.sha256 == plan.requirement.criterion_set_ref.digest.hex]
        if len(matches) != 1:
            _deny('METHOD_REQUIREMENTS_CHANGED')
        return matches[0]

    def _proof(self, context, plan, request, standard, check_keys):
        if plan.scope != context.scope:
            _deny('SCOPE_MISMATCH')
        self._validate(plan, request, standard, check_keys)
        answers = []
        evidence = []
        with self.factory.begin(context.scope, 'read') as uow:
            budget = uow.engineering.validated_budget()
            for key in sorted(check_keys, key=lambda item: item.sort_key):
                if type(key.target.ref) is not ArtifactRevisionRef:
                    _deny('REVIEW_SUBJECT_OWNER_UNAVAILABLE')
                ref = key.target.ref
                revision = uow.engineering.resolve_revision(ref)
                if revision.scope != context.scope or revision.ref != ref:
                    _deny('REVIEW_SUBJECT_BINDING_MISMATCH')
                if revision.schema_version != 2:
                    _deny('REVIEW_MATERIAL_SCHEMA_REQUIRED')
                verify_material(revision, budget)

                material_inputs = []
                payload = revision.payload
                if type(payload) is BlobPayload:
                    material_inputs.append(self._bytes_input('payload', payload.blob_ref, budget.read(payload.blob_ref)))
                elif type(payload) is MethodPayload and payload.content.rendered_body_ref is not None:
                    r = payload.content.rendered_body_ref
                    material_inputs.append(self._bytes_input('rendered_body', r, budget.read(r)))
                for source in revision.sources:
                    if type(source.capture) is ExcerptCapture:
                        raw = budget.read(source.capture.blob_ref)
                        selected = budget.selectors.check(raw, source.capture.selector, source.capture.excerpt_digest)
                        material_inputs.append(self._bytes_input('source:' + source.source_id, source.capture.blob_ref, raw,
                            selector=asdict(source.capture.selector), selected_digest=hashlib.sha256(selected).hexdigest(),
                            selected_bytes=base64.b64encode(selected).decode('ascii')))
                claim_ids = [claim.claim_id for claim in revision.claims]
                all_links = list(revision.evidence_links)
                links = [link for link in all_links if link.claim_id == key.claim_id]
                cap = next(item for item in standard.criteria if item.criterion_id == key.criterion_id).checks[0].capability_id
                if cap == 'ordessa.sources.integrity':
                    status = 'satisfied' if revision.sources and material_inputs else 'insufficient'
                    rationale = ('Exact revision and captured source bytes passed digest/selector checks.' if status == 'satisfied'
                                 else 'No captured source bytes were available for mechanical integrity checking.')
                else:
                    # Non-iterated coverage checks refer to the entire formal
                    # claim set, not a fictitious claim whose id is None.
                    required = tuple(c for c in revision.claims
                                     if key.claim_id is None or c.claim_id == key.claim_id)
                    complete = bool(required) and all(any(link.claim_id == c.claim_id
                                     for link in all_links) for c in required)
                    status = 'unknown' if complete else 'insufficient'
                    rationale = ('Claim and evidence-link chain is mechanically present; semantic support remains unknown.'
                                 if status == 'unknown' else 'The target has no complete claim-to-source evidence-link chain.')
                answers.append(CriterionAnswer(key, status, (ref,), rationale))
                evidence.append({'check_key': asdict(key), 'target_ref': _ref_projection(ref),
                    'revision_bytes': base64.b64encode(encode_revision(revision)).decode('ascii'),
                    'revision_digest': revision.digest.hex, 'claim_ids': claim_ids,
                    'links': [asdict(link) for link in all_links],
                    'check_claim_links': [asdict(link) for link in links], 'material_inputs': material_inputs,
                    'status': status})
        proof = canonical_bytes({'contract': _CONTRACT, 'plan_digest': asdict(plan.plan_digest),
            'request': asdict(request), 'standard': {'id': standard.standard_id,
            'resource_digest': standard.resource_ref.sha256},
            'check_keys': [asdict(key) for key in sorted(check_keys, key=lambda item: item.sort_key)],
            'evidence': evidence})
        if len(proof) > _MAX_PROOF_BYTES:
            _deny('REVIEW_MATERIAL_LIMIT')
        return proof, tuple(answers)

    @staticmethod
    def _bytes_input(label, ref, raw, **extra):
        if (type(raw) is not bytes or len(raw) != ref.byte_length
                or hashlib.sha256(raw).hexdigest() != ref.digest.hex):
            _deny('REVIEW_SOURCE_BYTES_MISMATCH')
        return {'label': label, 'ref': asdict(ref), 'bytes': base64.b64encode(raw).decode('ascii'),
                'digest': hashlib.sha256(raw).hexdigest(), **extra}

    def capture_proof(self, context, plan, request, *, standard, check_keys):
        with self.methods.guard_method(context, plan.requirement.method_ref) as snapshot:
            exact = self._standard(snapshot, plan)
            if exact != standard:
                _deny('METHOD_REQUIREMENTS_CHANGED')
            raw, _ = self._proof(context, plan, request, exact, check_keys)
        digest = Digest('sha256', hashlib.sha256(raw).hexdigest())
        return self.blobs.put_verified(raw, digest, 'application/vnd.ordessa.mechanical-review-proof+json')

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
            expected, answers = self._proof(context, plan, request, exact, check_keys)
        if stored != expected:
            _deny('REVIEW_SOURCE_PROOF_CHANGED')
        return VerifiedCheckResponse(answers, Digest('sha256', hashlib.sha256(expected).hexdigest()))

    @contextmanager
    def guard_checks(self, context, admissions):
        if type(admissions) is not tuple or not admissions:
            _deny()
        plans = {item.plan.requirement.method_ref for item in admissions}
        if len(plans) != 1:
            _deny('REVIEW_SOURCE_INVALID')
        with self.methods.guard_method(context, next(iter(plans))) as snapshot:
            for item in admissions:
                standard = self._standard(snapshot, item.plan)
                expected, answers = self._proof(context, item.plan, item.request,
                    standard, item.check_keys)
                if self.blobs.read_verified(item.raw_response_ref) != expected:
                    _deny('REVIEW_SOURCE_PROOF_CHANGED')
                if answers != item.response.answers or Digest('sha256', hashlib.sha256(expected).hexdigest()) != item.response.provenance_digest:
                    _deny('REVIEW_SOURCE_PROOF_CHANGED')
            yield


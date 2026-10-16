"""Review evidence from an independently executed, durable ACP review Unit.

This adapter consumes the original UnitRecords cold-read/capture seam.  The
method binding resolver selects the exact Unit, operation, prompt, delivery,
response schema and check selection; an injected UnitReviewerAuthority owns
reviewer identity and current trust through COMMIT.  Neither records nor DTOs
authenticate a reviewer.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from contextlib import ExitStack, contextmanager

from ordessa_infrastructure.encoding import canonical_bytes, decode_json

from ...application.contracts.errors import ApplicationError
from ...application.contracts.execution_observations import AuthorizedAcpTurnReader
from ..contracts.unit_review import UnitReviewBinding, UnitReviewBindingResolver, UnitReviewerAuthority
from ...application.contracts.reviewer_admission import (
    CriterionAnswer, VerifiedReviewResponse,
)
from ...application.usecases.changes.execution_capture import capture_execution_observation
from ...application.usecases.reviews.admission import review_observations
from ...domain.artifacts.refs import ArtifactRevisionRef
from ...domain.common.models.refs import BlobRef
from ...domain.common.models.values import Digest
from ...domain.reviews.evidence import VerifiedReviewerEvidence
from ...domain.reviews.models import CurrentReviewTrust, ReviewPlan, observations_digest
from ...methods.definitions.models.identity import ResourceRef


class UnitReviewCheckSource:
    """ReviewerSourcePort backed by original UnitRecords and same-authority blobs."""

    def __init__(self, factory, method_control, records: AuthorizedAcpTurnReader,
                 blobs, *, bindings: UnitReviewBindingResolver,
                 reviewer_authority: UnitReviewerAuthority | None = None):
        if (getattr(method_control, 'factory', None) is not factory
                or getattr(blobs, 'authority_id', None) != getattr(factory, 'authority_id', None)):
            raise ApplicationError('UNIT_REVIEW_AUTHORITY_MISMATCH')
        if records is None or bindings is None:
            raise ApplicationError('UNIT_REVIEW_SOURCE_UNAVAILABLE')
        self.factory, self.methods, self.records, self.blobs = factory, method_control, records, blobs
        self.bindings, self.authority = bindings, reviewer_authority

    @staticmethod
    def _binding(value, plan):
        if (type(value) is not UnitReviewBinding
                or type(value.plan_digest) is not Digest
                or type(value.request_version) is not int or value.request_version < 0
                or type(value.request_fence) is not int or value.request_fence < 1
                or type(value.unit_ref) is not dict
                or set(value.unit_ref) != {'environmentNamespace', 'unitId', 'ownerProviderRef', 'sourceRevision'}
                or type(value.delivery_refs) is not tuple
                or not value.delivery_refs
                or any(type(ref) is not ArtifactRevisionRef for ref in value.delivery_refs)
                or len(set(value.delivery_refs)) != len(value.delivery_refs)
                or type(value.response_schema_ref) is not ResourceRef
                or type(value.response_document_type) is not str or not value.response_document_type
                or type(value.response_schema) is not bytes or not value.response_schema
                or len(value.response_schema) > 262144
                or type(value.response_schema_digest) is not Digest
                or value.response_schema_digest.algorithm != 'sha256'
                or hashlib.sha256(value.response_schema).hexdigest() != value.response_schema_digest.hex
                or value.response_schema_ref.sha256 != value.response_schema_digest.hex
                or type(value.required_check_keys) is not tuple
                or not value.required_check_keys
                or len(set(value.required_check_keys)) != len(value.required_check_keys)
                or set(value.required_check_keys) != set(plan.check_keys)
                or not isinstance(value.reviewer_identity_constraints, Mapping)
                or not value.reviewer_identity_constraints):
            raise ApplicationError('UNIT_REVIEW_BINDING_INVALID')
        try:
            if len(canonical_bytes(dict(value.reviewer_identity_constraints))) > 65536:
                raise ApplicationError('UNIT_REVIEW_BINDING_INVALID')
        except (TypeError, ValueError, UnicodeError) as exc:
            raise ApplicationError('UNIT_REVIEW_BINDING_INVALID') from exc
        return value

    @staticmethod
    def _text(receipt):
        summary = receipt.get('summary')
        if (not isinstance(summary, dict) or type(summary.get('text')) is not str
                or not summary['text'] or summary.get('modelQualityVerified') is not False):
            raise ApplicationError('UNIT_REVIEW_RESPONSE_INVALID')
        return summary['text']

    def _standard(self, snapshot, plan, supplied):
        standards = [item for item in snapshot.program.standard_definitions
            if item.standard_id == plan.requirement.criterion_set_ref.criterion_set_id
            and item.resource_ref.sha256 == plan.requirement.criterion_set_ref.digest.hex]
        if len(standards) != 1 or (supplied is not None and supplied != standards[0]):
            raise ApplicationError('METHOD_REQUIREMENTS_CHANGED')
        return standards[0]

    def _schema_value(self, snapshot, binding, text):
        if len(text.encode('utf-8')) > 262144:
            raise ApplicationError('UNIT_REVIEW_RESPONSE_BOUND_EXCEEDED')
        resources = [item for item in snapshot.resources
            if item.resource_id == binding.response_schema_ref.resource_id
            and item.digest == binding.response_schema_ref.sha256]
        documents = [item for item in snapshot.program.document_definitions
            if item.document_type == binding.response_document_type
            and item.schema_resource == binding.response_schema_ref]
        if (len(resources) != 1 or len(documents) != 1
                or binding.response_schema_ref.kind != 'document_schema'
                or documents[0].validation_target != 'method_content'):
            raise ApplicationError('UNIT_REVIEW_SCHEMA_UNAVAILABLE')
        resource = resources[0]
        stored = resource.blob_ref
        try:
            snapshot_store = getattr(self.methods, 'snapshots', None)
            if snapshot_store is None or getattr(snapshot_store, 'library', None) is not self.factory.library:
                raise ValueError('same original snapshot store required')
            actual_schema = snapshot_store.read_blob(stored)
        except Exception as exc:
            raise ApplicationError('UNIT_REVIEW_SCHEMA_UNAVAILABLE') from exc
        if (actual_schema != binding.response_schema
                or hashlib.sha256(actual_schema).hexdigest() != binding.response_schema_digest.hex
                or resource.byte_length != len(actual_schema)
                or resource.media_type != stored.media_type):
            raise ApplicationError('UNIT_REVIEW_SCHEMA_MISMATCH')
        try:
            def no_duplicates(pairs):
                result = {}
                for key, value in pairs:
                    if key in result:
                        raise ValueError('duplicate json key')
                    result[key] = value
                return result
            value = json.loads(text, object_pairs_hook=no_duplicates,
                               parse_constant=lambda _: (_ for _ in ()).throw(ValueError('invalid constant')))
        except (ValueError, TypeError, RecursionError) as exc:
            raise ApplicationError('UNIT_REVIEW_RESPONSE_INVALID') from exc
        from .method_content import validate_document_content
        validation = validate_document_content(snapshot, binding.response_document_type, {'value': value})
        if not validation.ok:
            raise ApplicationError('UNIT_REVIEW_RESPONSE_SCHEMA_INVALID')
        return value

    def _capture(self, context, plan, request, standard, snapshot, raw_ref):
        if type(raw_ref) is not BlobRef:
            raise ApplicationError('UNIT_REVIEW_RESPONSE_INVALID')
        binding = self._binding(
            self.bindings.resolve_unit_review(context, plan, request, standard=standard), plan)
        if (binding.plan_digest != plan.plan_digest
                or binding.request_version != request.version
                or binding.request_fence != request.fence):
            raise ApplicationError('UNIT_REVIEW_REQUEST_BINDING_MISMATCH')
        if self.authority is None:
            raise ApplicationError('UNIT_REVIEW_AUTHORITY_UNAVAILABLE')
        captured = capture_execution_observation(
            self.records, self.blobs, authority_id=self.factory.authority_id,
            unit_ref=binding.unit_ref, operation_ref=binding.operation_ref,
            expected_prompt_digest=binding.expected_prompt_digest,
            query_invocation=binding.query_invocation)
        if captured.state != 'completed' or captured.expected_prompt_digest != binding.expected_prompt_digest:
            raise ApplicationError('UNIT_REVIEW_NOT_COMPLETED')
        raw = self.blobs.read_verified(captured.blob_ref)
        try:
            receipt = decode_json(raw)
        except Exception as exc:
            raise ApplicationError('UNIT_REVIEW_RECEIPT_INVALID') from exc
        if canonical_bytes(receipt) != raw or type(receipt) is not dict:
            raise ApplicationError('UNIT_REVIEW_RECEIPT_INVALID')
        text = self._text(receipt)
        # The exact delivery/schema/check selection must be part of the frozen
        # prompt whose digest the trusted resolver supplies. The captured
        # UnitRecords inputDigest is that prompt digest. The command's raw
        # response bytes must also be the exact completed Unit response text.
        try:
            submitted = self.blobs.read_verified(raw_ref)
        except Exception as exc:
            raise ApplicationError('UNIT_REVIEW_RESPONSE_INVALID') from exc
        if submitted != text.encode('utf-8'):
            raise ApplicationError('UNIT_REVIEW_RESPONSE_MISMATCH')
        response_value = self._schema_value(snapshot, binding, text)
        try:
            answers = self.bindings.decode_response(binding, response_value, plan=plan, standard=standard)
        except ApplicationError:
            raise
        except Exception as exc:
            raise ApplicationError('UNIT_REVIEW_RESPONSE_INVALID') from exc
        if (type(answers) is not tuple or len(answers) != len(plan.check_keys)
                or any(type(answer) is not CriterionAnswer for answer in answers)
                or len({answer.check_key for answer in answers}) != len(answers)
                or {answer.check_key for answer in answers} != set(plan.check_keys)):
            raise ApplicationError('UNIT_REVIEW_RESPONSE_INCOMPLETE')
        review_observations(plan, standard, answers)
        return binding, captured, answers

    def verify_response(self, context, plan, request, raw_response_ref, *, standard):
        with self.methods.guard_method(context, plan.requirement.method_ref) as snapshot:
            standard = self._standard(snapshot, plan, standard)
            binding, captured, answers = self._capture(
                context, plan, request, standard, snapshot, raw_response_ref)
            observations = review_observations(plan, standard, answers)
            obs_digest = observations_digest(observations)
            try:
                guard = self.authority.guard_unit_reviewer(
                    context, plan, request, binding, raw_response_ref, obs_digest)
                with guard as evidence:
                    self._validate_evidence(context, plan, request, raw_response_ref, obs_digest, evidence)
                    return VerifiedReviewResponse(evidence, answers)
            except ApplicationError:
                raise
            except Exception as exc:
                raise ApplicationError('UNIT_REVIEW_TRUST_UNAVAILABLE') from exc

    @staticmethod
    def _validate_evidence(context, plan, request, raw_ref, obs_digest, evidence):
        if (type(evidence) is not VerifiedReviewerEvidence or evidence.scope != context.scope
                or evidence.request_digest != plan.request_digest
                or evidence.raw_response_digest != raw_ref.digest
                or evidence.observations_digest != obs_digest
                or not set(plan.reviewer_requirements).issubset(evidence.roles)):
            raise ApplicationError('UNTRUSTED_REVIEWER')

    @contextmanager
    def guard_trust(self, context, records):
        if self.authority is None:
            raise ApplicationError('UNIT_REVIEW_AUTHORITY_UNAVAILABLE')
        if type(records) is not tuple:
            raise ApplicationError('INVALID_INPUT')
        with ExitStack() as stack:
            current = []
            for record in records:
                plan = record.plan
                snapshot = stack.enter_context(self.methods.guard_method(context, plan.requirement.method_ref))
                standards = [s for s in snapshot.program.standard_definitions
                        if s.standard_id == plan.requirement.criterion_set_ref.criterion_set_id
                        and s.resource_ref.sha256 == plan.requirement.criterion_set_ref.digest.hex]
                if len(standards) != 1:
                    raise ApplicationError('METHOD_REQUIREMENTS_CHANGED')
                standard = standards[0]
                request = self._request_for_record(context, record)
                binding, captured, answers = self._capture(
                    context, plan, request, standard, snapshot, record.raw_response_ref)
                observations = review_observations(plan, standard, answers)
                if observations != record.observations:
                    raise ApplicationError('UNIT_REVIEW_EVIDENCE_CHANGED')
                guard = self.authority.guard_unit_reviewer(
                    context, plan, request, binding, record.raw_response_ref,
                    observations_digest(observations), expected=record.reviewer_evidence)
                evidence = stack.enter_context(guard)
                self._validate_evidence(context, plan, request, record.raw_response_ref,
                                        observations_digest(observations), evidence)
                if evidence != record.reviewer_evidence:
                    raise ApplicationError('UNTRUSTED_REVIEWER')
                current.append(CurrentReviewTrust(record.ref, evidence.verifier_id, evidence.trust_version))
            yield tuple(current)

    def _request_for_record(self, context, record):
        resolver = getattr(self.bindings, 'resolve_record_request', None)
        if not callable(resolver):
            raise ApplicationError('UNIT_REVIEW_REQUEST_RESOLVER_UNAVAILABLE')
        request = resolver(context, record.plan, record)
        if (request is None or request.scope != context.scope
                or request.review_id != record.plan.review_id
                or type(request.version) is not int
                or request.version < 0 or type(request.fence) is not int or request.fence < 1):
            raise ApplicationError('REVIEW_REQUEST_CHANGED')
        return request


__all__ = ['UnitReviewBinding', 'UnitReviewBindingResolver', 'UnitReviewerAuthority',
           'UnitReviewCheckSource']

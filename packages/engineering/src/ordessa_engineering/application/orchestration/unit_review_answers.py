"""Strict method-document conversion to original full-plan CriterionAnswers.

This pure conversion does not authenticate a Unit, validate live source trust,
resolve evidence bytes, choose reviewer roles or turn an answer into a Grant.
The caller holds the original method/source guards and records through admission.
"""
import json
from ...application.contracts.errors import ApplicationError
from ...application.contracts.reviewer_admission import CriterionAnswer
from ...application.usecases.reviews.admission import review_observations
from ...domain.common.mechanisms.codec import require_object, decode_digest
from ...domain.common.outcomes.diagnostics import ReferenceError
from ...domain.common.models.values import validate_text
from ...domain.artifacts.ref_codec import decode_artifact_ref
from ...domain.reviews.target_codec import decode_target
from ...domain.reviews.models import CheckKey, ReviewPlan
from ...methods.definitions.models import MethodSnapshot
from .method_content import validate_document_content


MAX_UNIT_REVIEW_BYTES = 262144


def _pairs(items):
    value = {}
    for key, item in items:
        if key in value:
            raise ValueError('duplicate JSON property')
        value[key] = item
    return value


def decode_unit_review_result(plan, standard, raw_text, *, snapshot, document_type):
    """Decode the method-selected version-1 answer document for an exact plan.

    `document_type` and `snapshot` come from trusted composition/current method
    binding, never from an untrusted response selecting its own schema. No method
    name, phase, criterion, disposition policy or author!=reviewer rule is fixed.
    Every original key is required; answer order is canonicalized to plan order.
    """
    if type(plan) is not ReviewPlan or type(snapshot) is not MethodSnapshot:
        raise ApplicationError('UNIT_REVIEW_BINDING_INVALID')
    pinned = plan.requirement.method_ref
    actual = snapshot.ref
    if (actual.method_id, actual.release_version, actual.schema_version, actual.snapshot_digest) != (
            pinned.method_id, pinned.release_version, pinned.schema_version, pinned.snapshot_digest.hex):
        raise ApplicationError('METHOD_REQUIREMENTS_CHANGED')
    standards = [s for s in snapshot.program.standard_definitions
                 if s.standard_id == plan.requirement.criterion_set_ref.criterion_set_id
                 and s.resource_ref.sha256 == plan.requirement.criterion_set_ref.digest.hex]
    if len(standards) != 1 or standard != standards[0]:
        raise ApplicationError('METHOD_REQUIREMENTS_CHANGED')
    try:
        if type(raw_text) is not str or not raw_text or len(raw_text.encode('utf-8')) > MAX_UNIT_REVIEW_BYTES:
            raise ValueError('invalid response text bound')
        value = json.loads(raw_text, object_pairs_hook=_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite JSON constant')))
        require_object(value, {'schema_version','document_type','plan_digest','answers'}, 'INVALID_SCHEMA')
        if (type(value['schema_version']) is not int or value['schema_version'] != 1
                or type(document_type) is not str or not document_type
                or value['document_type'] != document_type):
            raise ValueError('selected response document differs')
        validation = validate_document_content(snapshot, document_type, {'value':value})
        if not validation.ok:
            raise ApplicationError('UNIT_REVIEW_RESPONSE_SCHEMA_INVALID')
        if decode_digest(value['plan_digest']) != plan.plan_digest:
            raise ApplicationError('UNIT_REVIEW_PLAN_DIGEST_MISMATCH')
        rows = value['answers']
        if type(rows) is not list or len(rows) != len(plan.check_keys):
            raise ApplicationError('UNIT_REVIEW_RESPONSE_INCOMPLETE')
        decoded = {}
        for row in rows:
            require_object(row, {'check_key','status','evidence_refs','rationale'}, 'INVALID_SCHEMA')
            key = row['check_key']
            require_object(key, {'target','criterion_id','claim_id'}, 'INVALID_SCHEMA')
            key = CheckKey(decode_target(key['target']), key['criterion_id'], key['claim_id'])
            if key in decoded or key not in plan.check_keys:
                raise ApplicationError('UNIT_REVIEW_RESPONSE_INCOMPLETE')
            if row['status'] not in ('satisfied','violated','insufficient','unknown') or type(row['status']) is not str:
                raise ValueError('invalid semantic answer status')
            validate_text(row['rationale'])
            if type(row['evidence_refs']) is not list:
                raise ValueError('evidence refs must be an array')
            evidence = tuple(decode_artifact_ref(ref) for ref in row['evidence_refs'])
            if (len(set(evidence)) != len(evidence) or any((ref.realm_id, ref.project_id) != (
                    plan.scope.realm_id, plan.scope.project_id) for ref in evidence)):
                raise ApplicationError('UNIT_REVIEW_EVIDENCE_SCOPE_MISMATCH')
            decoded[key] = CriterionAnswer(key, row['status'], evidence, row['rationale'])
        if set(decoded) != set(plan.check_keys):
            raise ApplicationError('UNIT_REVIEW_RESPONSE_INCOMPLETE')
        answers = tuple(decoded[key] for key in plan.check_keys)
        review_observations(plan, standard, answers)
        return answers
    except ApplicationError:
        raise
    except (ReferenceError, ValueError, TypeError, KeyError, UnicodeError, RecursionError, AttributeError) as exc:
        raise ApplicationError('UNIT_REVIEW_RESPONSE_INVALID') from exc

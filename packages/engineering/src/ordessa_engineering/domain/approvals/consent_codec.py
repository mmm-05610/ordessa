"""Closed canonical codecs for conversation-backed approval records."""
from dataclasses import asdict, fields
from ordessa_infrastructure.encoding import canonical_bytes
from ..common.mechanisms.codec import canonical_value, require_object, decode_scope, decode_digest, decode_tuple, projection
from ..common.outcomes.diagnostics import ReferenceError
from ..artifacts.ref_codec import decode_artifact_ref
from ..artifacts.method_codec import decode_method_ref
from ..reviews.codec import decode_requirement
from ..changes.ref_codec import decode_proposal_ref
from ..changes.models import ChangeSet
from ..changes.application_plan import HeadExpectation
from .consent import (ConsentPolicyRef, ConversationSource, NoticeRef, ConversationNotice,
                      WorkPackageNotice, AuthorizationIntent, ChangeAuthorizationIntent,
                      ConsentChallenge, ConversationEvidence, CapturedInstructionEvidence, ApprovalGrant)

from .implementation import (ImplementationAuthorizationIntent, ActionBudgetSlot,
                             WorkPackageAuthorization, WorkPackageAuthorizationIntent,
                             WORK_PACKAGE_SCHEMA_VERSION, WORK_PACKAGE_SUBJECT_KIND)
from ..changes.codec import decode_implementation_spec, decode_action_scope
from ..packages.codec import decode_package_ref
from ..reviews.ref_codec import decode_review_ref

_TYPES = (ImplementationAuthorizationIntent, ConsentPolicyRef, ConversationSource, NoticeRef, ConversationNotice,
          WorkPackageAuthorization, WorkPackageNotice, WorkPackageAuthorizationIntent,
          AuthorizationIntent, ChangeAuthorizationIntent, ConsentChallenge, ConversationEvidence,
          CapturedInstructionEvidence, ApprovalGrant)


def _decode(value, cls):
    if (cls is ConversationEvidence and type(value) is dict
            and ('schema_version' in value or 'evidence_kind' in value)):
        # The original command decodes this evidence family. New forms are
        # explicit, never guessed from a missing question or downgraded to Q&A.
        if (type(value.get('schema_version')) is not int or value.get('schema_version') != 2
                or value.get('evidence_kind') != 'captured_instruction'):
            raise ReferenceError('INVALID_CONSENT_RECORD')
        cls = CapturedInstructionEvidence
    if cls is AuthorizationIntent and type(value) is dict and value.get('intent_kind') == 'change_apply':
        cls = ChangeAuthorizationIntent
    if cls is AuthorizationIntent and type(value) is dict and value.get('intent_kind') == 'implementation':
        # Strict schema-version dispatch for the intent family: an absent version
        # is the original v1 implementation intent; the declared v2 version
        # selects the Work/package intent. Any other version is refused, never
        # guessed or silently downgraded to v1.
        version = value.get('schema_version')
        if version is None:
            cls = ImplementationAuthorizationIntent
        elif version == WORK_PACKAGE_SCHEMA_VERSION:
            cls = WorkPackageAuthorizationIntent
        else:
            raise ReferenceError('INVALID_CONSENT_RECORD')
    if cls is ConversationNotice and type(value) is dict and 'schema_version' in value:
        # The notice family follows the same rule: only the declared v2 version
        # selects the Work/package notice; an unknown version is refused.
        if value.get('schema_version') != WORK_PACKAGE_SCHEMA_VERSION:
            raise ReferenceError('INVALID_CONSENT_RECORD')
        cls = WorkPackageNotice
    if cls not in _TYPES:
        raise ReferenceError('INVALID_CONSENT_RECORD')
    require_object(value, {f.name for f in fields(cls)}, 'INVALID_CONSENT_RECORD')
    result = {}
    for key, item in value.items():
        if key == 'digest' and cls in (ConversationNotice, AuthorizationIntent, ChangeAuthorizationIntent, ImplementationAuthorizationIntent, ConversationEvidence, CapturedInstructionEvidence, ApprovalGrant,
                                       WorkPackageAuthorization, WorkPackageNotice, WorkPackageAuthorizationIntent):
            continue
        if key == 'intent_kind' and cls in (ChangeAuthorizationIntent, ImplementationAuthorizationIntent, WorkPackageAuthorizationIntent):
            if item != ('change_apply' if cls is ChangeAuthorizationIntent else 'implementation'):
                raise ReferenceError('INVALID_CONSENT_RECORD')
            continue
        if key == 'schema_version' and cls in (WorkPackageAuthorization,
                                               WorkPackageAuthorizationIntent, WorkPackageNotice,
                                               CapturedInstructionEvidence):
            # An unknown schema version is refused, never coerced to v2.
            if item != WORK_PACKAGE_SCHEMA_VERSION:
                raise ReferenceError('INVALID_CONSENT_RECORD')
            continue
        if cls is CapturedInstructionEvidence and key in ('evidence_kind', 'binding_origin'):
            expected = {'evidence_kind': 'captured_instruction',
                        'binding_origin': 'registered-main-agent'}
            if item != expected[key]:
                raise ReferenceError('INVALID_CONSENT_RECORD')
            continue
        if key == 'subject_kind' and cls is WorkPackageAuthorization:
            if item != WORK_PACKAGE_SUBJECT_KIND:
                raise ReferenceError('INVALID_CONSENT_RECORD')
            continue
        if key == 'scope':
            item = decode_scope(item)
        elif key == 'targets':
            item = decode_tuple(item, decode_artifact_ref, 'INVALID_CONSENT_RECORD')
        elif key == 'summary_ref':
            item = decode_artifact_ref(item)
        elif key == 'method_ref':
            item = decode_method_ref(item)
        elif key == 'package_ref':
            item = decode_package_ref(item)
        elif key == 'authorization':
            item = _decode(item, WorkPackageAuthorization)
        elif key in ('digest', 'binding_digest', 'presented_digest', 'nonce_digest', 'intent_digest', 'work_digest'):
            item = decode_digest(item)
        elif key == 'implementation_spec':
            item = decode_implementation_spec(item)
        elif key == 'supporting_review_refs':
            item = decode_tuple(item, decode_review_ref, 'INVALID_CONSENT_RECORD')
        elif key == 'scope_by_action':
            def action_scope(v):
                if type(v) is not list or len(v) != 2:
                    raise ReferenceError('INVALID_CONSENT_RECORD')
                return (v[0], decode_action_scope(v[1]))
            item = decode_tuple(item, action_scope, 'INVALID_CONSENT_RECORD')
        elif key == 'action_budgets':
            def slot(v):
                require_object(v, {'action', 'limit'}, 'INVALID_CONSENT_RECORD')
                return ActionBudgetSlot(**v)
            item = decode_tuple(item, slot, 'INVALID_CONSENT_RECORD')
        elif key == 'required_review_requirements':
            item = decode_tuple(item, lambda x: decode_requirement(canonical_bytes(x)), 'INVALID_CONSENT_RECORD')
        elif key == 'change_set':
            require_object(item, {'proposal_refs', 'digest'}, 'INVALID_CHANGE_SET')
            decoded = ChangeSet(decode_tuple(item['proposal_refs'], decode_proposal_ref, 'INVALID_CHANGE_SET'))
            if decoded.digest != decode_digest(item['digest']):
                raise ReferenceError('CONSENT_DIGEST_MISMATCH')
            item = decoded
        elif key == 'expected_heads':
            def head(v):
                require_object(v, {'artifact_id', 'version', 'head_ref'}, 'INVALID_MUTATION')
                return HeadExpectation(v['artifact_id'], v['version'],
                    None if v['head_ref'] is None else decode_artifact_ref(v['head_ref']))
            item = decode_tuple(item, head, 'INVALID_MUTATION')
        elif key in ('actions', 'message_refs'):
            item = decode_tuple(item, lambda x: x, 'INVALID_CONSENT_RECORD')
        elif key == 'source':
            item = _decode(item, ConversationSource)
        elif key == 'policy_ref':
            item = _decode(item, ConsentPolicyRef)
        elif key == 'notice_ref':
            item = _decode(item, NoticeRef)
        elif key == 'intent':
            item = _decode(item, AuthorizationIntent)
        elif key == 'evidence':
            item = _decode(item, ConversationEvidence)
        result[key] = item
    record = cls(**result)
    if hasattr(record, 'digest') and 'digest' not in result and decode_digest(value['digest']) != record.digest:
        raise ReferenceError('CONSENT_DIGEST_MISMATCH')
    return record


def decode_record(raw, cls):
    return _decode(canonical_value(raw), cls)


def encode_record(record):
    if type(record) not in _TYPES:
        raise ReferenceError('INVALID_CONSENT_RECORD')
    raw = canonical_bytes(projection(record))
    if decode_record(raw, type(record)) != record:
        raise ReferenceError('INVALID_CONSENT_RECORD')
    return raw

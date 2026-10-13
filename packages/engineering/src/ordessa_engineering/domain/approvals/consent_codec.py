"""Closed canonical codecs for conversation-backed approval records."""
from dataclasses import asdict, fields
from ordessa_infrastructure.encoding import canonical_bytes
from ..common.mechanisms.codec import canonical_value, require_object, decode_scope, decode_digest, decode_tuple
from ..common.outcomes.diagnostics import ReferenceError
from ..artifacts.ref_codec import decode_artifact_ref
from ..artifacts.method_codec import decode_method_ref
from ..reviews.codec import decode_requirement
from ..changes.ref_codec import decode_proposal_ref
from ..changes.models import ChangeSet
from ..changes.application_plan import HeadExpectation
from .consent import (ConsentPolicyRef, ConversationSource, NoticeRef, ConversationNotice,
                      AuthorizationIntent, ChangeAuthorizationIntent, ConsentChallenge, ConversationEvidence, ApprovalGrant)

from .implementation import ImplementationAuthorizationIntent, ActionBudgetSlot
from ..changes.codec import decode_implementation_spec, decode_action_scope
from ..reviews.ref_codec import decode_review_ref

_TYPES = (ImplementationAuthorizationIntent, ConsentPolicyRef, ConversationSource, NoticeRef, ConversationNotice,
          AuthorizationIntent, ChangeAuthorizationIntent, ConsentChallenge, ConversationEvidence, ApprovalGrant)


def _decode(value, cls):
    if cls is AuthorizationIntent and type(value) is dict and value.get('intent_kind') == 'change_apply':
        cls = ChangeAuthorizationIntent
    if cls is AuthorizationIntent and type(value) is dict and value.get('intent_kind') == 'implementation':
        cls = ImplementationAuthorizationIntent
    if cls not in _TYPES:
        raise ReferenceError('INVALID_CONSENT_RECORD')
    require_object(value, {f.name for f in fields(cls)}, 'INVALID_CONSENT_RECORD')
    result = {}
    for key, item in value.items():
        if key == 'digest' and cls in (ConversationNotice, AuthorizationIntent, ChangeAuthorizationIntent, ImplementationAuthorizationIntent, ConversationEvidence, ApprovalGrant):
            continue
        if key == 'intent_kind' and cls in (ChangeAuthorizationIntent, ImplementationAuthorizationIntent):
            if item != ('change_apply' if cls is ChangeAuthorizationIntent else 'implementation'):
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
        elif key in ('digest', 'binding_digest', 'presented_digest', 'nonce_digest', 'intent_digest'):
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
    raw = canonical_bytes(asdict(record))
    if decode_record(raw, type(record)) != record:
        raise ReferenceError('INVALID_CONSENT_RECORD')
    return raw

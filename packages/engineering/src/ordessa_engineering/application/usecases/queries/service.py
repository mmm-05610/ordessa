"""Authenticated exact reads on one scoped UoW; returns actual typed records.

The existing owner admits CommandContext for reads too. A transport-specific
QueryContext/serialized QueryResult and list projections are not fabricated.
"""
from dataclasses import asdict
from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.domain.reviews.target_codec import (decode_subject_ref)
from ordessa_engineering.domain.changes.ref_codec import (decode_proposal_ref)
from ordessa_engineering.domain.reviews.ref_codec import (decode_review_ref)
from ordessa_engineering.domain.approvals.ref_codec import (decode_approval_ref)
from ....domain.common.outcomes.diagnostics import (ReferenceError)
from ....domain.common.mechanisms.codec import (canonical_value)
from ....domain.common.models.values import (validate_id)
from ordessa_engineering.application.contracts.commands import CommandContext
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.approvals.consent import NoticeRef
from ordessa_engineering.domain.approvals.consent_codec import decode_record
from .references import resolve_exact
from .commands import read_command


_INPUTS = {
    "engineering.reviews.get_request": {"review_id"},
    "engineering.acceptance.get": {"adoption_id"},
    "engineering.artifacts.get": {"artifact_id"},
    "engineering.references.resolve": {"ref"},
    "engineering.proposals.get": {"proposal_ref"},
    "engineering.proposals.get_control": {"proposal_ref"},
    "engineering.changes.get": {"change_id"},
    "engineering.commands.get": {"request_id"},
    "engineering.notices.get": {"notice_ref"},
    "engineering.approvals.get": {"approval_ref"},
    "engineering.approvals.get_control": {"approval_ref"},
    "engineering.approvals.get_budget": {"approval_ref"},
    "engineering.changes.get_apply": {"apply_id"},
    "engineering.approvals.get_intent": {"intent_id"},
    "engineering.approvals.get_challenge": {"challenge_id"},
    "engineering.approvals.list_pending": {"limit", "after_challenge_id"},
}
SUPPORTED_QUERIES = tuple(_INPUTS)


class EngineeringQueries:
    def __init__(self, factory, access):
        self.factory = factory
        self.access = access

    def query(self, query, parameters, context):
        if type(context) is not CommandContext:
            raise ApplicationError("INVALID_CONTEXT")
        if type(query) is not str:
            raise ApplicationError("INVALID_ARGUMENT")
        if self.access is None:
            raise ApplicationError("ACCESS_AUTHORITY_UNAVAILABLE")
        self.access.require(context, query)
        if query not in _INPUTS:
            raise ApplicationError("QUERY_UNAVAILABLE")
        try:
            raw = canonical_bytes(parameters)
            if len(raw) > 2 * 1024 * 1024:
                raise ApplicationError("INVALID_INPUT")
            value = canonical_value(raw)
            if type(value) is not dict or set(value) != _INPUTS[query]:
                raise ApplicationError("INVALID_INPUT")
            if query == "engineering.approvals.list_pending":
                if type(value['limit']) is not int or not 1 <= value['limit'] <= 100:
                    raise ApplicationError('INVALID_INPUT')
                if value['after_challenge_id'] is not None:
                    validate_id(value['after_challenge_id'])
                target = None
            elif "notice_ref" in value:
                target = decode_record(canonical_bytes(value['notice_ref']), NoticeRef)
            elif "approval_ref" in value:
                target = decode_approval_ref(value['approval_ref'])
            elif "ref" in value:
                ref = value["ref"]
                if type(ref) is dict and ref.get("kind") == "review":
                    target = decode_review_ref(ref)
                elif type(ref) is dict and ref.get("kind") == "approval":
                    target = decode_approval_ref(ref)
                elif type(ref) is dict and set(ref) == {'scope', 'notice_id', 'digest'}:
                    target = decode_record(canonical_bytes(ref), NoticeRef)
                else:
                    target = decode_subject_ref(ref)
            elif "proposal_ref" in value:
                target = decode_proposal_ref(value["proposal_ref"])
            else:
                target = next(iter(value.values()))
                validate_id(target)
        except (ReferenceError, TypeError, ValueError, RecursionError, OverflowError):
            raise ApplicationError("INVALID_INPUT") from None
        with self.factory.begin(context.scope, "read") as uow:
            if query == "engineering.reviews.get_request":
                request = uow.reviews.get_request(target)
                plan = uow.reviews.get_plan(target)
                if request.scope != context.scope or plan.scope != context.scope:
                    raise ApplicationError("SCOPE_MISMATCH")
                return {"request": request, "plan": plan}
            if query == 'engineering.acceptance.get':
                return uow.acceptance.resolve(target)
            if query == 'engineering.notices.get':
                return uow.authorization.get_notice(target)
            if query == 'engineering.approvals.get':
                return uow.authorization.get_grant(target)
            if query == 'engineering.approvals.get_control':
                return uow.authorization.get_control(target)
            if query == 'engineering.approvals.get_budget':
                return uow.authorization.action_budget(target)
            if query == 'engineering.changes.get_apply':
                return uow.authorization.get_apply(target)
            if query == 'engineering.approvals.get_intent':
                return uow.authorization.get_intent(target)
            if query == 'engineering.approvals.get_challenge':
                challenge, state, version = uow.authorization.get_challenge(target)
                return {'challenge': asdict(challenge), 'state': state, 'version': version}
            if query == 'engineering.approvals.list_pending':
                return uow.authorization.list_pending(limit=value['limit'],
                    after_challenge_id=value['after_challenge_id'])
            if query == "engineering.artifacts.get":
                return uow.engineering.get_artifact(target)
            if query == "engineering.references.resolve":
                return resolve_exact(uow, target)
            if query == "engineering.proposals.get":
                return uow.proposals.get_proposal(target)
            if query == "engineering.proposals.get_control":
                return uow.proposals.get_control(target)
            if query == "engineering.changes.get":
                return uow.proposals.get_change(target)
            return read_command(uow, context, target)

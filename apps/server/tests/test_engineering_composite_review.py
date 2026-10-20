"""Actual instance service authority and complete nominal/mechanical routing.

Method/business configuration and model transport are explicit fixtures; access,
SQLite/Blob/ReviewRecord/CAS, mixed owners and source guards are original APIs.
No real model or human answer is generated.
"""
from dataclasses import asdict, replace
import hashlib
import importlib.util
from pathlib import Path

import pytest
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.contracts.mixed_reviews import FrozenCheckRequest
from ordessa_engineering.application.usecases.reviews.service import ReviewUseCases
from ordessa_engineering.application.usecases.reviews.mixed import MixedCheckPart, encode_mixed_response
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_interfaces.system_access.access_control.authentication import AccessGrant
from ordessa_server.composition.engineering_mixed_review import (
    COMPOSITE_REVIEW_CAPABILITY, OriginalCompositeReviewerAuthority, mixed_review_ports_factory,
)
from ordessa_server.composition.engineering_reviewer_source import OriginalJevReviewerSource, encode_review_run

_spec=importlib.util.spec_from_file_location('composite_nominal_fixture',
    Path(__file__).with_name('test_engineering_jev_nominal_source.py'))
_fixture=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_fixture)


def _setup(work, *, grant_composite=True):
    old=work['reviews'].admission.source;access=old.access
    capabilities=(*_fixture.OPERATIONS,COMPOSITE_REVIEW_CAPABILITY) if grant_composite else _fixture.OPERATIONS
    access.authority.replace_grants((AccessGrant(_fixture.SCOPE,capabilities),))
    caller=access.authority.authenticate('Bearer controlled-fixture-token')
    admitted=lambda op,identity:access.admit(caller,_fixture.SCOPE,op,request_id=identity,trace_id=identity)
    def source_factory(methods,blobs,access,scope):
        return OriginalJevReviewerSource(access=access,scope=scope,blobs=blobs,
            evidence_reader=old.reader,read_context=old.read_context,provider=old.provider,
            runs=old.runs,roles=old.roles,accepted_models=old.models,flows=old.flows,
            method_control=methods)
    ports=mixed_review_ports_factory(bindings=work['reviews'].admission.bindings,
        jev_source_factory=source_factory,roles=('reviewer',))(work['factory'],access,_fixture.SCOPE)
    reviews=ReviewUseCases(work['factory'],access,ports.review_admission,blobs=ports.blobs)
    return ports,reviews,admitted


def _response(work, ports, context):
    plan,request=work['plan'],work['request'];mixed=ports.review_admission.source
    with mixed.methods.guard_method(context,plan.requirement.method_ref) as snapshot:
        standard=next(s for s in snapshot.program.standard_definitions
            if s.standard_id==plan.requirement.criterion_set_ref.criterion_set_id)
    caps={c.criterion_id:c.checks[0].capability_id for c in standard.criteria}
    mechanical_keys=tuple(k for k in plan.check_keys if caps[k.criterion_id]!='ordessa.decision.evaluate')
    jev_keys=tuple(k for k in plan.check_keys if k not in mechanical_keys)
    frozen=FrozenCheckRequest(plan.plan_digest,request.version,request.fence)
    mechanical=mixed.sources['original-mechanical']
    proof=mechanical.capture_proof(context,plan,frozen,standard=standard,check_keys=mechanical_keys)
    raw=encode_review_run(work['run'])
    raw_ref=ports.blobs.put_verified(raw,Digest('sha256',hashlib.sha256(raw).hexdigest()),'application/json')
    return encode_mixed_response(plan,request.version,request.fence,(
        MixedCheckPart('original-jev',jev_keys,raw_ref),
        MixedCheckPart('original-mechanical',mechanical_keys,proof)))


def test_actual_service_composite_records_full_keys_without_human_or_grant(tmp_path):
    work=_fixture._prepare(tmp_path,'supported',mixed=True)
    try:
        ports,reviews,admitted=_setup(work)
        with admitted('engineering.reviews.record','mixed-source-capture') as context:
            raw=_response(work,ports,context)
            record=reviews.record_response(work['plan'].review_id,raw,context,
                expected_request_version=0,fence=1)
            assert record.status=='completed'
        with admitted('engineering.reviews.query','mixed-gate') as context:
            state=reviews.query_set(work['plan'].requirement,context)
            recorded=state.reviews[0].record
            assert len(recorded.observations)==len(work['plan'].check_keys)==4
            assert recorded.complete and all(o.result=='indeterminate' for o in recorded.observations)
            assert recorded.reviewer_evidence.reviewer.actor_kind=='service'
            assert recorded.reviewer_evidence.reviewer.actor_id==ports.review_admission.source.authority.principal_id
            assert not reviews.gate(work['plan'].requirement,context).satisfied
        assert len(work['calls'])==2
    finally:_fixture._close(work)


def test_missing_explicit_composite_grant_preserves_requested(tmp_path):
    work=_fixture._prepare(tmp_path,'supported',mixed=True)
    try:
        ports,reviews,admitted=_setup(work,grant_composite=False)
        with admitted('engineering.reviews.record','ungranted-composite') as context:
            raw=_response(work,ports,context)
            with pytest.raises(ApplicationError,match='ACCESS_'):
                reviews.record_response(work['plan'].review_id,raw,context,expected_request_version=0,fence=1)
        with work['factory'].begin(work['plan'].scope,'read') as uow:
            request=uow.reviews.get_request(work['plan'].review_id)
            assert request.state=='requested' and request.version==0 and request.fence==1
        assert len(work['calls'])==2
    finally:_fixture._close(work)


@pytest.mark.parametrize('roles', (('human',),('reviewer','human'),()))
def test_composite_never_infers_human_role_from_configured_tuple(tmp_path,roles):
    work=_fixture._prepare(tmp_path,'supported')
    try:
        access=work['reviews'].admission.source.access
        with pytest.raises(ApplicationError,match='MIXED_REVIEWER_AUTHORITY_UNAVAILABLE'):
            OriginalCompositeReviewerAuthority(access,scope=_fixture.SCOPE,
                principal_id=access.authority.principal_id,roles=roles)
    finally:_fixture._close(work)

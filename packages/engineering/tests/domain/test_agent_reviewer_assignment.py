"""Versioned role data only; original Engineering issuer/authorization stays separate."""
from dataclasses import replace
from pathlib import Path
import hashlib,json
import pytest
from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.domain.reviews.assignments import ReviewerAssignment,HistoricalReviewerAssignment
from ordessa_engineering.domain.reviews.assignment_codec import (
    encode_reviewer_assignment,decode_reviewer_assignment,encode_historical_reviewer_assignment)
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError

BASE=Path(__file__).parent/'fixtures/reviewer-assignment-v1-baseline.json'


def agent(instance,digest='a'):
    return canonical_bytes({'schemaVersion':'agent-instance/1','namespace':'namespace',
        'instanceId':instance,'bindingDigest':'sha256:'+digest*64})


def assignment():
    old=decode_reviewer_assignment(BASE.read_bytes())
    return ReviewerAssignment(old.scope,old.assignment_id,old.review_id,old.plan_digest,
        old.request_version,old.fence,old.method_ref,agent('reviewer'),agent('author'),old.roles,
        old.issuer_principal_id,old.issuer_credential_epoch,old.assigned_at)


def test_historical_v1_role_bytes_and_digest_are_exact_and_never_current_assignment():
    raw=BASE.read_bytes();old=decode_reviewer_assignment(raw)
    assert hashlib.sha256(raw).hexdigest()=='57abbacba45434a086585c0693ff7baf43573144e42a5a371eac7dfb6da617bd'
    assert type(old) is HistoricalReviewerAssignment
    assert old.digest.hex=='18467ae6cef3a7bd5e1543eede694974d73556a1393106d45033957a768687d1'
    assert encode_historical_reviewer_assignment(old)==raw
    with pytest.raises(ReferenceError,match='AGENT_REVIEWER_ASSIGNMENT_REQUIRED'):encode_reviewer_assignment(old)


def test_current_closed_agent_role_roundtrip_preserves_original_business_issuer_fields():
    current=assignment();old=decode_reviewer_assignment(BASE.read_bytes())
    assert decode_reviewer_assignment(encode_reviewer_assignment(current))==current
    for name in ('scope','assignment_id','review_id','plan_digest','request_version','fence','method_ref',
            'roles','issuer_principal_id','issuer_credential_epoch','assigned_at'):
        assert getattr(current,name)==getattr(old,name)
    assert current.digest!=old.digest
    assert current.require_distinct_author() is None
    wire=json.loads(encode_reviewer_assignment(current))
    assert wire['schemaVersion']=='engineering-agent-reviewer-assignment/2'
    assert 'reviewer_unit_ref' not in wire and 'author_unit_ref' not in wire


@pytest.mark.parametrize('changes',[{'reviewer_agent_ref_bytes':b'{"unitId":"old"}'},
    {'issuer_credential_epoch':-1},{'request_version':True},{'fence':0},
    {'roles':()},{'roles':('reviewer','reviewer')}])
def test_original_role_invariants_and_mixed_unit_ref_refuse(changes):
    with pytest.raises(ReferenceError):replace(assignment(),**changes)


@pytest.mark.parametrize('digest',['a','b'])
def test_same_agent_cannot_be_independent_reviewer_by_changing_binding_digest(digest):
    value=replace(assignment(),reviewer_agent_ref_bytes=agent('author',digest))
    with pytest.raises(ReferenceError,match='UNTRUSTED_REVIEWER'):value.require_distinct_author()


@pytest.mark.parametrize('field,value',[('schemaVersion','unknown/2'),('reviewer_unit_ref',{}),('roles',['admin'])])
def test_wire_unknown_fields_versions_and_modified_role_digest_refuse(field,value):
    wire=json.loads(encode_reviewer_assignment(assignment()));wire[field]=value
    with pytest.raises(ReferenceError):decode_reviewer_assignment(canonical_bytes(wire))

"""Agent-native authorship is source data, never a legacy reviewer grant."""
from dataclasses import asdict,replace
import pytest
from ordessa_infrastructure.encoding import canonical_bytes
from ordessa_engineering.application.contracts.review_authorship import (
    AgentReviewAuthorship,ReviewAuthorship,NATIVE_DIFFERENT_UNIT,SOURCE_BOUND_POLICY,NATIVE_DIFFERENT_AGENT,AGENT_SOURCE_BOUND_POLICY,authorship_mode,authorship_projection,
)
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.artifacts.method_binding import MethodRef
from ordessa_engineering.domain.artifacts.refs import ArtifactRevisionRef
from ordessa_engineering.domain.common.models.identity import Scope
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.common.outcomes.diagnostics import ReferenceError


def ref(instance='author',digest='a'):
    return canonical_bytes({'schemaVersion':'agent-instance/1','namespace':'namespace',
        'instanceId':instance,'bindingDigest':'sha256:'+digest*64})


def origin():
    d=Digest('sha256','a'*64)
    method=MethodRef('method','1',1,d)
    return AgentReviewAuthorship(Scope('realm','project'),method,
        (ArtifactRevisionRef('realm','project','artifact','revision',d),),ref())


def test_original_author_cannot_become_reviewer_by_changing_binding_digest():
    value=origin()
    for digest in ('a','b'):
        with pytest.raises(ApplicationError,match='UNTRUSTED_REVIEWER'):
            value.require_distinct_reviewer(ref(digest=digest))
    assert value.require_distinct_reviewer(ref('other')) is None


def test_agent_source_facts_select_identity_rule_without_grant():
    value=origin()
    for policy in (NATIVE_DIFFERENT_AGENT,AGENT_SOURCE_BOUND_POLICY):
        assert authorship_mode(policy,value)=='different_original_agent'
    assert not hasattr(value,'roles') and not hasattr(value,'issuer_principal_id')
    assert not hasattr(value,'author_unit_ref') and 'author_unit_ref' not in asdict(value)
    # Preserve the old material/v1 DTO shape; no newly inserted null field changes
    # original material source-bound prompt bytes or their original digest.
    assert 'author_agent_ref_bytes' not in ReviewAuthorship.__dataclass_fields__


def test_mixed_unit_identity_and_foreign_delivery_scope_refuse():
    with pytest.raises(ReferenceError):replace(origin(),author_agent_ref_bytes=b'{"unitId":"old"}')
    with pytest.raises(ApplicationError,match='REVIEW_AUTHOR_SOURCE_INVALID'):
        replace(origin(),scope=Scope('foreign','project'))


def test_historical_unit_authorship_cannot_supply_current_agent_assignment():
    value=origin()
    old=ReviewAuthorship(value.scope,value.method_ref,value.delivery_refs,'native_unit',
        {'environmentNamespace':'old','unitId':'author','ownerProviderRef':'provider','sourceRevision':'1'})
    # Historical policy semantics and DTO bytes remain unchanged.
    assert authorship_mode(NATIVE_DIFFERENT_UNIT,old)=='different_original_unit'
    assert authorship_mode(SOURCE_BOUND_POLICY,old)=='different_original_unit'
    assert authorship_projection(old)==asdict(old)
    for policy in (NATIVE_DIFFERENT_AGENT,AGENT_SOURCE_BOUND_POLICY):
        with pytest.raises(ApplicationError,match='AGENT_REVIEW_AUTHOR_BINDING_UNAVAILABLE'):
            authorship_mode(policy,old)
    for policy in (NATIVE_DIFFERENT_UNIT,SOURCE_BOUND_POLICY):
        with pytest.raises(ApplicationError,match='AGENT_REVIEW_IDENTITY_CONSTRAINT_REQUIRED'):
            authorship_mode(policy,value)
    assert authorship_projection(value)['schemaVersion']=='engineering-agent-review-authorship/2'

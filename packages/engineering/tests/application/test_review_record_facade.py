"""Finite facade recording on original human-review owners; authority is fixture-only."""
import asyncio
from dataclasses import asdict

import pytest
from jsonschema import Draft202012Validator

from test_human_review_admission import human_case, _reply
from test_method_control_admission import context
from test_proposal_usecases import SyntheticAccess, SCOPE
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.api.service import EngineeringService
from ordessa_engineering.application.usecases.reviews.human import encode_human_review_response
from ordessa_engineering.application.orchestration.method_bridge import command_capabilities


def facade(case, *, admitted=True):
    return EngineeringService(case['factory'], SyntheticAccess(),
        review_admission=case['admission'] if admitted else None, blobs=case['blobs'])


def params(case):
    raw = encode_human_review_response(case['plan'], case['request']['version'],
        case['request']['fence'], _reply(case['plan']), case['proof'])
    return {'review_id':case['plan'].review_id,'request_version':case['request']['version'],
        'fence':case['request']['fence'],'raw_response_utf8':raw.decode('utf-8')}


def execute(owner, body, ctx):
    return asyncio.run(owner.execute('engineering.reviews.record', body, ctx))


def test_finite_facade_commits_original_review_and_replays_exact_journal(human_case):
    owner=facade(human_case);body=params(human_case);ctx=context('facade-human-record')
    result=execute(owner,body,ctx)
    assert result.status=='completed'
    assert execute(owner,body,ctx)==result
    assert human_case['reviews'].gate(human_case['requirement'],context('facade-gate')).satisfied
    with human_case['factory'].begin(SCOPE,'read') as uow:
        assert uow.engineering.access.execute('SELECT COUNT(*) FROM eng_approval_grants').fetchone()[0]==0


def test_finite_facade_cannot_accept_caller_plan_verdict_or_digest_only(human_case):
    owner=facade(human_case);body=params(human_case)
    for extra in ('plan','reviewer_evidence','verdict','raw_response_digest'):
        with pytest.raises(ApplicationError,match='INVALID_INPUT'):
            execute(owner,body|{extra:'pass'},context('facade-extra-'+extra))
    with pytest.raises(ApplicationError,match='INVALID_INPUT'):
        execute(owner,body|{'raw_response_utf8':b'bytes'},context('facade-bytes'))
    with pytest.raises(ApplicationError,match='REVIEW_REQUEST_CHANGED'):
        execute(owner,body|{'fence':body['fence']+1},context('facade-fence'))
    with human_case['factory'].begin(SCOPE,'read') as uow:
        assert uow.reviews.get_request(body['review_id']).state=='requested'


def test_facade_missing_original_admission_cannot_record(human_case):
    with pytest.raises(ApplicationError,match='REVIEW_AUTHORITY_UNAVAILABLE'):
        execute(facade(human_case,admitted=False),params(human_case),context('facade-no-owner'))


def test_real_descriptor_has_finite_typed_utf8_envelope():
    descriptor=next(d for d in command_capabilities().capabilities
        if d.capability_id=='engineering.reviews.record')
    schema=EngineeringService.input_schema('engineering.reviews.record')
    assert descriptor.contract['input_schema']==schema
    assert descriptor.contract['completion']=='formal_review_record_persisted_not_implementation_grant'
    good={'review_id':'r','request_version':0,'fence':1,'raw_response_utf8':'{}'}
    assert Draft202012Validator(schema).is_valid(good)
    for bad in (good|{'fence':0},good|{'request_version':True},good|{'verdict':'pass'},
                {k:v for k,v in good.items() if k!='raw_response_utf8'}):
        assert not Draft202012Validator(schema).is_valid(bad)

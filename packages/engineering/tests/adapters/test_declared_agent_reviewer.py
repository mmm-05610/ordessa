"""Actual assigned Agent response -> original review COMMIT; no model calls."""
import asyncio
from dataclasses import asdict, replace
import hashlib
import pytest
from ordessa_infrastructure.encoding import canonical_bytes, decode_json
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.common.models.values import Digest
from ordessa_engineering.domain.reviews.ref_codec import decode_review_ref
from test_declared_agent_implementation_review import review_case
from test_real_source_chain import SCOPE, NOW


def turns(f):
    return f['native'].records._db.execute("SELECT count(*) FROM operations WHERE operation='turn'").fetchone()[0]


def blob(f,value):
    raw=canonical_bytes(value)
    return f['env'].blobs.put_verified(raw,Digest('sha256',hashlib.sha256(raw).hexdigest()),'application/json')


@pytest.mark.parametrize('verdict,status,result',[('passed','satisfied','pass'),('rejected','violated','fail'),
    ('cancelled','unknown','indeterminate'),('unknown','unknown','indeterminate')])
def test_actual_original_issuer_capture_commit_and_unchanged_holistic_mapping(tmp_path,monkeypatch,verdict,status,result):
    async def scenario():
        async with review_case(tmp_path,monkeypatch,verdict) as f:
            access=f['access']; source=f['review_source']; plan=f['review_plan']; request=f['review_request']
            with access.admit(f['caller'],f['wire'],'engineering.reviews.record',request_id='record-independent',trace_id='review') as ctx:
                verified=source.verify_response(ctx,plan,request,f['raw_ref'],standard=f['review_standard'])
                assert len(verified.answers)==1 and verified.answers[0].status==status
                answer=await f['review_service'].execute('engineering.reviews.record',{
                    'review_id':plan.review_id,'request_version':request.version,'fence':request.fence,
                    'raw_response_utf8':f['env'].blobs.read_verified(f['raw_ref']).decode('utf-8')},ctx)
                assert answer.status=='completed'
                value=decode_json(answer.result_bytes)
                assert value['verdict']==result
                with f['factory'].begin(SCOPE,'read') as uow:
                    record=uow.reviews.get_review(decode_review_ref(value['review_ref']))
                    current=uow.reviews.get_request(plan.review_id)
                    assert current.state=='recorded' and current.version==request.version+1
                    assert record.complete and record.verdict==result
                with source.guard_trust(ctx,(record,)) as trust:
                    assert trust[0].review_ref==record.ref
                    # The original assignment final-COMMIT fence observes a
                    # same-transaction role revocation and rolls it back.
                    with pytest.raises(ApplicationError):
                        with f['factory'].begin(SCOPE,'write') as uow:
                            uow.reviewer_assignments.revoke(f['assignment'].ref,expected_version=0,
                                revoked_at=NOW,reason='controlled final fence',event_id='controlled-final-fence')
                            uow.commit()
                with f['factory'].begin(SCOPE,'read') as uow:
                    assert uow.reviewer_assignments.control(f['assignment'].ref).state=='active'
                before=turns(f)
                replay=await f['review_service'].execute('engineering.reviews.record',{
                    'review_id':plan.review_id,'request_version':request.version,'fence':request.fence,
                    'raw_response_utf8':f['env'].blobs.read_verified(f['raw_ref']).decode('utf-8')},ctx)
                assert replay.result_bytes==answer.result_bytes and turns(f)==before==2
    asyncio.run(scenario())


def test_current_refs_prompt_role_and_source_substitution_cannot_admit_or_resend(tmp_path,monkeypatch):
    async def scenario():
        async with review_case(tmp_path,monkeypatch) as f:
            source=f['review_source']; locator=f['locator']; plan=f['review_plan']; request=f['review_request']
            variants=[replace(locator,plan_digest=Digest('sha256','0'*64)),replace(locator,fence=locator.fence+1),
                replace(locator,assignment_ref=replace(locator.assignment_ref,assignment_id='foreign-assignment')),
                replace(locator,author_execution_ref=replace(locator.author_execution_ref,source_revision='foreign-source')),
                replace(locator,reviewer_execution_ref=replace(locator.reviewer_execution_ref,operation_ref='foreign-operation'))]
            changed=decode_json(f['env'].blobs.read_verified(locator.params_ref)); changed['prompt'][0]['text']+=' '
            variants.append(replace(locator,params_ref=blob(f,changed)))
            with f['access'].admit(f['caller'],f['wire'],'engineering.reviews.record',request_id='verify-mutated',trace_id='review') as ctx:
                for variant in variants:
                    ref=blob(f,variant.projection())
                    with pytest.raises(ApplicationError):source.verify_response(ctx,plan,request,ref,standard=f['review_standard'])
                assert turns(f)==2
                f['native'].authority.read=False
                for _ in range(2):
                    with pytest.raises(Exception):source.verify_response(ctx,plan,request,f['raw_ref'],standard=f['review_standard'])
                f['native'].authority.read=True
                path=f['env'].project/'trial-candidate.md'; original=path.read_bytes();path.write_bytes(b'controlled changed source')
                try:
                    with pytest.raises(ApplicationError,match='SOURCE_CONTENT_MISMATCH'):
                        source.verify_response(ctx,plan,request,f['raw_ref'],standard=f['review_standard'])
                finally:path.write_bytes(original)
            with f['access'].admit(f['caller'],f['wire'],'engineering.reviews.revoke_reviewer',request_id='revoke-independent',trace_id='review') as ctx:
                f['assignments'].revoke_reviewer(ctx,assignment_ref=f['assignment'].ref,expected_control_version=0,reason='controlled role withdrawn')
            with f['access'].admit(f['caller'],f['wire'],'engineering.reviews.record',request_id='verify-revoked',trace_id='review') as ctx:
                for _ in range(2):
                    with pytest.raises(ApplicationError):source.verify_response(ctx,plan,request,f['raw_ref'],standard=f['review_standard'])
            assert turns(f)==2
            assert f['env'].library._connection.execute('SELECT count(*) FROM eng_reviews').fetchone()[0]==1 # original source review only
    asyncio.run(scenario())


def test_unknown_original_review_turn_is_not_retried_or_promoted(tmp_path,monkeypatch):
    async def scenario():
        async with review_case(tmp_path,monkeypatch,'native-unknown') as f:
            with f['access'].admit(f['caller'],f['wire'],'engineering.reviews.record',request_id='unknown-independent',trace_id='review') as ctx:
                for _ in range(2):
                    with pytest.raises(ApplicationError):
                        f['review_source'].verify_response(ctx,f['review_plan'],f['review_request'],f['raw_ref'],standard=f['review_standard'])
            assert turns(f)==2
            with f['factory'].begin(SCOPE,'read') as uow:
                assert uow.reviews.get_request(f['review_plan'].review_id).state=='requested'
    asyncio.run(scenario())


def test_prepared_then_real_role_revocation_refuses_actual_sdk_frame(tmp_path,monkeypatch):
    async def scenario():
        async with review_case(tmp_path,monkeypatch,'revoked-before-cut') as f:
            assert turns(f)==2  # Author turn plus the original reserved/unknown review.
            assert len(f['cut_calls'])==1
            assert f['physical_frames'].read_text().splitlines()==['frame']  # Author only; zero review frame.
            with f['factory'].begin(SCOPE,'read') as uow:
                assert uow.reviewer_assignments.control(f['assignment'].ref).state=='revoked'
                assert uow.reviews.get_request(f['review_plan'].review_id).state=='requested'
            assert f['env'].library._connection.execute('SELECT count(*) FROM eng_reviews').fetchone()[0]==1
    asyncio.run(scenario())

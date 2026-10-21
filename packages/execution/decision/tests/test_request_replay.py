"""Original decision execution claim is distinct from artifact byte idempotence."""
import asyncio,json
from dataclasses import replace
from types import SimpleNamespace
import pytest
from ordessa_decision.capability import build_capability
from ordessa_decision.runner import DecisionRunner
from ordessa_decision.evidence import EvidenceScope
from ordessa_decision.definitions.values import digest_hex
from test_capability import settings,job
from test_scoped_evidence import Authority


def setup(tmp_path, *, explode=False):
    config=settings(tmp_path);authority=Authority();alice=authority.issue('alice');calls=[]
    class Runner:
        async def run_async(self,raw):
            calls.append(raw['job_id'])
            if explode:raise ConnectionError('controlled uncertain execution')
            return await DecisionRunner(default_engine=config.default_engine).run_async(raw)
    config=replace(config,runner_factory=lambda **kwargs:Runner())
    cap=build_capability(config,invocation_resolver=authority.invocation,evidence_scope_resolver=authority.scope)
    return config,cap,authority,alice,calls


def test_same_request_replays_original_result_and_changed_input_conflicts(tmp_path):
    config,cap,authority,alice,calls=setup(tmp_path)
    async def call(body):return await cap.handlers['decisions.run']({'job':body},alice)
    first=asyncio.run(call(job()));second=asyncio.run(call(job()))
    assert first==second and first.status=='completed' and calls==['cap-job']
    conflict=asyncio.run(call(job(job_id='changed')))
    assert conflict.status=='refused' and conflict.error.code=='CONFLICT' and calls==['cap-job']
    assert first.operation_ref.startswith('decision-run/')
    # Another current principal with same request id is a different original
    # owner namespace; its run does not adopt or overwrite A's request/result.
    bob=authority.issue('bob')
    other=asyncio.run(cap.handlers['decisions.run']({'job':job()},bob))
    assert other.status=='completed' and other.operation_ref!=first.operation_ref and len(calls)==2


def test_crash_reserved_reopen_is_unknown_without_second_runner_or_model(tmp_path):
    config,cap,authority,alice,calls=setup(tmp_path,explode=True)
    with pytest.raises(ConnectionError):asyncio.run(cap.handlers['decisions.run']({'job':job()},alice))
    cold=build_capability(config,invocation_resolver=authority.invocation,evidence_scope_resolver=authority.scope)
    result=asyncio.run(cold.handlers['decisions.run']({'job':job()},alice))
    assert result.status=='unknown' and result.error.code=='EFFECT_UNKNOWN' and calls==['cap-job']


def test_concurrent_same_request_uses_one_original_claim(tmp_path):
    config,cap,authority,alice,calls=setup(tmp_path)
    async def scenario():
        return await asyncio.gather(*(cap.handlers['decisions.run']({'job':job()},alice) for _ in range(5)))
    results=asyncio.run(scenario())
    assert calls==['cap-job'] and all(result.status in ('completed','unknown') for result in results)
    assert len({r.operation_ref for r in results})==1


def test_corrupted_original_claim_or_result_never_runs_again(tmp_path):
    config,cap,authority,alice,calls=setup(tmp_path)
    first=asyncio.run(cap.handlers['decisions.run']({'job':job()},alice));assert first.status=='completed'
    root=config.evidence.scoped(EvidenceScope('principal','alice')).root
    result_path=next(root.glob('.run-result-*.json'));result_path.write_bytes(b'corrupt')
    result=asyncio.run(cap.handlers['decisions.run']({'job':job()},alice))
    assert result.status=='unknown' and calls==['cap-job']


def _process_run(root,write_fd,started,release,queue,identity):
    import os
    config=settings(root);authority=Authority();alice=authority.issue('alice')
    class Runner:
        async def run_async(self,raw):
            os.write(write_fd,b'one-original-run\n');started.set()
            assert release.wait(5)  # only this isolated controlled child blocks
            return await DecisionRunner(default_engine=config.default_engine).run_async(raw)
    config=replace(config,runner_factory=lambda **kwargs:Runner())
    cap=build_capability(config,invocation_resolver=authority.invocation,evidence_scope_resolver=authority.scope)
    result=asyncio.run(cap.handlers['decisions.run']({'job':job()},alice))
    queue.put((identity,result.status,result.operation_ref))


def test_two_processes_share_one_original_run_claim_and_cold_result(tmp_path):
    import multiprocessing,os
    context=multiprocessing.get_context('fork');started=context.Event();release=context.Event();queue=context.Queue()
    read_fd,write_fd=os.pipe();workers=[]
    try:
        first=context.Process(target=_process_run,args=(tmp_path,write_fd,started,release,queue,'first'))
        workers.append(first);first.start();assert started.wait(5)
        second=context.Process(target=_process_run,args=(tmp_path,write_fd,started,release,queue,'second'))
        workers.append(second);second.start();second.join(5);assert second.exitcode==0
        second_result=queue.get(timeout=2);assert second_result[:2]==('second','unknown')
        release.set();first.join(5);assert first.exitcode==0
        first_result=queue.get(timeout=2);assert first_result[:2]==('first','completed')
        assert first_result[2]==second_result[2]
        assert os.read(read_fd,65536)==b'one-original-run\n'
        config,cap,authority,alice,calls=setup(tmp_path)
        replay=asyncio.run(cap.handlers['decisions.run']({'job':job()},alice))
        assert replay.status=='completed' and replay.operation_ref==first_result[2] and calls==[]
    finally:
        release.set()
        for worker in workers:
            worker.join(5)
            if worker.is_alive():worker.terminate();worker.join(2)
        os.close(read_fd);os.close(write_fd);queue.close()


def test_run_grant_cannot_read_original_result_after_history_read_revocation(tmp_path):
    config,cap,authority,alice,calls=setup(tmp_path)
    original=asyncio.run(cap.handlers['decisions.run']({'job':job()},alice));assert original.status=='completed'
    authority.denied.add(('alice','decisions.get'));authority.denied.add(('alice','decisions.evidence'))
    replay=asyncio.run(cap.handlers['decisions.run']({'job':job()},alice))
    assert replay.status=='refused' and replay.error.code=='PERMISSION_DENIED'
    assert replay.data is None and replay.evidence_refs==() and calls==['cap-job']


def test_orphaned_result_never_creates_replacement_claim_or_runs_again(tmp_path):
    config,cap,authority,alice,calls=setup(tmp_path)
    first=asyncio.run(cap.handlers['decisions.run']({'job':job()},alice));assert first.status=='completed'
    root=config.evidence.scoped(EvidenceScope('principal','alice')).root
    claim=next(p for p in root.glob('.run-*.json') if not p.name.startswith('.run-result-'))
    result_path=next(root.glob('.run-result-*.json'));original=result_path.read_bytes();claim.unlink()
    replay=asyncio.run(cap.handlers['decisions.run']({'job':job()},alice))
    assert replay.status=='unknown' and calls==['cap-job']
    assert not claim.exists() and result_path.read_bytes()==original


def test_canonical_result_payload_tamper_fails_original_digest_without_rerun(tmp_path):
    from ordessa_decision.definitions.values import canonical_bytes
    config,cap,authority,alice,calls=setup(tmp_path)
    first=asyncio.run(cap.handlers['decisions.run']({'job':job()},alice));assert first.status=='completed'
    root=config.evidence.scoped(EvidenceScope('principal','alice')).root
    path=next(root.glob('.run-result-*.json'));record=json.loads(path.read_bytes())
    record['result']['data']['result']=999;path.write_bytes(canonical_bytes(record))
    replay=asyncio.run(cap.handlers['decisions.run']({'job':job()},alice))
    assert replay.status=='unknown' and replay.data is None and calls==['cap-job']

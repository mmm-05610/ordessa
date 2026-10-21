"""Original decision owner namespaces: hashes are data, never read authority."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from types import SimpleNamespace
import pytest

from ordessa_decision.evidence import EvidenceScope,FilesystemEvidenceStore
from ordessa_decision.definitions.values import DecisionError,canonical_bytes
from ordessa_decision.capability import build_capability
from test_capability import settings,job


class Authority:
    def __init__(self):self.tokens=[];self.denied=set();self.operations=[]
    def issue(self,subject):
        token=SimpleNamespace(subject=subject,request_id='controlled-request');self.tokens.append(token);return token
    def invocation(self,context):
        if not any(context is token for token in self.tokens):raise PermissionError()
        return context
    def scope(self,invocation,operation):
        self.invocation(invocation);self.operations.append(operation)
        if (invocation.subject,operation) in self.denied:raise PermissionError()
        return EvidenceScope('principal',invocation.subject)


def test_two_authenticated_callers_cannot_read_or_write_each_others_original_namespace(tmp_path):
    config=settings(tmp_path);authority=Authority();alice=authority.issue('alice');bob=authority.issue('bob')
    cap=build_capability(config,invocation_resolver=authority.invocation,evidence_scope_resolver=authority.scope)
    async def call(op,request,who):return await cap.handlers['decisions.'+op](request,who)
    ran=asyncio.run(call('run',{'job':job()},alice));assert ran.status=='completed'
    digest=ran.data['evidence']['digest'];owned=config.evidence.scoped(EvidenceScope('principal','alice'))
    before={p.name:p.read_bytes() for p in owned.root.iterdir()}
    for op in ('get','evidence'):
        assert asyncio.run(call(op,{'digest':digest},bob)).status=='refused'
        assert asyncio.run(call(op,{'digest':digest},alice)).status=='completed'
    # Same summary/hash in B's own scope never adopts A's object or metadata.
    bob_run=asyncio.run(call('run',{'job':job()},bob))
    assert bob_run.status=='completed' and bob_run.data['evidence']['digest']==digest
    assert asyncio.run(call('get',{'digest':digest},bob)).status=='completed'
    assert before=={p.name:p.read_bytes() for p in owned.root.iterdir()}
    authority.denied.add(('alice','decisions.evidence'))
    denied=asyncio.run(call('evidence',{'digest':digest},alice))
    assert denied.status=='refused' and denied.error.code=='PERMISSION_DENIED'
    assert asyncio.run(call('get',{'digest':digest},SimpleNamespace(subject='alice'))).status=='refused'
    assert 'decisions.evidence' in authority.operations
    assert not (config.evidence.root/(digest+'.json')).exists()


def test_scope_must_be_supplied_before_runner_or_unbound_store_access(tmp_path):
    config=settings(tmp_path);calls=[]
    config.evidence.put=lambda summary:calls.append('unbound-put')
    config.evidence.get=lambda digest:calls.append('unbound-get')
    cap=build_capability(config)
    for operation,request in [('run',{'job':job()}),('get',{'digest':'a'*64}),('evidence',{'digest':'a'*64})]:
        result=asyncio.run(cap.handlers['decisions.'+operation](request,object()))
        assert result.status=='refused' and result.error.code=='AUTHORITY_UNAVAILABLE'
    assert calls==[] and list(config.evidence.root.iterdir())==[]


def test_scope_metadata_concurrent_creation_tampering_and_historical_bytes(tmp_path):
    store=FilesystemEvidenceStore(tmp_path/'original');summary={'job_digest':'a'*64}
    old=store.put(summary);old_path=store.root/(old.digest+'.json');original=old_path.read_bytes()
    scope=EvidenceScope('project','existing-project/ref')
    view=store.scoped(scope)
    with pytest.raises(DecisionError):view.get(old.digest)  # no historical adoption/fallback
    assert not view.root.exists()
    with ThreadPoolExecutor(max_workers=4) as executor:
        refs=list(executor.map(lambda _:store.scoped(scope).put(summary),range(8)))
    assert all(ref.digest==old.digest for ref in refs)
    assert view.get(old.digest)==summary and old_path.read_bytes()==original
    metadata=view.root/'.scope.json';metadata.write_bytes(canonical_bytes(EvidenceScope('principal','foreign').projection()))
    damaged=metadata.read_bytes()
    for effect in (lambda:view.get(old.digest),lambda:view.put(summary)):
        with pytest.raises(DecisionError,match='evidence_scope_invalid'):effect()
    assert metadata.read_bytes()==damaged and old_path.read_bytes()==original


def test_exact_digest_validation_precedes_scope_or_path_io(tmp_path):
    store=FilesystemEvidenceStore(tmp_path/'original').scoped(EvidenceScope('principal','alice'))
    for value in ('A'*64,'../'+'a'*61,'a'*63+'/', '\x00'*64):
        with pytest.raises(DecisionError,match='invalid_evidence_ref'):store.get(value)
    assert not store.root.exists()
    for kind,ref in [('new-owner','a'),('principal',''),('project','x\n')]:
        with pytest.raises(DecisionError):EvidenceScope(kind,ref)


def test_scope_revoked_during_await_never_writes_under_new_or_unbound_owner(tmp_path):
    from ordessa_decision.settings import DecisionsSettings
    from ordessa_decision.runner import DecisionRunner
    from test_capability import Engine
    authority=Authority();alice=authority.issue('alice');calls=[];store=FilesystemEvidenceStore(tmp_path/'original')
    class Runner:
        async def run_async(self,raw):
            calls.append('run')
            result=await DecisionRunner(default_engine=Engine(),engines={},provider=None).run_async(raw)
            authority.denied.add(('alice','decisions.run'))
            return result
    config=DecisionsSettings(runner_factory=lambda **kwargs:Runner(),evidence=store)
    cap=build_capability(config,invocation_resolver=authority.invocation,evidence_scope_resolver=authority.scope)
    result=asyncio.run(cap.handlers['decisions.run']({'job':job()},alice))
    assert result.status=='unknown' and result.error.code=='EFFECT_UNKNOWN'
    assert calls==['run']
    owned=store.scoped(EvidenceScope('principal','alice')).root
    assert len(list(owned.glob('.run-*.json')))==1  # pre-effect claim stays unresolved
    assert list(owned.glob('.run-result-*.json'))==[]
    assert [p for p in owned.iterdir() if not p.name.startswith('.')]==[]


def test_scoped_reads_and_writes_reject_cross_subject_symlink_files_and_directories(tmp_path):
    store=FilesystemEvidenceStore(tmp_path/'original');alice=store.scoped(EvidenceScope('principal','alice'))
    bob=store.scoped(EvidenceScope('principal','bob'));summary={'job_digest':'b'*64};ref=bob.put(summary)
    alice.put({'job_digest':'a'*64})
    linked=alice.root/(ref.digest+'.json');linked.symlink_to(bob.root/(ref.digest+'.json'))
    for action in (lambda:alice.get(ref.digest),lambda:alice.put(summary)):
        with pytest.raises(DecisionError):action()
    linked.unlink()
    # Metadata and namespace directory links are refused too, before reading any artifact.
    metadata=alice.root/'.scope.json';saved=metadata.read_bytes();metadata.unlink();metadata.symlink_to(bob.root/'.scope.json')
    with pytest.raises(DecisionError):alice.get(ref.digest)
    metadata.unlink();metadata.write_bytes(saved)
    original=alice.root.with_name(alice.root.name+'-moved');alice.root.rename(original);alice.root.symlink_to(bob.root,target_is_directory=True)
    for action in (lambda:alice.get(ref.digest),lambda:alice.put(summary)):
        with pytest.raises(DecisionError):action()
    assert bob.get(ref.digest)==summary


def test_corrupt_scope_storage_is_rejected_before_any_runner_or_model_work(tmp_path):
    config=settings(tmp_path);authority=Authority();alice=authority.issue('alice')
    owned=config.evidence.scoped(EvidenceScope('principal','alice'))
    owned.verify_scope(for_write=True)
    (owned.root/'.scope.json').write_bytes(b'corrupt')
    cap=build_capability(config,invocation_resolver=authority.invocation,evidence_scope_resolver=authority.scope)
    result=asyncio.run(cap.handlers['decisions.run']({'job':job()},alice))
    assert result.status=='refused' and result.error.code=='PERMISSION_DENIED'
    assert list(owned.root.iterdir())==[owned.root/'.scope.json']


def test_first_scoped_write_syncs_parent_directory_entries_and_refuses_sync_failure(tmp_path,monkeypatch):
    import os,stat
    store=FilesystemEvidenceStore(tmp_path/'original');view=store.scoped(EvidenceScope('principal','alice'))
    real=os.fsync;synced=set()
    def sync(fd):
        facts=os.fstat(fd)
        if stat.S_ISDIR(facts.st_mode):synced.add((facts.st_dev,facts.st_ino))
        return real(fd)
    monkeypatch.setattr(os,'fsync',sync)
    assert view.put({'job_digest':'a'*64}).durability=='durable'
    for path in (store.root.parent,store.root,store.root/'scopes',view.root):
        facts=path.stat();assert (facts.st_dev,facts.st_ino) in synced
    other=store.scoped(EvidenceScope('principal','bob'));parent=store.root.stat()
    def failing(fd):
        facts=os.fstat(fd)
        if (facts.st_dev,facts.st_ino)==(parent.st_dev,parent.st_ino):raise OSError('parent sync failed')
        return real(fd)
    monkeypatch.setattr(os,'fsync',failing)
    with pytest.raises(DecisionError):other.put({'job_digest':'b'*64})
    assert not other.root.exists()

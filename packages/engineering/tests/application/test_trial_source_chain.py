"""New immutable declaration/material identity; controlled finite preflight only."""
import asyncio
from copy import deepcopy
from dataclasses import asdict
from hashlib import sha256
import importlib.util
import json
from pathlib import Path

import pytest
from decision_runtime import DecisionAnswer, FileEvidenceReader, ReadContext
from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.domain.reviews.ref_codec import decode_review_ref
from test_real_source_chain import (ROOT, SCOPE, ControlledDecisionProvider,
    build_local_chain, close_chain, create_proposal, request_and_run_review,
    associate_and_freeze, run_full_chain)


EVIDENCE = ROOT/'docs/implementation/packages-convergence-20261012/engineering/real-source-chain-20261014'
TRIAL = EVIDENCE/'positive-validation'
METHOD = ROOT/'methods/incremental-engineering/candidates/2.7.1'


def trial_entries():
    manifest = json.loads((TRIAL/'INPUT-MANIFEST.json').read_text())
    assert manifest['scope'] == asdict(SCOPE)
    entries = []
    for logical, version, name in (
        ('trial-source-mapping-DID','trial-baseline-v1','trial-baseline.md'),
        ('trial-source-mapping-DID','trial-candidate-v2','trial-candidate.md'),
        ('trial-spec','trial-spec-v1','spec.md'),
        ('trial-plan','trial-plan-v1','plan.md'),
        ('trial-tasks','trial-tasks-v1','tasks.md'),
    ):
        raw = (TRIAL/'materials'/name).read_bytes()
        pin = manifest['materials']['materials/'+name]
        assert len(raw) == pin['byte_length'] and sha256(raw).hexdigest() == pin['sha256']
        entries.append((logical,version,name,raw))
    return tuple(entries)


def build_trial_chain(directory, *, answer='passed', provider=None):
    entries = trial_entries()
    selected = provider or ControlledDecisionProvider(answer,
        expected_sources=(entries[0][3], entries[1][3]))
    return build_local_chain(directory, selected, method_directory=METHOD,
                             material_entries=entries)


def test_new_method_identity_preserves_quality_and_strict_release_binding():
    old = ROOT/'methods/incremental-engineering/candidates/2.7.0'
    before, after = (json.loads((p/'method.json').read_text()) for p in (old,METHOD))
    expected = deepcopy(before)
    expected['release_version'] = '2.7.1'
    changed = set()
    for ref in expected['resources']:
        old_raw, new_raw = ((p/ref['path']).read_bytes() for p in (old,METHOD))
        assert sha256(old_raw).hexdigest() == ref['sha256']
        if old_raw != new_raw:
            changed.add(ref['id'])
            ref['sha256'] = sha256(new_raw).hexdigest()
    assert changed == {'change-review-criteria','package-result-schema'}
    assert expected == after
    assert (old/'criteria/change-review.md').read_text().split('\n\n')[2:] == (
        METHOD/'criteria/change-review.md').read_text().split('\n\n')[2:]
    old_schema = json.loads((old/'schemas/package-result.schema.json').read_text())
    old_schema['properties']['release_version']['const'] = '2.7.1'
    assert old_schema == json.loads((METHOD/'schemas/package-result.schema.json').read_text())
    assert (old/'criteria/source-review.json').read_bytes() == (METHOD/'criteria/source-review.json').read_bytes()
    assert b'did-baseline-v1' not in (METHOD/'criteria/change-review.md').read_bytes()


def test_trial_positive_service_chain_and_original_native_cold_read(tmp_path):
    env = build_trial_chain(tmp_path)
    try:
        assert env.method.release_version == '2.7.1'
        assert env.baseline.locator == env.candidate.locator
        assert env.baseline.source_id == env.candidate.source_id == 'trial-source-mapping-DID'
        result = run_full_chain(env)
        assert result.package.payload.baseline == env.baseline
        assert result.package.payload.candidate == env.candidate
        assert {d.role for d in result.package.payload.documents} == {'spec','plan','tasks'}
        native_root = tmp_path/'decision-runs'
        asyncio.run(env.sink.close())
        async def cold():
            ctx = ReadContext(object(), 'trial-controlled-cold')
            reader = FileEvidenceReader(native_root,read_context=ctx)
            try:return await reader.read(result.receipt['run_id'],ctx)
            finally:await reader.close()
        native = asyncio.run(cold())
        assert native['status'] == 'completed' and native['call_evidence'] == 'recorded'
        assert native['terminal']['result']['request_id'] == env.plan.review_id+':1'
        assert len(env.services.decision_provider.questions) == 1
    finally:
        close_chain(env)


@pytest.mark.parametrize('answer', ('not_passed','unknown'))
def test_trial_nonpass_never_produces_package(tmp_path, answer):
    env = build_trial_chain(tmp_path, answer=answer)
    try:
        proposal_ref = create_proposal(env)
        _, recorded, _ = request_and_run_review(env)
        assert recorded.result['verdict'] != 'pass'
        review_ref = decode_review_ref(recorded.result['review_ref'])
        with pytest.raises(ApplicationError, match='PROPOSAL_REVIEW_ASSOCIATION_INVALID'):
            associate_and_freeze(env,proposal_ref,review_ref)
        assert env.library._connection.execute('SELECT count(*) FROM eng_packages').fetchone()[0] == 0
    finally:
        close_chain(env)


def _probe():
    path = EVIDENCE/'run_live_source_chain.py'
    spec = importlib.util.spec_from_file_location('bounded_source_probe',path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_provider_close_diagnostics_do_not_record_exception_text():
    probe = _probe()
    marker = 'sensitive-error-text-must-not-be-recorded'
    class Provider:
        async def close(self):
            raise RuntimeError(marker)
    result = asyncio.run(probe.close_provider_safely(Provider(),stage='call-loop'))
    assert result == {'stage':'call-loop','attempted':True,'succeeded':False,
                      'exception_type':'RuntimeError','errno':None}
    assert marker not in json.dumps(result)
    class Success:
        async def close(self):
            return None
    assert asyncio.run(probe.close_provider_safely(Success(),stage='call-loop')) == {
        'stage':'call-loop','attempted':True,'succeeded':True}


def test_native_completion_is_retained_when_engineering_source_verification_refuses(tmp_path):
    entries = trial_entries()
    class MismatchedReceipt(ControlledDecisionProvider):
        async def decide(self,question,ctx):
            answer = await super().decide(question,ctx)
            return DecisionAnswer(answer.question_id,answer.kind,answer.value,
                                  {'question_digest':'sha256:'+'f'*64})
    provider = MismatchedReceipt(expected_sources=(entries[0][3],entries[1][3]))
    env = build_trial_chain(tmp_path,provider=provider)
    try:
        with pytest.raises(ApplicationError,match='UNTRUSTED_REVIEWER') as refused:
            request_and_run_review(env)
        assert refused.value.decision_status == 'completed'
        native = asyncio.run(env.sink.read(refused.value.decision_run_id,env.services.read_context))
        assert native['status'] == 'completed'
        assert env.library._connection.execute('SELECT count(*) FROM eng_reviews').fetchone()[0] == 0
        assert env.library._connection.execute('SELECT count(*) FROM eng_packages').fetchone()[0] == 0
    finally:
        close_chain(env)

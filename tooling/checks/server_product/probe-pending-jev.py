"""One explicitly authorized real Zen call over an isolated original work.

This controlled DID/authority fixture does not authenticate a human or issue
an implementation Grant. Existing output directories refuse before any HTTP;
recover the original Decision evidence instead of rerunning an unknown call.
"""
import argparse
import asyncio
from dataclasses import asdict
import hashlib
import importlib.util
import json
from pathlib import Path
import time

import httpx2
from ordessa_decision.definitions import PolicyRef, ReadContext, digest, plain
from ordessa_decision.evidence import FileEvidenceSink
from ordessa_decision_jev import JevDecisionProvider, JevProviderSettings
from ordessa_server.composition.engineering_reviewer_source import (
    OriginalJevReviewerSource, encode_review_run,
)
from ordessa_server.composition.temporary_process_capability import ExistingOpenCodeInput

ENDPOINT = 'https://opencode.ai/zen/v1/systemone'
ROOT = Path(__file__).resolve().parents[3]


class SingleRequestTransport(httpx2.AsyncBaseTransport):
    def __init__(self):
        self.inner = httpx2.AsyncHTTPTransport(retries=0)
        self.requests = []

    async def handle_async_request(self, request):
        if str(request.url) != ENDPOINT or request.method != 'POST' or self.requests:
            raise RuntimeError('AUTHORIZED_SINGLE_REQUEST_EXCEEDED')
        row = {'method':'POST', 'endpoint':ENDPOINT,
            'body_sha256':hashlib.sha256(request.content).hexdigest()}
        self.requests.append(row)
        started = time.monotonic()
        try:
            response = await self.inner.handle_async_request(request)
            row['http_status'] = response.status_code
            return response
        finally:
            row['seconds_to_headers'] = round(time.monotonic() - started, 4)

    async def aclose(self):
        await self.inner.aclose()


def _save(path, value):
    path.write_text(json.dumps(plain(value), ensure_ascii=False, indent=2) + '\n')


async def qualify(args):
    if not args.authorize_live:
        raise RuntimeError('EXPLICIT_LIVE_AUTHORIZATION_REQUIRED')
    # Exclusive creation is a probe guard, not a second business journal.
    args.output.mkdir(mode=0o700, parents=False, exist_ok=False)
    receipt = {'phase':'preparing', 'new_http_requests':0, 'quality':'manual',
        'human_confirmed':False, 'grant':False, 'formal_review_record':False,
        'controlled_fixture':True, 'replay':False}
    _save(args.output / 'probe-phase.json', receipt)
    helper_path = ROOT / 'tests/fixtures/engineering/jev_pending_work.py'
    spec = importlib.util.spec_from_file_location('pending_jev_fixture', helper_path)
    if spec is None or spec.loader is None:
        raise RuntimeError('ORIGINAL_WORK_FIXTURE_UNAVAILABLE')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    work = None
    provider = sink = None
    secret = bytearray()
    transport = SingleRequestTransport()
    try:
        work = module.build_original_pending_work(args.output / 'work')
        policy = PolicyRef('controlled.pending-jev-policy', '1',
            digest('policy', {'requirement':work['plan'].requirement.digest.hex}))
        with work['admitted']('engineering.reviewer.jev', 'live-prepare') as context:
            prepared = work['work'].prepare(context, work['plan'].review_id, policy)
        # Refuse before credentials/network when the original capture predicate
        # is absent, even if input preparation alone succeeds.
        work['work']._capture_reads(prepared)
        if len(prepared.questions) != 1:
            raise RuntimeError('AUTHORIZED_SINGLE_QUESTION_REQUIRED')
        (args.output / 'input-receipt.json').write_bytes(prepared.receipt_bytes)
        settings = JevProviderSettings(binding_ref='ordessa.product.pending-jev/1',
            secret_ref='opencode_zen', base_url='https://opencode.ai/zen',
            model='jev-1.13-free', accepted_response_models=('jev-1.13-free',),
            timeout_seconds=20.0)
        secret = ExistingOpenCodeInput(args.credential_source).read()
        provider = JevDecisionProvider(settings,
            secret_resolver=lambda _: secret.decode('ascii'), transport=transport)
        read_context = ReadContext(object(), 'authorized-single-pending-jev')
        (args.output / 'durable').mkdir(mode=0o700)
        sink = FileEvidenceSink(args.output / 'durable', read_context=read_context)
        request_id = 'pending-jev-' + args.output.name
        receipt.update(phase='dispatching', decision_request_id=request_id,
            review_id=prepared.plan.review_id, request_version=prepared.request.version,
            request_fence=prepared.request.fence,
            plan_digest=asdict(prepared.plan.plan_digest),
            input_receipt_sha256=hashlib.sha256(prepared.receipt_bytes).hexdigest())
        _save(args.output / 'probe-phase.json', receipt)
        with work['admitted']('engineering.reviewer.jev', 'live-run') as context:
            run, flow, result = await work['work'].run(context, prepared,
                provider=provider, evidence_sink=sink, read_context=read_context,
                request_id=request_id, task_revision='1',
                review_ref='parent-authorized-pending-jev', wall_timeout_seconds=35)
        # Save actual completed bytes before business capture. A later failure
        # must preserve this result and may never trigger another model call.
        (args.output / 'raw-source.json').write_bytes(encode_review_run(run))
        _save(args.output / 'decision-result.json', result)
        receipt.update(phase='decision-completed-awaiting-capture', run_id=run.run_id,
            new_http_requests=len(transport.requests))
        _save(args.output / 'probe-phase.json', receipt)
        source = OriginalJevReviewerSource(access=work['access'],
            scope=work['server_scope'], blobs=work['blobs'], evidence_reader=sink,
            read_context=read_context, provider=provider, runs=(run,),
            roles=('reviewer',), accepted_models=('jev-1.13-free',), flows=(flow,))
        with work['admitted']('engineering.artifacts.create', 'live-capture') as context:
            captured = work['work'].capture(context, prepared, run, source=source)
        with work['factory'].begin(prepared.plan.scope, 'read') as uow:
            request = uow.reviews.get_request(prepared.plan.review_id)
        receipt.update(phase='pending-evidence-committed', artifact_result=captured.result,
            request_after=asdict(request), new_http_requests=len(transport.requests))
        _save(args.output / 'probe-phase.json', receipt)
    except Exception as error:
        original = getattr(error, 'decision_result', None)
        if original is not None:
            _save(args.output / 'decision-result.json', original)
            receipt['decision_status'] = original.status
            receipt['run_id'] = original.run_id
        receipt.update(failure_code=getattr(error, 'code', type(error).__name__),
            new_http_requests=len(transport.requests), replay_forbidden=True)
        _save(args.output / 'probe-phase.json', receipt)
        raise
    finally:
        _save(args.output / 'http-audit.json', {'requests':transport.requests, 'max_requests':1,
            'retries':0, 'paid_fallback':False})
        if provider is not None:
            await provider.close()
        else:
            await transport.aclose()
        if sink is not None:
            await sink.close()
        if work is not None:
            work['library'].close()
        if secret:
            # Never persist or print the credential; check all retained bytes.
            leaked = any(bytes(secret) in p.read_bytes()
                for p in args.output.rglob('*') if p.is_file())
            for i in range(len(secret)):
                secret[i] = 0
            if leaked:
                raise RuntimeError('CREDENTIAL_RETENTION_REFUSED')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--authorize-live', action='store_true')
    parser.add_argument('--credential-source', required=True)
    parser.add_argument('--output', type=Path, required=True)
    arguments = parser.parse_args()
    try:
        asyncio.run(qualify(arguments))
    except Exception as error:
        print('pending JEV probe ended:', getattr(error, 'code', type(error).__name__))
        raise SystemExit(1)
    print('pending JEV evidence committed; quality remains manual')

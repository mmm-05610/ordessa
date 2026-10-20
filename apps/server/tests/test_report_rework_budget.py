"""Request-before-spend and one-window tests; no external model or real library."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from multiprocessing import get_context
from types import SimpleNamespace
from uuid import uuid4
from hashlib import sha256
import json
import pytest

from ordessa_server.composition.report_rework_budget import (
    ReportReworkBudget, ReportReworkBudgetRefused, RESERVATION_NANODOLLARS,
)


def prepared(tmp_path):
    now = [datetime(2026, 10, 18, 14, tzinfo=timezone.utc)]
    authority = ReportReworkBudget(tmp_path / 'budget.json', plan_digest='a' * 64,
                                    clock=lambda: now[0]).start()
    for role, pid in [('report', 101), ('review', 102)]:
        config = authority.phase_config(role, pi_ai_module='file:///module.js',
            module_sha256='b' * 64, extension_sha256='c' * 64)
        profile = tmp_path / role
        profile.mkdir()
        authority.receive('/ready', dict(contract='ordessa.pi.request-budget.ready/1',
            plan_digest='a' * 64, role=role, phase_id=config['phase_id'], pid=pid,
            profile=str(profile), provider='deepseek', model='deepseek-flash',
            api='openai-completions', registered=True))
    return authority, now


def reserve(authority, role):
    return authority.receive('/reserve', dict(
        contract='ordessa.pi.request-budget.reserve/1', plan_digest='a' * 64,
        role=role, phase_id=authority.configuration(role)['phase_id'],
        pid=101 if role == 'report' else 102, request_id=str(uuid4()),
        provider='deepseek', model='deepseek-flash', request_bytes=120000,
        max_input_tokens=1000000, max_output_tokens=16384, reserved_usd='0.3196608'))


def confirmed_report_ledger(tmp_path, *, now=None):
    tmp_path.mkdir(parents=True, exist_ok=True)
    current = [now or datetime(2026, 10, 18, 14, tzinfo=timezone.utc)]
    path = tmp_path / 'resume-budget.json'
    authority = ReportReworkBudget(path, plan_digest='a' * 64,
        clock=lambda: current[0]).start()
    config = authority.phase_config('report', pi_ai_module='file:///module.js',
        module_sha256='b' * 64, extension_sha256='c' * 64)
    profile = tmp_path / 'report-profile'
    profile.mkdir()
    authority.receive('/ready', dict(contract='ordessa.pi.request-budget.ready/1',
        plan_digest='a' * 64, role='report', phase_id=config['phase_id'], pid=101,
        profile=str(profile), provider='deepseek', model='deepseek-flash',
        api='openai-completions', registered=True))
    reservation = reserve(authority, 'report')
    authority.receive('/usage', dict(contract='ordessa.pi.request-budget.usage/1',
        plan_digest='a' * 64, role='report', phase_id=config['phase_id'], pid=101,
        request_id=authority.snapshot()['reservations'][0]['request_id'],
        reservation_id=reservation['reservation_id'], provider='deepseek',
        model='deepseek-flash', input_tokens=100, output_tokens=20,
        cache_read_tokens=0, cache_write_tokens=0, total_tokens=120))
    authority.close()
    raw = path.read_bytes()
    return path, current, sha256(raw).hexdigest()


def _resume_worker(path, plan_digest, ledger_digest, started, release, result):
    try:
        authority = ReportReworkBudget.resume(path, plan_digest=plan_digest,
            ledger_digest=ledger_digest)
        result.put('ok')
        started.set()
        release.wait(5)
        authority.close()
    except ReportReworkBudgetRefused:
        result.put('refused')
        started.set()


def test_concurrent_roles_cannot_overspend_or_refund_unknown_sends(tmp_path):
    authority, _ = prepared(tmp_path)
    try:
        def attempt(i):
            try:
                reserve(authority, 'report' if i % 2 else 'review')
                return True
            except ReportReworkBudgetRefused:
                return False
        with ThreadPoolExecutor(max_workers=8) as pool:
            answers = list(pool.map(attempt, range(12)))
        assert sum(answers) == 3
        state = json.loads(authority.path.read_text())
        assert state['reserved_nanodollars'] == 3 * RESERVATION_NANODOLLARS < 1000000000
        assert len(state['reservations']) == 3 and state['usage'] == []
        with pytest.raises(ReportReworkBudgetRefused):
            ReportReworkBudget(authority.path, plan_digest='a' * 64)
    finally:
        authority.close()


def test_deadline_is_first_run_plus_90_minutes_and_never_refreshes(tmp_path):
    authority, now = prepared(tmp_path)
    try:
        reserve(authority, 'report')
        deadline = authority.expires_at
        now[0] += timedelta(minutes=90)
        with pytest.raises(ReportReworkBudgetRefused):
            reserve(authority, 'review')
        assert authority.expires_at == deadline
        assert len(authority.snapshot()['reservations']) == 1
    finally:
        authority.close()


def test_resume_preserves_original_ledger_and_allows_only_two_review_reservations(tmp_path):
    path, now, digest = confirmed_report_ledger(tmp_path)
    before = json.loads(path.read_text())
    resumed = ReportReworkBudget.resume(path, plan_digest='a' * 64,
        ledger_digest=digest, clock=lambda: now[0]).start()
    try:
        assert resumed.resumed_review_only is True
        assert resumed.plan_digest == before['plan_digest']
        assert resumed.not_before == before['not_before']
        assert resumed.expires_at == before['expires_at']
        assert resumed.snapshot()['reservations'] == before['reservations']
        assert resumed.snapshot()['usage'] == before['usage']
        with pytest.raises(ReportReworkBudgetRefused):
            resumed.phase_config('report', pi_ai_module='file:///module.js',
                module_sha256='b' * 64, extension_sha256='c' * 64)
        config = resumed.phase_config('review', pi_ai_module='file:///module.js',
            module_sha256='b' * 64, extension_sha256='c' * 64)
        profile = tmp_path / 'review-profile'
        profile.mkdir()
        resumed.receive('/ready', dict(contract='ordessa.pi.request-budget.ready/1',
            plan_digest='a' * 64, role='review', phase_id=config['phase_id'], pid=102,
            profile=str(profile), provider='deepseek', model='deepseek-flash',
            api='openai-completions', registered=True))
        assert reserve(resumed, 'review')['allowed'] is True
        assert reserve(resumed, 'review')['allowed'] is True
        with pytest.raises(ReportReworkBudgetRefused):
            reserve(resumed, 'review')
        state = resumed.snapshot()
        assert state['reserved_nanodollars'] == 3 * RESERVATION_NANODOLLARS < 1_000_000_000
        assert len(state['usage']) == 1
    finally:
        resumed.close()


def test_resume_rejects_wrong_digest_plan_tampering_expiry_and_used_review(tmp_path):
    path, now, digest = confirmed_report_ledger(tmp_path)
    with pytest.raises(ReportReworkBudgetRefused):
        ReportReworkBudget.resume(path, plan_digest='a' * 64, ledger_digest='0' * 64)
    with pytest.raises(ReportReworkBudgetRefused):
        ReportReworkBudget.resume(path, plan_digest='d' * 64, ledger_digest=digest)
    resumed = ReportReworkBudget.resume(path, plan_digest='a' * 64,
        ledger_digest=digest, clock=lambda: now[0])
    assert resumed.resumed_review_only is True
    resumed.close()
    # The successful resume above persists its one-time fence, so no subsequent
    # restoration can turn the same used allowance into a fresh review run.
    resumed_digest = sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ReportReworkBudgetRefused):
        ReportReworkBudget.resume(path, plan_digest='a' * 64, ledger_digest=resumed_digest)
    expired, expired_now, expired_digest = confirmed_report_ledger(
        tmp_path / 'expired', now=datetime(2026, 10, 18, 14, tzinfo=timezone.utc))
    expired_now[0] += timedelta(minutes=90)
    with pytest.raises(ReportReworkBudgetRefused):
        ReportReworkBudget.resume(expired, plan_digest='a' * 64,
            ledger_digest=expired_digest, clock=lambda: expired_now[0])


def test_resume_rejects_rehashed_tampering_and_unknown_report_send(tmp_path):
    path, _now, _digest = confirmed_report_ledger(tmp_path)
    state = json.loads(path.read_text())
    state['reserved_nanodollars'] = 0
    path.write_text(json.dumps(state, sort_keys=True))
    tampered_digest = sha256(path.read_bytes()).hexdigest()
    with pytest.raises(ReportReworkBudgetRefused):
        ReportReworkBudget.resume(path, plan_digest='a' * 64,
            ledger_digest=tampered_digest)

    unknown_path, _now, _digest = confirmed_report_ledger(tmp_path / 'unknown')
    unknown = json.loads(unknown_path.read_text())
    unknown['usage'] = []  # A reservation without confirmed usage is ambiguous.
    unknown_path.write_text(json.dumps(unknown, sort_keys=True))
    unknown_digest = sha256(unknown_path.read_bytes()).hexdigest()
    with pytest.raises(ReportReworkBudgetRefused):
        ReportReworkBudget.resume(unknown_path, plan_digest='a' * 64,
            ledger_digest=unknown_digest)

    review_path, _now, _digest = confirmed_report_ledger(tmp_path / 'review-ready')
    review_state = json.loads(review_path.read_text())
    review_phase_id = 'f' * 32
    review_state['phases']['review'] = {'phase_id': review_phase_id, 'ready': {
        'contract': 'ordessa.pi.request-budget.ready/1', 'plan_digest': 'a' * 64,
        'role': 'review', 'phase_id': review_phase_id, 'pid': 102,
        'profile': str(tmp_path / 'review-ready-profile'), 'provider': 'deepseek',
        'model': 'deepseek-flash', 'api': 'openai-completions', 'registered': True}}
    review_path.write_text(json.dumps(review_state, sort_keys=True))
    review_digest = sha256(review_path.read_bytes()).hexdigest()
    with pytest.raises(ReportReworkBudgetRefused):
        ReportReworkBudget.resume(review_path, plan_digest='a' * 64,
            ledger_digest=review_digest)


def test_resume_fence_is_cross_process_single_owner(tmp_path):
    path, _now, digest = confirmed_report_ledger(tmp_path)
    context = get_context('spawn')
    started = [context.Event(), context.Event()]
    release = context.Event()
    result = context.Queue()
    workers = [context.Process(target=_resume_worker,
        args=(str(path), 'a' * 64, digest, started[index], release, result))
        for index in range(2)]
    for worker in workers:
        worker.start()
    try:
        assert all(event.wait(10) for event in started)
        outcomes = [result.get(timeout=5), result.get(timeout=5)]
        assert outcomes.count('ok') == 1
        assert outcomes.count('refused') == 1
    finally:
        release.set()
        for worker in workers:
            worker.join(10)
        for worker in workers:
            if worker.is_alive():
                worker.terminate()


def test_actual_unit_profile_must_match_ready_and_role(tmp_path):
    authority, _ = prepared(tmp_path)
    try:
        unit = SimpleNamespace(identity={'unitId': 'actual'})
        owner = SimpleNamespace(records=SimpleNamespace(owner_read_unit=lambda _:
            SimpleNamespace(facts={'privateRootFacts': {'profile': str(tmp_path / 'report')}})))
        authority.require_unit_ready(owner, unit, 'report')
        with pytest.raises(ReportReworkBudgetRefused):
            authority.require_unit_ready(owner, unit, 'review')
    finally:
        authority.close()


def test_pinned_pi_loads_actual_budget_provider_without_a_model_prompt(tmp_path):
    """Real Pi public extension loader; no prompt or external HTTP is sent."""
    from hashlib import sha256
    from pathlib import Path
    import os
    import subprocess
    repo = Path(__file__).resolve().parents[3]
    extension = repo / 'plugins/harness/pi/src/ordessa_harness_pi/acp/request-budget.mjs'
    module = Path('/home/maoqh/.pi/agent/install/releases/0.86.1/node_modules/@earendil-works/pi-ai/dist/api/openai-completions.js')
    authority = ReportReworkBudget(tmp_path / 'budget.json', plan_digest='a' * 64).start()
    try:
        config = authority.phase_config('report', pi_ai_module=module.as_uri(),
            module_sha256=sha256(module.read_bytes()).hexdigest(),
            extension_sha256=sha256(extension.read_bytes()).hexdigest())
        config.pop('extension_sha256')
        profile = tmp_path / 'profile'
        profile.mkdir()
        model = {'id': 'deepseek-flash', 'name': 'budget loader probe',
            'api': 'openai-completions', 'reasoning': False, 'input': ['text'],
            'cost': {'input': .3, 'output': 1.2, 'cacheRead': .006, 'cacheWrite': 0},
            'contextWindow': 1000000, 'maxTokens': 16384}
        (profile / 'models.json').write_text(json.dumps({'providers': {'deepseek': {
            'baseUrl': 'https://api.deepseek.com', 'api': 'openai-completions',
            'apiKey': 'non-secret-no-prompt-fixture', 'models': [model]}}}))
        environment = {'PATH': os.environ['PATH'], 'HOME': str(tmp_path),
            'PI_CODING_AGENT_DIR': str(profile), 'TMPDIR': str(tmp_path),
            'ORDESSA_PI_REQUEST_BUDGET': json.dumps(config)}
        result = subprocess.run(['/home/maoqh/.local/bin/pi', '--mode', 'rpc',
            '--provider', 'deepseek', '--model', 'deepseek-flash', '--no-session',
            '--no-extensions', '--no-skills', '--no-context-files', '--no-prompt-templates',
            '-e', str(extension)], input='{"id":"state-only","type":"get_state"}\n',
            text=True, capture_output=True, env=environment, cwd=tmp_path, timeout=30)
        assert result.returncode == 0, result.stderr[-3000:]
        state = authority.snapshot()
        assert state['phases']['report']['ready'] is not None, result.stderr[-3000:]
        assert state['phases']['report']['ready']['profile'] == str(profile)
        assert state['reserved_nanodollars'] == 0 and state['reservations'] == []
    finally:
        authority.close()

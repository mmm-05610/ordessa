"""Trusted synchronous guard at the original single-use claim boundary."""
import asyncio
import threading
import time

import pytest
from decision_runtime import CallPermit, DecisionError


def permit():
    return CallPermit('run', 'question', 'settings', time.monotonic() + 10)


def claim(value, **changes):
    return value.claim(**{'run_id': 'run', 'question_digest': 'question',
                          'settings_digest': 'settings', **changes})


def test_metadata_and_deadline_precede_guard_and_one_consumption():
    value = permit(); calls = []
    value.bind_claim_guard(lambda: calls.append(True))
    with pytest.raises(DecisionError): claim(value, question_digest='foreign')
    assert calls == [] and value._claimed is False
    claim(value)
    assert calls == [True] and value._claimed is True
    with pytest.raises(DecisionError): claim(value)
    with pytest.raises(DecisionError): value.bind_claim_guard(lambda: None)
    assert calls == [True]
    expired = CallPermit('run', 'question', 'settings', time.monotonic() - 1)
    expired.bind_claim_guard(lambda: calls.append('expired'))
    with pytest.raises(DecisionError): claim(expired)
    assert calls == [True] and expired._claimed is False


def test_guard_failure_does_not_consume_or_allow_rebinding():
    value = permit()
    def refused(): raise RuntimeError('revoked original authority')
    value.bind_claim_guard(refused)
    with pytest.raises(RuntimeError): claim(value)
    assert value._claimed is False
    with pytest.raises(DecisionError): value.bind_claim_guard(lambda: None)
    async def asynchronous(): pass
    other = permit(); other.bind_claim_guard(asynchronous)
    with pytest.raises(DecisionError): claim(other)
    assert other._claimed is False


def test_copied_task_or_thread_cannot_consume_guarded_permit():
    async def scenario():
        value = permit(); calls = []
        value.bind_claim_guard(lambda: calls.append(True))
        async def copied():
            with pytest.raises(DecisionError): claim(value)
        await asyncio.create_task(copied())
        errors = []
        def worker():
            try: claim(value)
            except DecisionError as error: errors.append(error.code)
        thread = threading.Thread(target=worker); thread.start(); thread.join()
        assert errors == ['permit_refused'] and calls == [] and value._claimed is False
        claim(value)
        assert calls == [True] and value._claimed is True
    asyncio.run(scenario())


def test_guard_elapsed_deadline_refuses_before_consumption_and_physical_call(monkeypatch):
    ticks = [1.0]
    monkeypatch.setattr('decision_runtime.ports.time.monotonic', lambda: ticks[0])
    value = CallPermit('run', 'question', 'settings', 2.0)
    physical = []
    value.bind_claim_guard(lambda: ticks.__setitem__(0, 3.0))
    with pytest.raises(DecisionError):
        claim(value)
        physical.append('SDK dispatch')
    assert value._claimed is False and physical == []


def test_synchronous_guard_span_observes_consumption_before_authority_unlock():
    from contextlib import contextmanager
    value = permit(); events = []
    @contextmanager
    def original_authority():
        events.append(('enter', value._claimed))
        yield
        # Deterministic linearization counterexample: a revocation/observer at
        # guard exit must see that the independent permit was already consumed.
        events.append(('unlock', value._claimed))
    value.bind_claim_guard(original_authority)
    claim(value)
    assert events == [('enter', False), ('unlock', True)]
    assert value._claimed is True


def test_guard_span_entry_failure_refuses_without_consumption():
    from contextlib import contextmanager
    value = permit()
    @contextmanager
    def refused():
        raise RuntimeError('original admission revoked')
        yield
    value.bind_claim_guard(refused)
    with pytest.raises(RuntimeError): claim(value)
    assert value._claimed is False


def test_guard_span_exit_failure_stays_consumed_and_cannot_be_replayed():
    from contextlib import contextmanager
    value = permit(); physical = []
    @contextmanager
    def broken_exit():
        yield
        raise RuntimeError('authority cleanup uncertain')
    value.bind_claim_guard(broken_exit)
    with pytest.raises(RuntimeError):
        claim(value)
        physical.append('SDK dispatch')
    assert value._claimed is True and physical == []
    with pytest.raises(DecisionError): claim(value)


def test_async_context_manager_is_not_an_admission_span():
    from contextlib import asynccontextmanager
    @asynccontextmanager
    async def asynchronous(): yield
    value = permit(); value.bind_claim_guard(asynchronous)
    with pytest.raises(DecisionError): claim(value)
    assert value._claimed is False


def test_guard_exit_uncertainty_is_durable_unknown_without_second_attempt(tmp_path):
    from contextlib import contextmanager
    from types import SimpleNamespace
    from decision_runtime import DecisionRunner, FilesystemEvidenceStore
    from decision_runtime.capability import build_capability
    from decision_runtime.evidence import EvidenceScope
    from decision_runtime.settings import DecisionsSettings
    class Provider:
        binding_ref = 'controlled-guard-exit'
        settings_digest = 'settings'
        calls = 0
        physical = []
        async def decide(self, question, context):
            self.calls += 1
            @contextmanager
            def original_guard():
                yield
                raise RuntimeError('original cleanup uncertain')
            context.permit.bind_claim_guard(original_guard)
            context.claim(question, self.settings_digest)
            self.physical.append('SDK dispatch')
            raise AssertionError('guard exit failure cannot dispatch')
    provider = Provider()
    owner = FilesystemEvidenceStore(tmp_path)
    capability = build_capability(DecisionsSettings(DecisionRunner, owner, provider),
        invocation_resolver=lambda ctx: ctx,
        evidence_scope_resolver=lambda *_: EvidenceScope('principal', 'controlled-guard'))
    job = {'spec_version': 'decision-job/1', 'job_id': 'guard-exit', 'version': 1,
        'input': {}, 'limits': {'max_model_calls': 1, 'max_steps': 1, 'max_value_bytes': 4096, 'timeout_seconds': 5.0},
        'steps': [{'id': 'ask', 'type': 'ask', 'engine': None,
            'when': {'fact': 'input', 'op': 'eq', 'value': {}},
            'payload': {'question': {'kind': 'choice', 'text': 'Controlled choice', 'options': {'a': 'A', 'b': 'B'}}}}],
        'result': {'from': 'ask', 'path': ['answer']}}
    context = SimpleNamespace(request_id='original-guard-request')
    first = asyncio.run(capability.handlers['decisions.run']({'job': job}, context))
    second = asyncio.run(capability.handlers['decisions.run']({'job': job}, context))
    assert first.status == second.status == 'unknown'
    assert first.operation_ref == second.operation_ref
    assert provider.calls == 1 and provider.physical == []


@pytest.mark.parametrize('failure', ['deadline', 'awaitable-admission', 'awaitable-exit'])
def test_guard_cannot_suppress_refusal_or_return_async_exit(monkeypatch, failure):
    ticks = [1.0]
    monkeypatch.setattr('decision_runtime.ports.time.monotonic', lambda: ticks[0])
    value = CallPermit('run', 'question', 'settings', 2.0)
    physical = []
    async def asynchronous(): pass
    class Guard:
        def __enter__(self):
            if failure == 'deadline': ticks[0] = 3.0
            if failure == 'awaitable-admission': return asynchronous()
        def __exit__(self, *error):
            if failure == 'awaitable-exit': return asynchronous()
            return True  # Malicious suppression cannot make admission succeed.
    value.bind_claim_guard(Guard)
    with pytest.raises(DecisionError):
        claim(value)
        physical.append('SDK dispatch')
    assert physical == []
    assert value._claimed is (failure == 'awaitable-exit')

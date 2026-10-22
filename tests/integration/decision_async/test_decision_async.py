"""Controlled async Decision owner: acceptance, query, dispatch-time authority.

No model and no network: a fake provider proves the owner-held background run,
the readable pending/terminal facts, revocation before dispatch, and the explicit
provider-missing refusal. CEL-only jobs stay synchronous (fast, no HTTP wait).
"""
from __future__ import annotations

import asyncio

import pytest

from ordessa_decision import DecisionAnswer, DecisionRunner, FilesystemEvidenceStore, RulesOutcome
from ordessa_decision.capability import build_capability
from ordessa_decision.definitions.values import digest_hex
from ordessa_decision.evidence import EvidenceScope
from ordessa_decision.settings import DecisionsSettings


class Engine:
    engine_id = "fake"

    def validate(self, payload):
        pass

    def evaluate(self, payload, facts):
        return RulesOutcome(values={"double": facts["input"]["n"] * 2},
                            disposition="passed")

    def close(self):
        pass


class SlowProvider:
    """Protocol-shaped fake: one permit claim, then a bounded delayed answer."""

    binding_ref = "fake-slow/1"
    settings_digest = digest_hex({"binding": "fake-slow/1"})

    def __init__(self, delay=0.25):
        self.delay = delay
        self.calls = 0

    async def decide(self, question, context):
        self.calls += 1
        context.claim(question, self.settings_digest)
        await asyncio.sleep(self.delay)
        receipt = {"resolved_model": "fake-1", "requested_model": "fake-1",
                   "protocol_validation_version": "jev-protocol/2",
                   "question_digest": question.question_digest,
                   "provider_settings_digest": self.settings_digest,
                   "probabilities": {"a": 0.9, "b": 0.1},
                   "confidence": 1.0}
        return DecisionAnswer(question.question_id, "choice", "a", receipt,
                              {"status": "unknown"})


class Context:
    principal = {"id": "worker"}
    deadline = None

    def __init__(self, request_id="req-1"):
        self.request_id = request_id


def _settings(tmp_path, *, provider):
    return DecisionsSettings(
        runner_factory=lambda **kwargs: DecisionRunner(host_limits=None, **kwargs),
        evidence=FilesystemEvidenceStore(tmp_path / "evidence"),
        provider=provider,
        default_engine=Engine())


def _build(settings, *, resolver=None):
    resolutions = {"count": 0}

    def scope(invocation, operation):
        resolutions["count"] += 1
        if resolver is not None:
            return resolver(invocation, operation)
        return EvidenceScope("principal", "worker")

    capability = build_capability(settings,
                                  invocation_resolver=lambda context: context,
                                  evidence_scope_resolver=scope)
    return capability, resolutions


def _model_job(**overrides):
    value = {
        "spec_version": "decision-job/1", "job_id": "async-cap", "version": 1,
        "input": {"n": 2},
        "limits": {"max_model_calls": 1, "max_steps": 2,
                   "max_value_bytes": 1024, "timeout_seconds": 5.0},
        "steps": [{"id": "ask", "type": "ask", "engine": None,
                   "when": {"fact": "input.n", "op": "gte", "value": 0},
                   "payload": {"question": {"kind": "choice", "text": "Pick",
                                            "options": {"a": "A", "b": "B"}}}}],
        "result": {"from": "ask", "path": ["answer"]},
    }
    value.update(overrides)
    return value


def _rules_job():
    return {
        "spec_version": "decision-job/1", "job_id": "sync-cap", "version": 1,
        "input": {"n": 2},
        "limits": {"max_model_calls": 0, "max_steps": 2,
                   "max_value_bytes": 1024, "timeout_seconds": 2.0},
        "steps": [{"id": "rules", "type": "rules", "engine": None,
                   "when": {"fact": "input.n", "op": "gte", "value": 1},
                   "payload": {"values": {"double": "input.n * 2"}}}],
        "result": {"from": "rules", "path": ["values", "double"]},
    }


@pytest.mark.asyncio
async def test_model_run_accepts_then_query_reads_terminal_fact(tmp_path):
    provider = SlowProvider()
    capability, _ = _build(_settings(tmp_path, provider=provider))
    context = Context("async-1")
    accepted = await capability.handlers["decisions.run"]({"job": _model_job()}, context)
    assert accepted.status == "accepted" and accepted.operation_ref
    assert accepted.data == {"state": "pending"}
    # The accepted run is queryable while it is still running; no second call.
    pending = await capability.handlers["decisions.query"](
        {"originalRequestId": "async-1", "job": _model_job()}, context)
    assert pending.status == "accepted" and provider.calls <= 1
    # Re-submitting the SAME request id while it runs stays pending
    # (not a conflict and not a second dispatch).
    replay = await capability.handlers["decisions.run"]({"job": _model_job()}, context)
    assert replay.status == "accepted" and provider.calls <= 1
    await capability._decision_service.wait_background()
    done = await capability.handlers["decisions.query"](
        {"originalRequestId": "async-1", "job": _model_job()}, context)
    assert done.status == "completed"
    assert done.data["result"] == "a"
    assert done.data["evidence"]["digest"]
    # A later read never calls the provider again.
    again = await capability.handlers["decisions.query"](
        {"originalRequestId": "async-1", "job": _model_job()}, context)
    assert again.status == "completed" and provider.calls == 1


@pytest.mark.asyncio
async def test_revoked_scope_before_dispatch_refuses_without_model_call(tmp_path):
    provider = SlowProvider(delay=0.0)
    state = {"calls": 0}

    def resolver(invocation, operation):
        state["calls"] += 1
        # Entry check passes; the dispatch-time recheck (inside the background
        # owner) sees the revoked scope and refuses before the provider runs.
        if state["calls"] > 2:
            raise PermissionError('revoked')
        return EvidenceScope("principal", "worker")

    capability, _ = _build(_settings(tmp_path, provider=provider), resolver=resolver)
    context = Context("async-revoked")
    accepted = await capability.handlers["decisions.run"]({"job": _model_job()}, context)
    assert accepted.status == "accepted"
    await capability._decision_service.wait_background()
    result = await capability.handlers["decisions.query"](
        {"originalRequestId": "async-revoked", "job": _model_job()}, context)
    assert result.status == "refused"
    assert result.error.code == "PERMISSION_DENIED"
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_model_job_without_provider_is_refused_before_any_claim(tmp_path):
    capability, _ = _build(_settings(tmp_path, provider=None))
    context = Context("async-noprovider")
    result = await capability.handlers["decisions.run"]({"job": _model_job()}, context)
    assert result.status == "refused"
    assert result.error.code == "PROVIDER_UNAVAILABLE"
    queried = await capability.handlers["decisions.query"](
        {"originalRequestId": "async-noprovider", "job": _model_job()}, context)
    assert queried.status == "refused"  # no claim was created


@pytest.mark.asyncio
async def test_restarted_owner_reports_unresolved_claim_unknown_without_redispatch(tmp_path):
    provider = SlowProvider(delay=10)
    settings = _settings(tmp_path, provider=provider)
    capability, _ = _build(settings)
    context = Context('interrupted')
    await capability.handlers['decisions.run']({'job': _model_job()}, context)
    await asyncio.sleep(0)
    service = capability._decision_service
    for task in tuple(service._background):
        task.cancel()
    await service.wait_background()
    restarted, _ = _build(settings)
    query = await restarted.handlers['decisions.query'](
        {'originalRequestId': context.request_id, 'job': _model_job()}, context)
    assert query.status == 'unknown'
    replay = await restarted.handlers['decisions.run']({'job': _model_job()}, context)
    assert replay.status == 'unknown'
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_server_owner_rechecks_real_authority_after_acceptance(tmp_path):
    from ordessa_interfaces.system_access.access_control.authentication import (
        AccessGrant, InstanceAccessAuthority)
    from ordessa_interfaces.system_access.contracts.refs import Scope
    from ordessa_server.composition.decision_owner import build_decision_owner
    from ordessa_server.composition.invocation import server_invocation
    authority = InstanceAccessAuthority(lambda: 'test-token', principal_id='instance',
        grants=(AccessGrant(Scope('ordessa', 'local'),
                            ('decisions.run', 'decisions.get', 'decisions.query')),),
        legacy_principal=None)
    invocation = server_invocation(authority.authenticate('Bearer test-token'))
    provider = SlowProvider(delay=0)
    owner = build_decision_owner(tmp_path, invocation_resolver=lambda _: invocation,
                                 authority=authority, provider=provider)
    context = Context('revoke-before-dispatch')
    accepted = await owner.capability.handlers['decisions.run']({'job': _model_job()}, context)
    assert accepted.status == 'accepted'
    authority.revoke()
    await owner.capability._decision_service.wait_background()
    assert provider.calls == 0
    queried = await owner.capability.handlers['decisions.query'](
        {'originalRequestId': context.request_id, 'job': _model_job()}, context)
    assert queried.status == 'refused'


@pytest.mark.asyncio
async def test_mixed_rules_ask_rules_order_and_terminal(tmp_path):
    from ordessa_decision import load_rules_engine
    provider = SlowProvider(delay=0.0)
    settings = _settings(tmp_path, provider=provider)
    settings = DecisionsSettings(
        runner_factory=settings.runner_factory, evidence=settings.evidence,
        provider=provider, default_engine=load_rules_engine('cel'))
    capability, _ = _build(settings)
    job = {
        "spec_version": "decision-job/1", "job_id": "mixed-cap", "version": 1,
        "input": {"n": 2},
        "limits": {"max_model_calls": 1, "max_steps": 3,
                   "max_value_bytes": 4096, "timeout_seconds": 5.0},
        "steps": [
            {"id": "pre", "type": "rules", "engine": None,
             "when": {"fact": "input.n", "op": "gte", "value": 0},
             "payload": {"checks": [{"id": "ok", "when": "input.n > 0"}],
                         "default": {"ready": "yes"}}},
            {"id": "judge", "type": "ask", "engine": None,
             "when": {"fact": "pre.values.default.ready", "op": "eq", "value": "yes"},
             "payload": {"question": {"kind": "choice", "text": "Pick",
                                      "options": {"a": "A", "b": "B"}}}},
            {"id": "post", "type": "rules", "engine": None,
             "when": {"fact": "judge.answer", "op": "eq", "value": "a"},
             "payload": {"checks": [{"id": "a", "when": 'judge.answer == "a"'}],
                         "default": {"decision": "a-wins"}}},
        ],
        "result": {"from": "post", "path": ["values", "default"]},
    }
    accepted = await capability.handlers["decisions.run"]({"job": job}, Context("mixed-1"))
    assert accepted.status == "accepted"
    await capability._decision_service.wait_background()
    done = await capability.handlers["decisions.query"](
        {"originalRequestId": "mixed-1", "job": job}, Context("mixed-1"))
    assert done.status == "completed"
    assert done.data["result"] == {"decision": "a-wins"}
    assert provider.calls == 1


@pytest.mark.asyncio
async def test_cel_only_run_stays_synchronous(tmp_path):
    capability, _ = _build(_settings(tmp_path, provider=None))
    result = await capability.handlers["decisions.run"]({"job": _rules_job()},
                                                        Context("sync-1"))
    assert result.status == "completed"
    assert result.data["result"] == 4
    assert not capability._decision_service._background


def test_production_decision_access_requires_the_exact_grant_and_revocation(tmp_path):
    from ordessa_interfaces.system_access.access_control.authentication import (
        AccessGrant, InstanceAccessAuthority)
    from ordessa_interfaces.system_access.contracts.refs import Scope
    from ordessa_server.composition.decision_bindings.access import ServerDecisionAccess
    from ordessa_server.composition.invocation import server_invocation

    authority = InstanceAccessAuthority(
        lambda: 'token', principal_id='instance',
        grants=(AccessGrant(Scope('ordessa', 'local'), ('decisions.run',)),),
        legacy_principal=None)
    access = ServerDecisionAccess(authority)
    invocation = server_invocation(authority.authenticate('Bearer token'))
    assert access.authorize_operation(invocation, 'decisions.run', {}) is True
    with pytest.raises(Exception):
        access.authorize_operation(invocation, 'decisions.get', {})
    authority.revoke()
    with pytest.raises(Exception):
        access.authorize_operation(invocation, 'decisions.run', {})

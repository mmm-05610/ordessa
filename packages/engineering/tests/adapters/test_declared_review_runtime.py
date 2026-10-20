"""Controlled boundaries for the declared reviewer native-write adapter.

These tests exercise the composition helper and its original permission/Unit
ports with explicit doubles. They do not claim a complete Server or native ACP
integration test.
"""
import asyncio
from contextlib import contextmanager
import json
from threading import Thread, current_thread
from types import SimpleNamespace

import pytest

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_execution_agents.harness.transport import EffectWriteGuard
from ordessa_engineering.adapters.native_records import declared_review_runtime as review_runtime


_UNIT = {
    "environmentNamespace": "test-environment",
    "unitId": "review-unit",
    "ownerProviderRef": {"provider": "controlled-test"},
    "sourceRevision": "test-r1",
}
_OPERATION = "declared-review-operation"
_DIGEST = "sha256:" + "a" * 64
_HANDOFF = object()


class _Factory:
    def __init__(self):
        self.calls = []
        self.reads = []

    def __call__(self, unit_ref, operation, digest, params):
        self.calls.append((unit_ref, operation, digest, params))
        return "original-factory-result"

    @contextmanager
    def guard_effect_handoff(self, *args, **kwargs):
        self.reads.append((args, kwargs))
        yield "original-handoff"

    @contextmanager
    def begin(self, scope, mode):
        assert mode == "read"
        assert not getattr(self, 'active_read', False), 'original UoW cannot be nested'
        self.reads.append((scope, mode))
        self.active_read = True
        try:
            yield self.uow
        finally:
            self.active_read = False


class _Access:
    def __init__(self, events):
        self.events = events
        self.consume_calls = []

    def require(self, context, capability):
        assert context.scope == "controlled-scope"
        assert capability == "engineering.reviews.request"
        self.events.append("require")

    @contextmanager
    def consume_effect_write(self, handoff, context, *, invocation_key, action_instances):
        assert handoff is _HANDOFF
        self.consume_calls.append((handoff, context, invocation_key, action_instances))
        self.events.append("consume-enter")
        try:
            yield
        finally:
            self.events.append("consume-exit")


class _Owner:
    def __init__(self, events):
        self.records = SimpleNamespace(
            acp_prompt_input_digest=lambda unit_ref, params: _DIGEST,
        )
        self.permission = object()
        self.auth = object()
        self.events = events
        self.native_calls = []

    def authorization(self):
        return self.auth

    def native_unit(self, unit, authorization):
        assert authorization is self.auth
        self.native_calls.append(unit)
        self.events.append("native-unit-validated")
        return SimpleNamespace()


class _Unit:
    identity = _UNIT

    def snapshot(self):
        return {"sessionId": "native-session-1"}


def _fixture():
    events = []
    factory = _Factory()
    access = _Access(events)
    owner = _Owner(events)
    methods = SimpleNamespace(factory=factory)

    @contextmanager
    def method_guard(context, method_ref):
        assert method_ref == "method-ref"
        events.append("method-guard-enter")
        yield "method-definition"
        events.append("method-guard-exit")

    methods.guard = method_guard
    bindings = SimpleNamespace(factory=factory)

    def resolve_plan(context, plan, definition):
        assert definition == "method-definition"
        events.append("submission-plan-resolved")

    bindings.resolve_declared_submission_plan = resolve_plan
    assignment = SimpleNamespace(
        request_version=4,
        fence=9,
        plan_digest="plan-digest",
        author_unit_ref_bytes=b"declared-author-unit-ref",
        reviewer_unit_ref=_UNIT,
        ref="assignment-ref",
    )
    control = SimpleNamespace(state="active")
    request = SimpleNamespace(state="requested", version=4, fence=9)
    plan = SimpleNamespace(
        review_id="review-1",
        plan_digest="plan-digest",
        requirement=SimpleNamespace(
            method_ref="method-ref",
            expected_targets=SimpleNamespace(targets=(SimpleNamespace(ref="submission-ref"),)),
        ),
    )
    submission = SimpleNamespace(ref="submission-ref")

    class _Reviews:
        def get_request(self, review_id):
            assert review_id == plan.review_id
            events.append("request-reread")
            return request

        def get_plan(self, review_id):
            assert review_id == plan.review_id
            events.append("plan-reread")
            return plan

    class _Assignments:
        def active_for_review(self, review_id):
            assert review_id == plan.review_id
            events.append("assignment-reread")
            return assignment, control

    class _Submissions:
        def resolve(self, ref):
            assert ref == "submission-ref"
            events.append("submission-reread")
            return submission

    factory.uow = SimpleNamespace(
        reviews=_Reviews(), reviewer_assignments=_Assignments(), submissions=_Submissions(),
    )

    def prompt_parameters(context, plan, request, assignment, session_id):
        # The real source reconstructs its input through this same original
        # Library. A producer must not call it inside an already open UoW.
        with factory.begin('controlled-scope', 'read'):
            return {'sessionId': session_id, 'prompt': 'review the declared report'}

    source = SimpleNamespace(
        factory=factory,
        records=owner.records,
        blobs=object(),
        access=access,
        bindings=bindings,
        prompt_parameters=prompt_parameters,
        operation_ref=lambda plan, assignment: _OPERATION,
    )
    assignments = SimpleNamespace(factory=factory, access=access)
    runtime = review_runtime.DeclaredUnitReviewRuntime(
        factory=factory, access=access, owner=owner, blobs=source.blobs,
        methods=methods, bindings=bindings, assignments=assignments, source=source,
    )
    unit = _Unit()
    params = source.prompt_parameters(None, plan, request, assignment, "native-session-1")
    context = SimpleNamespace(scope="controlled-scope", request_id="review-request-1")
    runtime._slot = (context, plan, request, assignment, unit, params, _HANDOFF, current_thread())
    return SimpleNamespace(
        runtime=runtime, factory=factory, access=access, owner=owner, source=source,
        assignment=assignment, control=control, request=request, plan=plan,
        unit=unit, params=params, events=events,
    )


def test_dispatch_factory_is_wrapped_once_and_original_behavior_is_delegated():
    f = _fixture()
    original_reads = list(f.factory.reads)
    runtime = f.runtime
    assert runtime.wrap_dispatch_factory(f.factory) is runtime
    with pytest.raises(ApplicationError, match="REVIEW_SOURCE_AUTHORITY_MISMATCH"):
        runtime.wrap_dispatch_factory(f.factory)

    # With no reviewer slot, ordinary implementation dispatch is unchanged.
    runtime._slot = None
    assert runtime("unit-ref", "implementation-op", _DIGEST, {"prompt": "x"}) == "original-factory-result"
    assert f.factory.calls == [("unit-ref", "implementation-op", _DIGEST, {"prompt": "x"})]
    with runtime.guard_effect_handoff("handoff-args", scope="fixed") as value:
        assert value == "original-handoff"
    assert f.factory.reads == original_reads + [(('handoff-args',), {"scope": "fixed"})]


def _guard(f, *, unit_ref=None, operation=None, digest=None, params=None):
    return f.runtime(
        f.unit.identity if unit_ref is None else unit_ref,
        _OPERATION if operation is None else operation,
        _DIGEST if digest is None else digest,
        f.params if params is None else params,
    )


def _frame(params):
    return json.dumps({"id": "request-1", "method": "session/prompt", "params": params}).encode()


def test_native_guard_revalidates_exact_review_binding_before_write(monkeypatch):
    f = _fixture()
    monkeypatch.setattr(review_runtime, "resolve_declared_report_binding",
        lambda uow, submission: SimpleNamespace(unit_ref_bytes=b"declared-author-unit-ref"))
    guard = _guard(f)
    assert type(guard) is EffectWriteGuard

    writes = []

    async def send():
        async with guard.hold(_frame(f.params)):
            # This is the controlled byte-write boundary: all original request,
            # assignment, binding, session and permission checks must precede it.
            assert "request-reread" in f.events
            assert "assignment-reread" in f.events
            assert "submission-reread" in f.events
            assert "native-unit-validated" in f.events
            assert f.events.index("consume-enter") < f.events.index("request-reread")
            assert f.events.index("submission-reread") < f.events.index("native-unit-validated")
            writes.append("exact-frame")

    asyncio.run(send())
    assert writes == ["exact-frame"]
    assert len(f.access.consume_calls) == 1
    assert ("controlled-scope", "read") in f.factory.reads
    handoff, context, invocation_key, action_instances = f.access.consume_calls[0]
    assert handoff is _HANDOFF
    assert invocation_key == bytes.fromhex(_DIGEST.removeprefix("sha256:"))
    assert action_instances == ()


def test_rework_approval_guard_runs_inside_effect_cut_and_refusal_prevents_prompt(monkeypatch):
    f = _fixture()
    monkeypatch.setattr(review_runtime, "resolve_declared_report_binding",
        lambda uow, submission: SimpleNamespace(unit_ref_bytes=b"declared-author-unit-ref"))

    @contextmanager
    def refused_rework_guard(context, plan, request, assignment):
        assert context.request_id == "review-request-1"
        assert plan is f.plan and request is f.request and assignment is f.assignment
        f.events.append("report-approval-guard-enter")
        raise ApplicationError("ACCESS_AUTHORITY_UNAVAILABLE")
        yield

    f.runtime.native_prompt_guard = refused_rework_guard
    guard = _guard(f)
    writes = []

    async def send():
        async with guard.hold(_frame(f.params)):
            writes.append("must-not-write")

    with pytest.raises(ApplicationError, match="ACCESS_AUTHORITY_UNAVAILABLE"):
        asyncio.run(send())
    assert writes == []
    assert f.events.index("consume-enter") < f.events.index("report-approval-guard-enter")
    assert f.events[-1] == "consume-exit"
    assert "request-reread" not in f.events


def test_rework_approval_guard_spans_the_native_byte_cut(monkeypatch):
    f = _fixture()
    monkeypatch.setattr(review_runtime, "resolve_declared_report_binding",
        lambda uow, submission: SimpleNamespace(unit_ref_bytes=b"declared-author-unit-ref"))

    @contextmanager
    def live_rework_guard(context, plan, request, assignment):
        assert context.request_id == "review-request-1"
        f.events.append("report-approval-guard-enter")
        try:
            yield
        finally:
            f.events.append("report-approval-guard-exit")

    f.runtime.native_prompt_guard = live_rework_guard
    guard = _guard(f)
    writes = []

    async def send():
        async with guard.hold(_frame(f.params)):
            assert f.events.index("report-approval-guard-enter") < f.events.index("request-reread")
            writes.append("exact-frame")

    asyncio.run(send())
    assert writes == ["exact-frame"]
    assert f.events.index("consume-enter") < f.events.index("report-approval-guard-enter")
    assert f.events.index("report-approval-guard-exit") < f.events.index("consume-exit")


@pytest.mark.parametrize("change", ["unit", "operation", "digest", "params"])
def test_native_guard_refuses_any_changed_fixed_binding_without_write(change):
    f = _fixture()
    values = {}
    if change == "unit":
        values["unit_ref"] = {**_UNIT, "unitId": "other-unit"}
    elif change == "operation":
        values["operation"] = "other-operation"
    elif change == "digest":
        values["digest"] = "sha256:" + "b" * 64
    else:
        values["params"] = {**f.params, "prompt": "different input"}

    with pytest.raises(ApplicationError, match="REVIEW_REQUEST_CHANGED"):
        _guard(f, **values)
    assert f.access.consume_calls == []


def test_native_guard_is_bound_to_original_thread_and_stale_request_never_writes(monkeypatch):
    f = _fixture()
    monkeypatch.setattr(review_runtime, "resolve_declared_report_binding",
        lambda uow, submission: SimpleNamespace(unit_ref_bytes=b"declared-author-unit-ref"))
    errors = []

    def other_thread():
        try:
            _guard(f)
        except BaseException as error:
            errors.append(error)

    thread = Thread(target=other_thread)
    thread.start()
    thread.join(timeout=2)
    assert not thread.is_alive()
    assert len(errors) == 1 and isinstance(errors[0], ApplicationError)
    assert "REVIEW_REQUEST_CHANGED" in str(errors[0])
    assert f.access.consume_calls == []

    guard = _guard(f)
    f.request.state = "expired"
    writes = []

    async def send_stale():
        async with guard.hold(_frame(f.params)):
            writes.append("must-not-write")

    with pytest.raises(ApplicationError, match="REVIEW_REQUEST_CHANGED"):
        asyncio.run(send_stale())
    assert writes == []
    assert len(f.access.consume_calls) == 1
    assert f.factory.calls == []


def test_native_guard_accepts_the_original_sealed_public_unit_reference(monkeypatch):
    from types import MappingProxyType
    f = _fixture()
    f.unit.identity = MappingProxyType({**_UNIT,
        'ownerProviderRef': MappingProxyType(_UNIT['ownerProviderRef'])})
    monkeypatch.setattr(review_runtime, 'resolve_declared_report_binding',
        lambda uow, submission: SimpleNamespace(unit_ref_bytes=b'declared-author-unit-ref'))
    guard = _guard(f)
    async def send():
        async with guard.hold(_frame(f.params)):
            assert 'native-unit-validated' in f.events
    asyncio.run(send())
    assert len(f.access.consume_calls) == 1

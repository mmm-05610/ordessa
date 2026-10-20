"""Work invokes receive only exact checks and child admissions on original ACLs."""
from contextvars import copy_context
from pathlib import Path
from threading import Event, Thread
import time

import pytest

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_interfaces.system_access.access_control.authentication import (
    AccessGrant,
    InstanceAccessAuthority,
)
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_execution_agents.profiles import ProfileRevisionRef
from ordessa_units.assembly import UnitRunPermission
from ordessa_units.admission.invocation import InvocationAuthorityRefused
from ordessa_system_access_bindings.engineering import EngineeringCommandAccess


WORK_INVOKE = "engineering.work.invoke"
WORK_GET = "engineering.work.get"
DISPATCH = "engineering.executions.dispatch"
OTHER = "engineering.proposals.create"
SCOPE = Scope("work-case", "scope-one")
WORK_STEPS = (
    WORK_GET,
    "engineering.reviews.request",
    "engineering.reviews.record",
    "engineering.submissions.record_report",
    "engineering.proposals.associate_review",
    DISPATCH,
)


def _access(*capabilities, token_provider=None):
    provider = token_provider or (lambda: "controlled-work-token")
    authority = InstanceAccessAuthority(
        provider,
        principal_id="work-instance",
        legacy_principal=None,
        grants=(AccessGrant(SCOPE, tuple(capabilities)),),
    )
    caller = authority.authenticate("Bearer controlled-work-token")
    return authority, caller, EngineeringCommandAccess(authority)


def _must_refuse(callback):
    with pytest.raises(ApplicationError):
        result = callback()
        if hasattr(result, "__enter__"):
            with result:
                pass


def _unit_permission(authority, caller, access, root, *, scope=SCOPE,
                     expires_at=None):
    root.mkdir(parents=True, exist_ok=True)
    return UnitRunPermission(
        access_authority=authority,
        principal=caller,
        scope=scope,
        agent_id="work-bootstrap-agent",
        profile_revision=ProfileRevisionRef(
            scope.realm_id, "work-bootstrap-profile", 1, "sha256:" + "a" * 64),
        environment_identity="work-bootstrap-environment",
        root_directory=str(root.resolve()),
        actions=frozenset({"prepare", "start", "stop", "release"}),
        expires_at=time.time() + 60 if expires_at is None else expires_at,
    )


def test_work_capability_check_uses_only_the_exact_active_work_context():
    _, caller, access = _access(WORK_INVOKE, WORK_GET, DISPATCH)
    with access.admit(caller, SCOPE, WORK_INVOKE,
                      request_id="work-invoke-1", trace_id="trace-1") as context:
        assert access.check_work_capability(context, DISPATCH) is True
        _must_refuse(lambda: access.check_work_capability(
            context, OTHER))
        forged = type(context)(
            context.scope, context.principal_id, context.authenticated_actor,
            context.request_id, context.received_at, context.trace_id)
        _must_refuse(lambda: access.check_work_capability(forged, DISPATCH))
    with access.admit(caller, SCOPE, WORK_GET,
                      request_id="work-get-1", trace_id="trace-2") as context:
        assert access.check_work_capability(context, DISPATCH) is True


def test_work_step_child_reuses_principal_scope_and_trace_then_restores_parent():
    _, caller, access = _access(WORK_INVOKE, *WORK_STEPS)
    with access.admit(caller, SCOPE, WORK_INVOKE,
                      request_id="work-invoke-2", trace_id="trace-2") as parent:
        parent_copy = copy_context()
        copied_child = []
        _must_refuse(lambda: access.admit(
            caller, SCOPE, DISPATCH, request_id="ordinary-nested-dispatch",
            trace_id="trace-2"))
        with access.admit_work_step(
            parent, DISPATCH, request_id="work-invoke-2:dispatch:draft:1",
        ) as child:
            copied_child.append(copy_context())
            assert child is not parent
            assert child.scope == parent.scope
            assert child.principal_id == parent.principal_id == caller.principal_id
            assert child.trace_id == parent.trace_id
            assert child.request_id == "work-invoke-2:dispatch:draft:1"
            access.require(child, DISPATCH)
            _must_refuse(lambda: access.require(parent, WORK_INVOKE))
            _must_refuse(lambda: parent_copy.run(
                access.require, parent, WORK_INVOKE))
            _must_refuse(lambda: access.admit_work_step(
                child, DISPATCH, request_id="nested-dispatch"))
        access.require(parent, WORK_INVOKE)
        assert access.current_context() is parent
        _must_refuse(lambda: access.require(parent, DISPATCH))
        _must_refuse(lambda: copied_child[0].run(
            access.require, child, DISPATCH))


def test_work_step_child_allowlist_is_fixed_and_each_child_uses_its_own_guard():
    _, caller, access = _access(WORK_INVOKE, *WORK_STEPS)
    with access.admit(caller, SCOPE, WORK_INVOKE,
                      request_id="work-invoke-allowlist", trace_id="trace-allowlist") as parent:
        for index, operation in enumerate(WORK_STEPS):
            with access.admit_work_step(
                parent, operation, request_id=f"work-invoke-allowlist:step:{index}",
            ) as child:
                access.require(child, operation)
                if operation == WORK_GET:
                    assert access.check_work_capability(child, DISPATCH) is True
                _must_refuse(lambda: access.admit_work_step(
                    child, WORK_GET, request_id="nested-work-get"))
        for operation in (WORK_INVOKE, OTHER, "engineering.approvals.issue"):
            _must_refuse(lambda operation=operation: access.admit_work_step(
                parent, operation, request_id="work-invoke-allowlist:rejected"))
        access.require(parent, WORK_INVOKE)


def test_declared_review_can_only_issue_its_exact_reviewer_assignment_child():
    review, assign = 'engineering.reviews.request', 'engineering.reviews.assign_reviewer'
    _, caller, access = _access(WORK_INVOKE, review, assign, DISPATCH)
    with access.admit(caller, SCOPE, WORK_INVOKE,
                      request_id='review-work', trace_id='review-work') as work:
        with access.admit_work_step(work, review, request_id='review-step') as context:
            _must_refuse(lambda: access.admit_work_step(context, DISPATCH, request_id='wrong-child'))
            with access.admit_work_step(context, assign, request_id='review-assignment') as child:
                access.require(child, assign)
                _must_refuse(lambda: access.require(context, review))
                _must_refuse(lambda: access.require(work, WORK_INVOKE))
            access.require(context, review)
        access.require(work, WORK_INVOKE)
    with access.admit(caller, SCOPE, review,
                      request_id='direct-review', trace_id='direct-review') as context:
        _must_refuse(lambda: access.admit_work_step(context, assign, request_id='not-work-child'))


def test_review_bootstrap_retains_original_unit_permission_and_suspended_work(tmp_path):
    review = 'engineering.reviews.request'
    authority, caller, access = _access(WORK_INVOKE, review, 'execution.units.start')
    permission = _unit_permission(authority, caller, access, tmp_path / 'review-unit')
    finished, failures = [], []
    def start():
        try:
            with permission.guard('start'):
                finished.append(True)
        except BaseException as error:
            failures.append(error)
    with access.admit(caller, SCOPE, WORK_INVOKE,
                      request_id='review-bootstrap-work', trace_id='review-bootstrap-work') as work:
        with access.admit_work_step(work, review, request_id='review-bootstrap') as context:
            with access.guard_unit_bootstrap(context, permission=permission):
                worker = Thread(target=start)
                worker.start()
                worker.join(2)
                assert not worker.is_alive() and finished == [True] and not failures
                _must_refuse(lambda: access.require(work, WORK_INVOKE))
            access.require(context, review)
        access.require(work, WORK_INVOKE)


def test_missing_child_capability_never_yields_or_revives_parent():
    _, caller, access = _access(WORK_INVOKE)
    yielded = []
    with access.admit(caller, SCOPE, WORK_INVOKE,
                      request_id="work-invoke-3", trace_id="trace-3") as parent:
        _must_refuse(lambda: access.admit_work_step(
            parent, DISPATCH, request_id="work-invoke-3:dispatch"))
        _must_refuse(lambda: access.require(parent, WORK_INVOKE))
        assert yielded == []


def test_failed_child_and_rotated_parent_credential_do_not_restore_authority():
    _, caller, access = _access(WORK_INVOKE, DISPATCH)
    with access.admit(caller, SCOPE, WORK_INVOKE,
                      request_id="work-invoke-4", trace_id="trace-4") as parent:
        with pytest.raises(RuntimeError, match="controlled child failure"):
            with access.admit_work_step(
                parent, DISPATCH, request_id="work-invoke-4:dispatch:failed",
            ):
                raise RuntimeError("controlled child failure")
        _must_refuse(lambda: access.require(parent, WORK_INVOKE))

    token = ["controlled-work-token"]
    authority, caller, access = _access(
        WORK_INVOKE, DISPATCH, token_provider=lambda: token[0])
    with access.admit(caller, SCOPE, WORK_INVOKE,
                      request_id="work-invoke-5", trace_id="trace-5") as parent:
        with pytest.raises(ApplicationError):
            with access.admit_work_step(
                parent, DISPATCH, request_id="work-invoke-5:dispatch:rotate",
            ):
                token[0] = "rotated-work-token"
        _must_refuse(lambda: access.require(parent, WORK_INVOKE))


def test_unit_bootstrap_releases_only_dispatch_guard_and_restores_original_context(tmp_path):
    authority, caller, access = _access(
        WORK_INVOKE, DISPATCH, "execution.units.start")
    permission = _unit_permission(authority, caller, access, tmp_path / "unit-root")
    with access.admit(caller, SCOPE, WORK_INVOKE,
                      request_id="work-unit-bootstrap", trace_id="trace-bootstrap") as work:
        with access.admit_work_step(
                work, DISPATCH, request_id="work-unit-bootstrap:dispatch") as dispatch:
            copied = copy_context()
            completed = []
            failures = []

            def revalidate_original_unit_permission():
                try:
                    with permission.guard("start"):
                        completed.append("allowed")
                except BaseException as error:
                    failures.append(error)

            with access.guard_unit_bootstrap(dispatch, permission=permission):
                with pytest.raises(ApplicationError):
                    access.current_context()
                _must_refuse(lambda: copied.run(access.require, dispatch, DISPATCH))

                def nested_engineering_admission():
                    with access.admit(caller, SCOPE, DISPATCH,
                                      request_id="nested-during-unit-bootstrap",
                                      trace_id="trace-bootstrap"):
                        pytest.fail("suspended bootstrap lease admitted nested Engineering work")

                _must_refuse(nested_engineering_admission)
                _must_refuse(lambda: copied.run(nested_engineering_admission))
                worker = Thread(target=revalidate_original_unit_permission)
                worker.start()
                worker.join(2)
                assert not worker.is_alive(), "Unit guard remained blocked by Engineering lease"
                assert completed == ["allowed"]
                assert failures == []
            access.require(dispatch, DISPATCH)
            assert access.current_context() is dispatch
        access.require(work, WORK_INVOKE)


def test_unit_bootstrap_refuses_wrong_authority_scope_and_non_dispatch_context(tmp_path):
    authority, caller, access = _access(WORK_INVOKE, DISPATCH)
    permission = _unit_permission(authority, caller, access, tmp_path / "valid")
    other_authority, other_caller, other_access = _access(WORK_INVOKE, DISPATCH)
    other_permission = _unit_permission(
        other_authority, other_caller, other_access, tmp_path / "other")
    wrong_scope = _unit_permission(
        authority, caller, access, tmp_path / "wrong-scope",
        scope=Scope(SCOPE.realm_id, "different-project"))

    with access.admit(caller, SCOPE, WORK_INVOKE,
                      request_id="work-unit-bootstrap-invalid", trace_id="trace-invalid") as work:
        with access.admit_work_step(
                work, DISPATCH, request_id="work-unit-bootstrap-invalid:dispatch") as dispatch:
            _must_refuse(lambda: access.guard_unit_bootstrap(
                dispatch, permission=other_permission))
            _must_refuse(lambda: access.guard_unit_bootstrap(
                dispatch, permission=wrong_scope))
            forged = type(dispatch)(dispatch.scope, dispatch.principal_id,
                dispatch.authenticated_actor, dispatch.request_id,
                dispatch.received_at, dispatch.trace_id)
            _must_refuse(lambda: access.guard_unit_bootstrap(
                forged, permission=permission))
        _must_refuse(lambda: access.guard_unit_bootstrap(
            work, permission=permission))

    with access.admit(caller, SCOPE, DISPATCH,
                      request_id="work-unit-bootstrap-direct-dispatch",
                      trace_id="trace-direct-dispatch") as dispatch:
        _must_refuse(lambda: access.guard_unit_bootstrap(
            dispatch, permission=permission))


def test_unit_bootstrap_refuses_nested_capability_and_existing_handoff(tmp_path):
    authority, caller, access = _access(
        WORK_INVOKE, DISPATCH, OTHER, "execution.units.start")
    permission = _unit_permission(authority, caller, access, tmp_path / "unit-root")
    with access.admit(caller, SCOPE, OTHER,
                      request_id="work-unit-bootstrap-nested", trace_id="trace-nested"):
        with access.admit(caller, SCOPE, DISPATCH,
                          request_id="work-unit-bootstrap-nested:dispatch",
                          trace_id="trace-nested") as nested_dispatch:
            _must_refuse(lambda: access.guard_unit_bootstrap(
                nested_dispatch, permission=permission))

    with access.admit(caller, SCOPE, WORK_INVOKE,
                      request_id="work-unit-bootstrap-capability-work",
                      trace_id="trace-capability") as work:
        with access.admit_work_step(
                work, DISPATCH,
                request_id="work-unit-bootstrap-capability:dispatch") as dispatch:
            with access.guard_current_capability(dispatch, SCOPE, DISPATCH):
                _must_refuse(lambda: access.guard_unit_bootstrap(
                    dispatch, permission=permission))

    stopped = Event()
    target = Thread(target=lambda: stopped.wait(3))
    target.start()
    try:
        with access.admit(caller, SCOPE, WORK_INVOKE,
                          request_id="work-unit-bootstrap-handoff-work",
                          trace_id="trace-handoff") as work:
            with access.admit_work_step(
                    work, DISPATCH,
                    request_id="work-unit-bootstrap-handoff:dispatch") as dispatch:
                with access.handoff_effect_write(
                        dispatch, invocation_key=b"x" * 32,
                        action_instances=(("step", "action"),),
                        target_thread=target,
                        expires_at=time.monotonic() + 2):
                    _must_refuse(lambda: access.guard_unit_bootstrap(
                        dispatch, permission=permission))
    finally:
        stopped.set()
        target.join(2)
    assert not target.is_alive()


def test_unit_bootstrap_exception_does_not_restore_dispatch_lease(tmp_path):
    authority, caller, access = _access(
        WORK_INVOKE, DISPATCH, "execution.units.start")
    permission = _unit_permission(authority, caller, access, tmp_path / "unit-root")
    with access.admit(caller, SCOPE, WORK_INVOKE,
                      request_id="work-unit-bootstrap-fail", trace_id="trace-fail") as work:
        with pytest.raises(ApplicationError):
            with access.admit_work_step(
                    work, DISPATCH, request_id="work-unit-bootstrap-fail:dispatch") as dispatch:
                with pytest.raises(RuntimeError, match="controlled Unit bootstrap failure"):
                    with access.guard_unit_bootstrap(dispatch, permission=permission):
                        raise RuntimeError("controlled Unit bootstrap failure")
                _must_refuse(lambda: access.require(dispatch, DISPATCH))
        _must_refuse(lambda: access.require(work, WORK_INVOKE))


def test_unit_bootstrap_does_not_restore_after_permission_credential_rotation(tmp_path):
    token = ["controlled-work-token"]
    authority, caller, access = _access(
        WORK_INVOKE, DISPATCH, token_provider=lambda: token[0])
    permission = _unit_permission(authority, caller, access, tmp_path / "unit-root")
    with access.admit(caller, SCOPE, WORK_INVOKE,
                      request_id="work-unit-bootstrap-rotate", trace_id="trace-rotate") as work:
        with pytest.raises(ApplicationError):
            with access.admit_work_step(
                    work, DISPATCH, request_id="work-unit-bootstrap-rotate:dispatch") as dispatch:
                with pytest.raises(ApplicationError):
                    with access.guard_unit_bootstrap(dispatch, permission=permission):
                        token[0] = "rotated-bootstrap-token"
                _must_refuse(lambda: access.require(dispatch, DISPATCH))
        _must_refuse(lambda: access.require(work, WORK_INVOKE))


def test_unit_bootstrap_preserves_original_expired_permission_refusal(tmp_path):
    authority, caller, access = _access(
        WORK_INVOKE, DISPATCH, "execution.units.start")
    permission = _unit_permission(
        authority, caller, access, tmp_path / "unit-root", expires_at=time.time() - 1)
    with access.admit(caller, SCOPE, WORK_INVOKE,
                      request_id="work-unit-bootstrap-expired", trace_id="trace-expired") as work:
        with pytest.raises(ApplicationError):
            with access.admit_work_step(
                    work, DISPATCH, request_id="work-unit-bootstrap-expired:dispatch") as dispatch:
                with pytest.raises(InvocationAuthorityRefused):
                    with access.guard_unit_bootstrap(dispatch, permission=permission):
                        with permission.guard("start"):
                            pytest.fail("expired Unit permission reached a protected operation")
                _must_refuse(lambda: access.require(dispatch, DISPATCH))
        _must_refuse(lambda: access.require(work, WORK_INVOKE))


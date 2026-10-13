"""Canonical operation identity reaches the original dispatch owner access gate.

Uses the actual W10 InstanceAccessAuthority and EngineeringCommandAccess
binding. It does not send a native operation or claim a production grant.
"""
import asyncio
import contextvars
from contextlib import contextmanager
from types import SimpleNamespace
import pytest

from ordessa_engineering.application.contracts.errors import ApplicationError
from ordessa_engineering.application.orchestration.steps.implementation_dispatch import (
    ImplementationDispatch,
)
from ordessa_interfaces.system_access.access_control.authentication import (
    AccessError,
    AccessGrant,
    InstanceAccessAuthority,
)
from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_system_access_bindings.engineering import EngineeringCommandAccess


CANONICAL = "engineering.executions.dispatch"
LEGACY = "engineering.implementation.dispatch"
SCOPE = Scope("canonical-dispatch-test-realm", "canonical-dispatch-test-project")
TOKEN = "controlled-canonical-dispatch-fixture-token"


def _access(capabilities):
    authority = InstanceAccessAuthority(
        lambda: TOKEN,
        principal_id="canonical-dispatch-test-agent",
        legacy_principal=None,
        grants=(AccessGrant(SCOPE, tuple(capabilities)),),
    )
    caller = authority.authenticate(f"Bearer {TOKEN}")
    return authority, caller, EngineeringCommandAccess(authority)


def test_canonical_dispatch_capability_reaches_original_owner_gate():
    """The original dispatch route consumes the same canonical W10 lease."""
    authority, caller, access = _access((CANONICAL,))
    owner = ImplementationDispatch(object(), access)
    with access.admit(caller, SCOPE, CANONICAL, request_id="dispatch-admit", trace_id="dispatch-admit") as context:
        # With no execution dependency configured, the call should pass its
        # production access gate and stop before any native effect. Before the
        # owner adopts CANONICAL, it instead fails at the private old gate.
        with pytest.raises(ApplicationError, match="DISPATCH_EXECUTION_AUTHORITY_UNAVAILABLE"):
            owner.dispatch("run-fixture", "step-fixture", 1, object(), {}, ("run_checks",), context)


def test_canonical_dispatch_gate_rejects_other_operation_identity():
    _authority, caller, access = _access((CANONICAL, LEGACY))
    owner = ImplementationDispatch(object(), access)
    with access.admit(caller, SCOPE, CANONICAL, request_id="dispatch-wrong-op", trace_id="dispatch-wrong-op") as context:
        with pytest.raises(ApplicationError, match="ACCESS_AUTHORITY_UNAVAILABLE"):
            owner._access(context, LEGACY)


def test_canonical_dispatch_effect_guard_uses_same_operation_lease():
    """Effect admission passes the operation gate, then rejects malformed binding."""
    _authority, caller, access = _access((CANONICAL,))
    owner = ImplementationDispatch(object(), access)
    with access.admit(caller, SCOPE, CANONICAL, request_id="dispatch-effect", trace_id="dispatch-effect") as context:
        async def enter_effect_guard():
            async with owner.acquire_effect_write(
                context, None, {}, asyncio.get_running_loop().time() + 1
            ):
                pytest.fail("malformed effect binding must never enter the write cut")

        with pytest.raises(ApplicationError, match="DISPATCH_EFFECT_BINDING_MISMATCH"):
            asyncio.run(enter_effect_guard())


def test_effect_factory_checks_canonical_lease_before_reading_original_binding():
    """The native effect factory uses canonical admission and reaches no write."""
    from ordessa_engineering.adapters.native_records.recorded_dispatch import (
        engineering_effect_write_guard_factory,
    )

    class ReachedReadback(Exception):
        pass

    @contextmanager
    def stop_before_read(_scope, _mode="read"):
        raise ReachedReadback
        yield  # pragma: no cover

    _authority, caller, access = _access((CANONICAL,))
    owner = ImplementationDispatch(
        SimpleNamespace(authority_id="canonical-test-authority", begin=stop_before_read), access
    )
    blobs = SimpleNamespace(authority_id="canonical-test-authority")
    owner.blobs = blobs
    with access.admit(caller, SCOPE, CANONICAL, request_id="dispatch-effect-factory",
                      trace_id="dispatch-effect-factory") as context:
        effect_factory = engineering_effect_write_guard_factory(owner, context, object(), blobs)
        # Its real first step is owner._access(context, EXECUTION_DISPATCH).
        # The fixture stops at the original binding read before any guard/write.
        with pytest.raises(ReachedReadback):
            effect_factory({}, "execution-op-fixture", "sha256:" + "0" * 64, {})


def test_missing_canonical_capability_is_denied_by_original_authority():
    authority, caller, _access_port = _access(())
    command_access = EngineeringCommandAccess(authority)
    with pytest.raises(AccessError):
        with command_access.admit(caller, SCOPE, CANONICAL,
                                  request_id="dispatch-no-auth", trace_id="dispatch-no-auth"):
            pytest.fail("the selected authority has no canonical dispatch permission")


def test_legacy_only_grant_cannot_admit_canonical_dispatch():
    authority, caller, access = _access((LEGACY,))
    with pytest.raises(AccessError):
        with access.admit(caller, SCOPE, CANONICAL,
                          request_id="dispatch-legacy-only", trace_id="dispatch-legacy-only"):
            pytest.fail("legacy permission must not act as a canonical alias")


@pytest.mark.parametrize("stale_cause", ["revoked", "credential-rotated"])
def test_stale_or_revoked_issued_caller_cannot_enter_canonical_gate(stale_cause):
    token = [TOKEN]
    authority = InstanceAccessAuthority(
        lambda: token[0], principal_id="canonical-dispatch-test-agent",
        legacy_principal=None, grants=(AccessGrant(SCOPE, (CANONICAL,)),),
    )
    stale_caller = authority.authenticate(f"Bearer {TOKEN}")
    access = EngineeringCommandAccess(authority)
    if stale_cause == "revoked":
        authority.revoke()
    else:
        token[0] = TOKEN + "-rotated"
    with pytest.raises(AccessError):
        with access.admit(stale_caller, SCOPE, CANONICAL,
                          request_id=f"dispatch-{stale_cause}", trace_id=f"dispatch-{stale_cause}"):
            pytest.fail("a caller issued before revocation/rotation must be stale")


def test_admission_lease_exit_invalidates_copied_context():
    _authority, caller, access = _access((CANONICAL,))
    with access.admit(caller, SCOPE, CANONICAL, request_id="dispatch-lease-exit",
                      trace_id="dispatch-lease-exit") as context:
        copied = contextvars.copy_context()
        access.require(context, CANONICAL)
    with pytest.raises(ApplicationError, match="ACCESS_AUTHORITY_UNAVAILABLE"):
        access.require(context, CANONICAL)
    with pytest.raises(ApplicationError, match="ACCESS_AUTHORITY_UNAVAILABLE"):
        copied.run(access.require, context, CANONICAL)


"""Mechanism tests for single-process bearer identity and exact access guards.

These tests use synthetic machine tokens. They do not assert human identity,
approval authority, or a production credential-provider integration.
"""
from __future__ import annotations

from dataclasses import FrozenInstanceError, replace
from threading import Event, Thread

import pytest

from ordessa_interfaces.system_access.contracts.refs import Scope
from ordessa_interfaces.system_access.access_control.authentication import (
    AccessError,
    AccessGrant,
    InstanceAccessAuthority,
)


SCOPE = Scope("realm-auth-test", "project-auth-test")
OTHER_SCOPE = Scope("realm-auth-test", "project-other")
TOKEN = "synthetic-instance-token"
CAPABILITIES = ("engineering.artifacts.read", "engineering.artifacts.write")


def _authority(token_provider=lambda: TOKEN, *, scope=SCOPE,
               capabilities=CAPABILITIES, principal_id="local", legacy_principal="local"):
    return InstanceAccessAuthority(
        token_provider,
        principal_id=principal_id,
        grants=(AccessGrant(scope, capabilities),),
        legacy_principal=legacy_principal,
    )


def _principal(authority: InstanceAccessAuthority):
    return authority.authenticate(f"Bearer {TOKEN}")


@pytest.mark.parametrize(
    ("authorization", "code"),
    (
        ("", "INVALID_AUTHORIZATION"),
        ("Basic synthetic-instance-token", "AUTHENTICATION_REQUIRED"),
        ("Bearer wrong-token", "AUTHENTICATION_REQUIRED"),
        ("Bearer " + "x" * 8192, "INVALID_AUTHORIZATION"),
        ({"authorization": f"Bearer {TOKEN}"}, "AUTHENTICATION_REQUIRED"),
    ),
)
def test_authentication_rejects_empty_wrong_oversized_and_non_string_credentials(authorization, code):
    authority = _authority()
    with pytest.raises(AccessError) as caught:
        authority.authenticate(authorization)
    assert caught.value.code == code


@pytest.mark.parametrize("provider_value", ("", "x" * 4097, "contains space", "non-ascii-🔒"))
def test_authority_rejects_invalid_or_oversized_provider_token(provider_value):
    with pytest.raises(AccessError) as caught:
        _authority(lambda: provider_value)
    assert caught.value.code == "AUTHORITY_UNAVAILABLE"


def test_authenticated_identity_is_machine_scoped_and_authority_local():
    authority = _authority()
    other_authority = _authority()
    principal = _principal(authority)

    assert principal.principal_id == "local"
    assert principal.kind == "machine"
    assert principal.assurance == "instance-bearer"
    with pytest.raises(FrozenInstanceError):
        principal.principal_id = "human"
    with pytest.raises(AccessError) as caught:
        replace(principal, kind="human")
    assert caught.value.code == "INVALID_PRINCIPAL"
    with pytest.raises(AccessError) as caught:
        with other_authority.guard(principal, SCOPE, CAPABILITIES[0]):
            pytest.fail("a principal issued by another authority must not be accepted")
    assert caught.value.code == "INVALID_PRINCIPAL"


def test_access_requires_exact_scope_and_capability_and_never_grants_approval():
    authority = _authority()
    principal = _principal(authority)

    with authority.guard(principal, SCOPE, CAPABILITIES[0]) as admitted:
        assert admitted is principal
    for scope, operation in (
        (OTHER_SCOPE, CAPABILITIES[0]),
        (SCOPE, "engineering.artifacts.delete"),
    ):
        with pytest.raises(AccessError) as caught:
            with authority.guard(principal, scope, operation):
                pytest.fail("ungranted scope or capability must be denied")
        assert caught.value.code == "ACCESS_DENIED"

    for capability in (
        "approval.grant",
        "engineering.approvals.grant",
        "engineering.records.record_consent",
        "engineering.*",
    ):
        with pytest.raises(AccessError) as caught:
            AccessGrant(SCOPE, (capability,))
        assert caught.value.code == "INVALID_CAPABILITY"


def test_revocation_grant_replacement_and_token_rotation_stale_old_principals():
    authority = _authority()
    principal = _principal(authority)
    authority.revoke()
    with pytest.raises(AccessError) as caught:
        with authority.guard(principal, SCOPE, CAPABILITIES[0]):
            pytest.fail("revoked identity must not enter a guarded operation")
    assert caught.value.code == "AUTHORIZATION_STALE"

    replaced = _authority()
    before_replacement = _principal(replaced)
    replaced.replace_grants((AccessGrant(SCOPE, (CAPABILITIES[0],)),))
    with pytest.raises(AccessError) as caught:
        with replaced.guard(before_replacement, SCOPE, CAPABILITIES[0]):
            pytest.fail("grant replacement invalidates earlier principal snapshots")
    assert caught.value.code == "AUTHORIZATION_STALE"

    current_token = ["token-before-rotation"]
    rotating = _authority(lambda: current_token[0])
    old_principal = rotating.authenticate("Bearer token-before-rotation")
    current_token[0] = "token-after-rotation"
    fresh_principal = rotating.authenticate("Bearer token-after-rotation")
    assert fresh_principal.credential_epoch > old_principal.credential_epoch
    with pytest.raises(AccessError) as caught:
        with rotating.guard(old_principal, SCOPE, CAPABILITIES[0]):
            pytest.fail("token rotation invalidates principals from the prior token")
    assert caught.value.code == "AUTHORIZATION_STALE"


def test_guard_blocks_same_thread_authority_mutation_until_guard_exits():
    authority = _authority()
    principal = _principal(authority)
    epoch = authority.credential_epoch

    with authority.guard(principal, SCOPE, CAPABILITIES[0]):
        for change in (authority.revoke, lambda: authority.replace_grants(())):
            with pytest.raises(AccessError) as caught:
                change()
            assert caught.value.code == "AUTHORIZATION_GUARD_ACTIVE"
        assert authority.credential_epoch == epoch

    assert authority.revoke() == epoch + 1


def test_other_thread_revocation_waits_for_guard_and_invalidates_after_exit():
    authority = _authority()
    principal = _principal(authority)
    entered_guard = Event()
    release_guard = Event()
    revoke_started = Event()
    revoke_finished = Event()
    thread_errors: list[BaseException] = []

    def revoke_from_other_thread():
        try:
            revoke_started.set()
            authority.revoke()
            revoke_finished.set()
        except BaseException as error:  # retain unexpected thread failures for the assertion
            thread_errors.append(error)
            revoke_finished.set()

    def hold_guard():
        try:
            with authority.guard(principal, SCOPE, CAPABILITIES[0]):
                entered_guard.set()
                if not release_guard.wait(2):
                    thread_errors.append(AssertionError("test failed to release guarded operation"))
        except BaseException as error:
            thread_errors.append(error)

    worker = Thread(target=revoke_from_other_thread, daemon=True)
    guard_worker = Thread(target=hold_guard, daemon=True)
    try:
        guard_worker.start()
        assert entered_guard.wait(1), "guard thread did not enter"
        worker.start()
        assert revoke_started.wait(1), "revocation thread did not start"
        assert not revoke_finished.wait(0.05), "revocation passed an active guard"
        release_guard.set()
        assert revoke_finished.wait(1), "revocation did not resume after guard exit"
        guard_worker.join(1)
        assert not guard_worker.is_alive(), "guard thread did not finish"
        worker.join(1)
        assert not worker.is_alive(), "revocation thread did not finish"
    finally:
        release_guard.set()
        if guard_worker.ident is not None:
            guard_worker.join(1)
        if worker.ident is not None:
            worker.join(1)

    assert thread_errors == []
    with pytest.raises(AccessError) as caught:
        with authority.guard(principal, SCOPE, CAPABILITIES[0]):
            pytest.fail("principal used before revocation must be stale")
    assert caught.value.code == "AUTHORIZATION_STALE"


def test_legacy_local_identity_requires_an_explicit_local_binding():
    authority_without_legacy = _authority(legacy_principal=None)
    principal = _principal(authority_without_legacy)
    with pytest.raises(AccessError) as caught:
        with authority_without_legacy.guard_legacy(principal):
            pytest.fail("legacy access must be disabled without explicit mapping")
    assert caught.value.code == "LEGACY_IDENTITY_UNAVAILABLE"

    explicitly_local = _authority()
    local_principal = _principal(explicitly_local)
    with explicitly_local.guard_legacy(local_principal) as admitted:
        assert admitted is local_principal

    with pytest.raises(AccessError) as caught:
        _authority(principal_id="service-worker", legacy_principal="local")
    assert caught.value.code == "INVALID_LEGACY_BINDING"


def test_revoked_credential_cannot_authenticate_again_or_be_revived_by_grant_change():
    token = [TOKEN]
    authority = _authority(lambda: token[0])
    authority.revoke()
    authority.replace_grants((AccessGrant(SCOPE, CAPABILITIES),))
    with pytest.raises(AccessError) as rejected:
        _principal(authority)
    assert rejected.value.code == "AUTHENTICATION_REQUIRED"
    token[0] = "new-synthetic-rotated-token"
    fresh = authority.authenticate("Bearer " + token[0])
    with authority.guard(fresh, SCOPE, CAPABILITIES[0]):
        pass


def test_runtime_lease_invalidation_preserves_credential_but_retires_old_snapshot():
    authority = _authority()
    old = _principal(authority)
    authority.invalidate()
    with pytest.raises(AccessError) as rejected:
        authority.verify(old)
    assert rejected.value.code == "AUTHORIZATION_STALE"
    fresh = _principal(authority)
    authority.verify(fresh)
    assert fresh.credential_epoch > old.credential_epoch

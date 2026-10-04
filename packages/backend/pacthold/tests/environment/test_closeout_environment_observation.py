"""E3 closeout regressions for Environment-owned authority and observation."""
from __future__ import annotations

from dataclasses import dataclass
import time

import pytest

from ordessa_environment_api import (
    AdmissionRefusedError,
    AuthorityConflictError,
    AuthorityKey,
    AuthorityRegistration,
    CanonicalFactTarget,
    IdentityMismatchError,
)
from pacthold.core.registration import CoreContributionSet
from pacthold.environment import (
    Environment,
    InstallationRecord,
    ObservationAttachmentUnknownError,
    ObservationReleasePendingError,
)


@dataclass(frozen=True)
class _Contract:
    contract_id = "closeout.observe@1"


@dataclass(frozen=True)
class _OtherContract:
    contract_id = "other.observe@1"


class _AllowPolicy:
    def admit_invoke(self, principal, surface, guarantee):
        return True

    def admit_object_access(self, principal, object_ref, mode):
        return mode == "observe"


class _Source:
    def __init__(self, events=()):
        self.events = tuple(events)
        self.detaches = 0
        self.cursor = None
        self.sink = None

    def attach(self, sink, *, cursor=None):
        self.cursor = cursor
        self.sink = sink
        for kind, *args in self.events:
            getattr(sink, kind)(*args)

        def detach():
            self.detaches += 1

        return detach


def _setup():
    environment = Environment("env-closeout", policy=_AllowPolicy())
    environment.install(InstallationRecord("closeout.plugin", "a" * 64))
    environment.enable("closeout.plugin")
    activation = environment.activate(
        "closeout.plugin", CoreContributionSet(contracts=(_Contract,))
    ).activation
    target = CanonicalFactTarget("workspace", "ordessa.workspace", "workspace:one")
    registration = AuthorityRegistration(
        key=AuthorityKey("configuration", target),
        declaring_owner_domain="closeout.plugin",
        target_schema_id="ordessa.workspace.configuration@1",
        schema_major=1,
    )
    environment.register_authority(registration, activation)
    binding = environment.bind("closeout.observe")
    return environment, activation, target, registration, binding


def test_read_and_subscribe_delivers_snapshot_then_delta_with_bounded_credit():
    environment, _activation, target, _registration, binding = _setup()
    source = _Source((
        ("snapshot", "r1", {"name": "one"}),
        ("delta", "r2", {"name": "two"}),
    ))

    handle = environment.read_and_subscribe(binding, target, None, 1, source=source)
    first = handle.observe(None, 1, 0)
    assert [frame.kind for frame in first.frames] == ["snapshot"]
    assert first.frames[0].value == {"name": "one"}
    assert first.frames[0].source["providerActivation"] == "closeout.plugin@1"

    second = handle.observe(first.cursor, 1, 0)
    assert [frame.kind for frame in second.frames] == ["delta"]
    assert second.frames[0].patch == {"name": "two"}
    handle.release()
    assert source.detaches == 1


def test_resume_gap_is_visible_before_new_full_snapshot():
    environment, _activation, target, _registration, binding = _setup()
    source = _Source((("gap", "history-unavailable"), ("snapshot", "r9", {"fresh": True})))

    handle = environment.read_and_subscribe(binding, target, "old-cursor", 2, source=source)
    batch = handle.observe("old-cursor", 2, 0)

    assert [frame.kind for frame in batch.frames] == ["gap", "snapshot"]
    assert batch.frames[0].reason == "history-unavailable"
    assert batch.frames[1].value == {"fresh": True}
    assert batch.resync_required is False
    handle.release()


def test_zero_credit_returns_only_gap_and_never_leaks_initial_snapshot():
    environment, _activation, target, _registration, binding = _setup()
    source = _Source((("snapshot", "r1", {"secret": "must-not-escape"}),))

    handle = environment.read_and_subscribe(binding, target, None, 0, source=source)
    batch = handle.observe(None, 5, 0)

    assert [frame.kind for frame in batch.frames] == ["gap"]
    assert batch.frames[0].reason == "zero-credit"
    assert "secret" not in repr(batch)
    handle.release()


def test_buffer_overflow_becomes_gap_and_never_truncates_as_current_state():
    environment, _activation, target, _registration, binding = _setup()
    source = _Source(
        (("snapshot", "r0", {"n": 0}),)
        + tuple(("delta", f"r{i}", {"n": i}) for i in range(1, 65))
    )

    handle = environment.read_and_subscribe(binding, target, None, 1, source=source)
    batch = handle.observe(None, 64, 0)

    assert [frame.kind for frame in batch.frames] == ["gap"]
    assert batch.frames[0].reason == "buffer-overflow"
    assert batch.resync_required is True
    handle.release()


def test_authority_is_single_writer_and_exact_registration_is_idempotent():
    environment, activation, target, registration, _binding = _setup()
    assert environment.register_authority(registration, activation) == registration

    environment.install(InstallationRecord("other.plugin", "b" * 64))
    environment.enable("other.plugin")
    other = environment.activate(
        "other.plugin", CoreContributionSet(contracts=(_OtherContract,))
    ).activation
    conflicting = AuthorityRegistration(
        key=registration.key,
        declaring_owner_domain="other.plugin",
        target_schema_id=registration.target_schema_id,
        schema_major=1,
    )
    with pytest.raises(AuthorityConflictError):
        environment.register_authority(conflicting, other)


def test_observation_ref_cannot_cross_principal_or_target():
    environment, _activation, target, _registration, binding = _setup()
    handle = environment.read_and_subscribe(
        binding, target, None, 1, source=_Source((("snapshot", "r1", {"ok": True}),)),
        principal="user:one",
    )
    other_target = CanonicalFactTarget("workspace", "ordessa.workspace", "workspace:two")
    with pytest.raises(IdentityMismatchError):
        environment.observe(
            handle.ref, None, 1, 0, principal="user:two", target=target,
        )
    with pytest.raises(IdentityMismatchError):
        environment.observe(
            handle.ref, None, 1, 0, principal="user:one", target=other_target,
        )
    handle.release()


def test_subscription_blocks_drain_and_idempotent_release_unblocks_it():
    environment, activation, target, _registration, binding = _setup()
    source = _Source((("snapshot", "r1", {"ok": True}),))
    handle = environment.read_and_subscribe(binding, target, None, 1, source=source)

    cut = environment.drain(activation)
    assert any(item.startswith("active-subscription:") for item in cut.blockers)
    handle.release()
    handle.release()
    cut_after_release = environment.drain(activation)
    assert not any(item.startswith("active-subscription:") for item in cut_after_release.blockers)
    assert source.detaches == 1


def test_lease_expiry_detaches_without_background_worker_and_unblocks_drain():
    environment, activation, target, _registration, binding = _setup()
    source = _Source((("snapshot", "r1", {"ok": True}),))
    environment.read_and_subscribe(
        binding, target, None, 1, source=source, lease_seconds=0.01,
    )
    time.sleep(0.03)

    cut = environment.drain(activation)
    assert source.detaches == 1
    assert not any(item.startswith("active-subscription:") for item in cut.blockers)


def test_attach_callback_can_reenter_drain_without_holding_environment_lock():
    environment, activation, target, _registration, binding = _setup()

    class ReentrantSource:
        cut = None

        def attach(self, sink, *, cursor=None):
            self.cut = environment.drain(activation)
            sink.snapshot("r1", {"ok": True})
            return lambda: None

    source = ReentrantSource()
    handle = environment.read_and_subscribe(binding, target, None, 1, source=source)
    assert any(item.startswith("active-subscription:") for item in source.cut.blockers)
    assert handle.observe().frames[0].kind == "snapshot"
    handle.release()


def test_non_observe_policy_refusal_does_not_attach_source():
    environment, _activation, target, _registration, binding = _setup()

    class DenyObserve(_AllowPolicy):
        def admit_object_access(self, principal, object_ref, mode):
            return False

    environment._policy = DenyObserve()
    source = _Source((("snapshot", "r1", {"no": "attach"}),))
    with pytest.raises(AdmissionRefusedError):
        environment.read_and_subscribe(binding, target, None, 1, source=source)
    assert source.detaches == 0


def test_missing_policy_refuses_protected_observation():
    environment, _activation, target, _registration, binding = _setup()
    environment._policy = None
    source = _Source((("snapshot", "r1", {"no": "attach"}),))
    with pytest.raises(AdmissionRefusedError, match="policy is unavailable"):
        environment.read_and_subscribe(binding, target, None, 1, source=source)
    assert source.detaches == 0


def test_successful_empty_read_renews_idle_observer_lease(monkeypatch):
    from pacthold import environment as environment_module

    current = [1.0]
    monkeypatch.setattr(environment_module.time, "monotonic", lambda: current[0])
    environment, _activation, target, _registration, binding = _setup()
    source = _Source((("snapshot", "r1", {"ok": True}),))
    handle = environment.read_and_subscribe(
        binding, target, None, 1, source=source, lease_seconds=10,
    )
    assert handle.observe(None, 1, 0).frames[0].kind == "snapshot"
    current[0] = 5.0
    assert handle.observe(None, 1, 0).frames == ()

    # This is past the original deadline (11s), but before the renewed one (15s).
    current[0] = 12.0
    assert handle.observe(None, 1, 0).frames == ()
    handle.release()


def test_detach_failure_remains_retirement_blocker_until_same_detach_retries():
    environment, activation, target, _registration, binding = _setup()

    class FlakyDetachSource(_Source):
        def __init__(self):
            super().__init__((("snapshot", "r1", {"ok": True}),))
            self.attempts = 0

        def attach(self, sink, *, cursor=None):
            detach = super().attach(sink, cursor=cursor)

            def flaky_detach():
                self.attempts += 1
                if self.attempts == 1:
                    raise RuntimeError("detach outcome not confirmed")
                detach()

            return flaky_detach

    source = FlakyDetachSource()
    handle = environment.read_and_subscribe(binding, target, None, 1, source=source)
    with pytest.raises(ObservationReleasePendingError) as pending:
        handle.release()
    assert pending.value.ref == handle.ref
    cut = environment.drain(activation)
    assert any(item.startswith("observation-detach-pending:") for item in cut.blockers)

    handle.release()
    assert source.attempts == 2
    cut_after = environment.drain(activation)
    assert not any("subscription:" in item or "detach-pending:" in item for item in cut_after.blockers)


def test_attach_exception_keeps_unknown_settlement_blocker_until_confirmed():
    environment, activation, target, _registration, binding = _setup()

    class AttachThenThrow:
        def attach(self, sink, *, cursor=None):
            sink.snapshot("r1", {"possibly-attached": True})
            raise RuntimeError("provider failed after attaching callback")

    with pytest.raises(ObservationAttachmentUnknownError) as unknown:
        environment.read_and_subscribe(binding, target, None, 1, source=AttachThenThrow())
    ref = unknown.value.ref
    cut = environment.drain(activation)
    assert any(item.startswith("observation-attach-unknown:") for item in cut.blockers)
    with pytest.raises(AdmissionRefusedError):
        environment.resolve_observation_attachment(
            ref, principal="local", target=target, confirmed_detached=False,
        )

    environment.resolve_observation_attachment(
        ref, principal="local", target=target, confirmed_detached=True,
    )
    cut_after = environment.drain(activation)
    assert not any("observation-attach-unknown:" in item for item in cut_after.blockers)


def test_permission_revocation_redacts_queue_and_late_source_frames_are_fenced():
    environment, _activation, target, _registration, binding = _setup()
    source = _Source((("snapshot", "r1", {"secret": "queued"}),))
    handle = environment.read_and_subscribe(binding, target, None, 1, source=source)

    class DenyObserve(_AllowPolicy):
        def admit_object_access(self, principal, object_ref, mode):
            return False

    environment._policy = DenyObserve()
    with pytest.raises(AdmissionRefusedError, match="policy"):
        handle.observe(None, 1, 0)
    source.sink.snapshot("r2", {"secret": "late"})
    entry = environment._subscriptions[handle.ref.subscription_id]
    assert entry.released is True
    assert entry.queue == []
    assert source.detaches == 1

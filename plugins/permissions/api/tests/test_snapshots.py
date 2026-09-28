"""T01 red/green: a snapshot is bound to one runtime identity or it is nothing."""
from __future__ import annotations

import datetime as dt

import pytest

from ordessa_permissions_api import EffectivePolicySnapshot, PolicyRefusal

NOW = dt.datetime(2026, 9, 28, 12, 0, tzinfo=dt.timezone.utc)


def binding(**overrides: object) -> dict:
    base: dict = {
        "server_instance_id": "srv-1",
        "session_id": "sess-1",
        "native_session_id": "chan-9",
        "runtime_generation": "gen-3",
        "principal": "user-1",
        "ceiling_revision": "admin-default@3",
        "intent_revision": "profile-a@2",
        "issued_at": NOW,
        "expires_at": NOW + dt.timedelta(minutes=5),
    }
    base.update(overrides)
    return base


def test_a_complete_binding_produces_a_recomputable_digest() -> None:
    snapshot = EffectivePolicySnapshot.issue(**binding())
    assert snapshot.digest and len(snapshot.digest) == 64
    assert EffectivePolicySnapshot.issue(**binding()).digest == snapshot.digest
    assert snapshot.valid_at(NOW)
    assert snapshot.server_instance_id == "srv-1"


@pytest.mark.parametrize("field", [
    "server_instance_id", "session_id", "native_session_id", "runtime_generation",
    "principal", "ceiling_revision", "intent_revision", "issued_at", "expires_at",
])
def test_a_snapshot_that_misses_any_binding_field_refuses(field: str) -> None:
    kwargs = binding()
    kwargs[field] = None
    with pytest.raises(PolicyRefusal) as exc:
        EffectivePolicySnapshot.issue(**kwargs)  # type: ignore[arg-type]
    assert exc.value.code == "PERMISSION_SNAPSHOT_INVALID"
    assert field in str(exc.value)


@pytest.mark.parametrize("blank", ["", "   ", "x" * 400])
def test_a_blank_or_unbounded_binding_text_is_not_a_binding(blank: str) -> None:
    with pytest.raises(PolicyRefusal) as exc:
        EffectivePolicySnapshot.issue(**binding(session_id=blank))
    assert exc.value.code == "PERMISSION_SNAPSHOT_INVALID"


def test_changing_any_bound_field_changes_the_digest() -> None:
    base = EffectivePolicySnapshot.issue(**binding())
    for field in ("server_instance_id", "session_id", "native_session_id",
                  "runtime_generation", "principal", "ceiling_revision", "intent_revision"):
        other = EffectivePolicySnapshot.issue(**binding(**{field: "different"}))
        assert other.digest != base.digest, field


def test_a_forged_digest_is_refused_not_recomputed_silently() -> None:
    record = EffectivePolicySnapshot.issue(**binding()).as_record()
    record["digest"] = "0" * 64
    with pytest.raises(PolicyRefusal) as exc:
        EffectivePolicySnapshot.from_record(record)
    assert exc.value.code == "PERMISSION_SNAPSHOT_INVALID"


def test_a_record_with_unknown_fields_is_refused() -> None:
    record = EffectivePolicySnapshot.issue(**binding()).as_record()
    record["toolCanRunWithoutApproval"] = True
    with pytest.raises(PolicyRefusal) as exc:
        EffectivePolicySnapshot.from_record(record)
    assert exc.value.code == "PERMISSION_SNAPSHOT_INVALID"


def test_expiry_is_part_of_validity_and_is_a_hard_bound() -> None:
    snapshot = EffectivePolicySnapshot.issue(**binding())
    assert snapshot.valid_at(NOW + dt.timedelta(minutes=5))
    assert not snapshot.valid_at(NOW + dt.timedelta(minutes=5, seconds=1))
    assert not snapshot.valid_at(NOW - dt.timedelta(seconds=1))


def test_expires_at_must_be_after_issued_at() -> None:
    with pytest.raises(PolicyRefusal) as exc:
        EffectivePolicySnapshot.issue(**binding(expires_at=NOW - dt.timedelta(hours=1)))
    assert exc.value.code == "PERMISSION_SNAPSHOT_INVALID"


def test_a_snapshot_bound_to_another_runtime_generation_does_not_cover_it() -> None:
    snapshot = EffectivePolicySnapshot.issue(**binding())
    assert snapshot.covers(**binding())
    assert not snapshot.covers(**binding(native_session_id="chan-other"))
    assert not snapshot.covers(**binding(runtime_generation="gen-4"))


def test_no_binding_field_is_a_timestamp_pair_only_one_is_enough_to_be_stale() -> None:
    snapshot = EffectivePolicySnapshot.issue(**binding())
    assert snapshot.issued_at < snapshot.expires_at
    assert snapshot.age_at(NOW + dt.timedelta(minutes=1)) == dt.timedelta(minutes=1)

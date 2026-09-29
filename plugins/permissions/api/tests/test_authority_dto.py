"""PE1-1: the `AuthorityRecord` DTO and its query-port contract.

The authority fact record is a frozen read model over stores that already
exist; these tests pin its construction discipline (closed fields, declared
nullability, deterministic ids, aware timestamps) and the guarantee the C4
alignment (AR-1) leans on: the record carries a stable identity and a wire
family that the platform already defines - no new family is invented here.
"""
from __future__ import annotations

import datetime as dt

import pytest
from ordessa_permissions_api import (
    PERMISSION_ERROR_FAMILIES,
    AuthorityRecord,
    AuthorityScope,
    AuthoritySourceKind,
    AuthorityStateKind,
    PolicyRefusal,
    authority_id_for,
)

UTC = dt.timezone.utc
BASE = dict(
    source="approval_grant", scope="session", tool="bash", state="active",
    fact_ref="approval_abc",
)


def test_record_round_trips_through_its_closed_record_shape():
    expires = dt.datetime(2026, 9, 28, 12, 5, tzinfo=UTC)
    record = AuthorityRecord.of(
        **BASE, target="/repo/a.py", operation_digest="a" * 64,
        requested_by="user-1", approved_by="user-2",
        granted_at=dt.datetime(2026, 9, 28, 12, 0, tzinfo=UTC),
        expires_at=expires, revision=3)
    raw = record.as_record()
    assert set(raw) == {"authorityId", "source", "scope", "tool", "target",
                        "operationDigest", "requestedBy", "approvedBy", "grantedAt",
                        "expiresAt", "state", "revision", "factRef"}
    rebuilt = AuthorityRecord.from_record(raw)
    assert rebuilt == record
    assert rebuilt.scope is AuthorityScope.SESSION
    assert rebuilt.state is AuthorityStateKind.ACTIVE


def test_the_record_is_frozen():
    record = AuthorityRecord.of(**BASE)
    with pytest.raises(Exception):
        record.tool = "read"  # type: ignore[misc]


def test_unknown_and_missing_fields_are_refused_not_ignored():
    with pytest.raises(PolicyRefusal):
        AuthorityRecord.from_record({**BASE, "toolKey": "bash"})
    with pytest.raises(PolicyRefusal):
        AuthorityRecord.from_record({"source": "approval_grant", "scope": "session"})


def test_the_id_is_deterministic_and_the_same_fact_never_mints_two_ids():
    first = authority_id_for(source="approval_grant", fact_ref="approval_abc")
    second = authority_id_for(source="approval_grant", fact_ref="approval_abc")
    other = authority_id_for(source="approval_grant", fact_ref="approval_xyz")
    assert first == second and first != other
    record = AuthorityRecord.of(**BASE)
    assert record.authority_id == first
    assert AuthorityRecord.of(**BASE).authority_id == first


def test_naive_timestamps_and_bad_digests_are_refused():
    with pytest.raises(PolicyRefusal):
        AuthorityRecord.of(**BASE, expires_at=dt.datetime(2026, 9, 28, 12, 5))
    with pytest.raises(PolicyRefusal):
        AuthorityRecord.of(**BASE, operation_digest="zz" * 32)
    with pytest.raises(PolicyRefusal):
        AuthorityRecord.of(**BASE, operation_digest="a" * 63)
    # a 64-hex digest and an ISO string timestamp are accepted spellings
    record = AuthorityRecord.of(**BASE, operation_digest="a" * 64,
                                expires_at="2026-09-28T12:05:00+00:00")
    assert record.operation_digest == "a" * 64
    assert record.expires_at is not None and record.expires_at.tzinfo is not None


def test_unknown_enum_spellings_are_refused_not_coerced():
    def without(*keys):
        return {key: value for key, value in BASE.items() if key not in keys}
    with pytest.raises(PolicyRefusal):
        AuthorityRecord.of(**without("scope"), scope="galaxy")
    with pytest.raises(PolicyRefusal):
        AuthorityRecord.of(**without("state"), state="pending")
    with pytest.raises(PolicyRefusal):
        AuthorityRecord.of(**without("source"), source="somewhere-else")
    # the stored `project` spelling maps onto PROFILE at the projection site
    # (the backend's rule reader), not by silently coercing it here
    with pytest.raises(PolicyRefusal):
        AuthorityRecord.of(**without("scope"), scope="project")


def test_effective_and_alive_mean_active_only():
    no_state = {key: value for key, value in BASE.items() if key != "state"}
    active = AuthorityRecord.of(**BASE, expires_at="2026-09-28T12:05:00+00:00")
    expired = AuthorityRecord.of(**no_state, state="expired")
    revoked = AuthorityRecord.of(**no_state, state="revoked")
    assert active.effective and expired.effective is False and revoked.effective is False
    assert active.alive_at(dt.datetime(2026, 9, 28, 12, 4, 59, tzinfo=UTC)) is True
    assert active.alive_at(dt.datetime(2026, 9, 28, 12, 5, 1, tzinfo=UTC)) is False
    # no expiry recorded is a declared absence, never "unlimited"
    standing = AuthorityRecord.of(**BASE)
    assert standing.expires_at is None
    assert standing.alive_at(dt.datetime(2126, 1, 1, tzinfo=UTC)) is True


def test_the_three_scopes_are_the_dispatch_vocabulary():
    for spelling, expected in (("session", AuthorityScope.SESSION),
                               ("user", AuthorityScope.USER),
                               ("profile", AuthorityScope.PROFILE)):
        record = AuthorityRecord.of(**{k: v for k, v in BASE.items()
                                       if k != "scope"}, scope=spelling)
        assert record.scope is expected


def test_every_emittable_code_already_has_a_platform_wire_family():
    """AR-1 alignment: the record's refusal vocabulary rides the existing
    `PERMISSION_AUTHORIZATION_INVALID` family - no new family is added."""
    assert PERMISSION_ERROR_FAMILIES["PERMISSION_AUTHORIZATION_INVALID"] \
        == "INVALID_REQUEST"
    with pytest.raises(PolicyRefusal):
        AuthorityRecord.of(**{k: v for k, v in BASE.items() if k != "fact_ref"},
                           fact_ref=None)

"""T01 red/green: the ceiling is a non-widenable upper bound (FR-01, FR-02).

The two behaviours under test are the ones the legacy engine cannot express: a
ceiling record may only come from a trusted source, and several ceilings
**intersect** instead of the last one winning.
"""
from __future__ import annotations

import datetime as dt

import pytest

from ordessa_permissions_api import (
    CeilingEntry,
    CeilingSource,
    ExposureLevel,
    PolicyCeiling,
    PolicyRefusal,
    Scope,
    intersect_ceilings,
)


def trusted(**overrides: object) -> dict:
    record: dict = {
        "policyId": "admin-default",
        "scope": "admin",
        "revision": 3,
        "source": "signed-admin",
        "signed": True,
        "deny": [{"key": "edit", "pattern": "/etc/*"}],
        "requireApproval": [{"key": "bash"}],
        "maximumExposure": "exec",
        "effectiveFrom": "2026-09-01T00:00:00+00:00",
    }
    record.update(overrides)
    return record


def test_a_trusted_record_builds_a_ceiling_with_every_declared_field() -> None:
    ceiling = PolicyCeiling.from_record(trusted())
    assert ceiling.policy_id == "admin-default"
    assert ceiling.scope is Scope.ADMIN
    assert ceiling.revision == 3
    assert ceiling.source is CeilingSource.SIGNED_ADMIN
    assert ceiling.is_trusted
    assert ceiling.maximum_exposure is ExposureLevel.EXEC
    assert ceiling.effective_from == dt.datetime(2026, 9, 1, tzinfo=dt.timezone.utc)


def test_unknown_record_key_is_refused_rather_than_ignored() -> None:
    with pytest.raises(PolicyRefusal) as exc:
        PolicyCeiling.from_record(trusted(defaultAction="allow"))
    assert exc.value.code == "PERMISSION_CEILING_INVALID"
    assert "defaultAction" in str(exc.value)


@pytest.mark.parametrize("bad", [{}, None, "x", 3, ["policyId"]])
def test_a_ceiling_must_be_an_object(bad: object) -> None:
    with pytest.raises(PolicyRefusal) as exc:
        PolicyCeiling.from_record(bad)  # type: ignore[arg-type]
    assert exc.value.code == "PERMISSION_CEILING_INVALID"


def test_revision_must_be_a_positive_integer() -> None:
    for bad in (0, -1, "3", None, True):
        with pytest.raises(PolicyRefusal) as exc:
            PolicyCeiling.from_record(trusted(revision=bad))
        assert exc.value.code == "PERMISSION_CEILING_INVALID"


def test_effective_from_must_be_an_aware_timestamp() -> None:
    with pytest.raises(PolicyRefusal) as exc:
        PolicyCeiling.from_record(trusted(effectiveFrom=None))
    assert exc.value.code == "PERMISSION_CEILING_INVALID"
    with pytest.raises(PolicyRefusal) as exc2:
        PolicyCeiling.from_record(
            trusted(effectiveFrom=dt.datetime(2026, 9, 1)))  # naive
    assert exc2.value.code == "PERMISSION_CEILING_INVALID"


# --- provenance: absence of trust is modelled, never read as "no limit" ----

def test_unsigned_provenance_is_refused_as_unverified_not_treated_as_absent() -> None:
    with pytest.raises(PolicyRefusal) as exc:
        PolicyCeiling.from_record(trusted(signed=False))
    assert exc.value.code == "POLICY_SCOPE_UNVERIFIED"


def test_an_unknown_or_host_invented_source_is_refused() -> None:
    with pytest.raises(PolicyRefusal) as exc:
        PolicyCeiling.from_record(trusted(source="profile-store"))
    assert exc.value.code == "POLICY_SCOPE_UNVERIFIED"
    assert PolicyCeiling.from_record(trusted(source="host-trusted")).is_trusted


def test_missing_source_provenance_is_refused() -> None:
    record = trusted()
    del record["source"]
    with pytest.raises(PolicyRefusal) as exc:
        PolicyCeiling.from_record(record)
    assert exc.value.code == "POLICY_SCOPE_UNVERIFIED"


@pytest.mark.parametrize("scope", ["session", "project"])
def test_a_low_trust_scope_cannot_claim_ceiling_authority(scope: str) -> None:
    # Cross-scope promotion is refused at the door: a session/project record
    # can never *be* an administrator ceiling.
    with pytest.raises(PolicyRefusal) as exc:
        PolicyCeiling.from_record(trusted(scope=scope))
    assert exc.value.code == "POLICY_SCOPE_UNVERIFIED"


def test_absence_is_explicitly_modelled_as_unverified() -> None:
    ceiling = PolicyCeiling.unverified("host-observed")
    assert ceiling.source is CeilingSource.UNVERIFIED
    assert not ceiling.is_trusted
    assert ceiling.hard_denies == ()
    assert ceiling.require_approval == ()


# --- entries ---------------------------------------------------------------

def test_deny_entries_are_typed_and_their_tool_key_vocabulary_is_closed() -> None:
    with pytest.raises(PolicyRefusal) as exc:
        PolicyCeiling.from_record(trusted(deny=[{"key": "delete_prod", "pattern": None}]))
    assert exc.value.code == "PERMISSION_UNKNOWN_TOOL"
    with pytest.raises(PolicyRefusal) as exc2:
        PolicyCeiling.from_record(trusted(deny=[{"key": "bash", "action": "allow"}]))
    assert exc2.value.code == "PERMISSION_CEILING_INVALID"


def test_a_ceiling_entry_cannot_ask_for_approval_by_being_an_allow_rule() -> None:
    # The ceiling vocabulary is *restrictions only*: an `allow` entry is a
    # widening attempt and is refused.
    with pytest.raises(PolicyRefusal) as exc:
        CeilingEntry.of("bash", action="allow")
    assert exc.value.code == "PERMISSION_CEILING_INVALID"


def test_entries_match_their_declared_tool_and_target_only() -> None:
    entry = CeilingEntry.of("edit", pattern="/etc/*")
    assert entry.matches("edit", "/etc/passwd")
    assert not entry.matches("read", "/etc/passwd")
    assert not entry.matches("edit", "/srv/app.ts")
    assert CeilingEntry.of("bash").matches("bash", "anything")


def test_maximum_exposure_is_a_closed_ordered_vocabulary() -> None:
    assert ExposureLevel.of("read").rank < ExposureLevel.of("write").rank
    assert ExposureLevel.of("write").rank < ExposureLevel.of("network").rank
    assert ExposureLevel.of("network").rank < ExposureLevel.of("exec").rank
    assert ExposureLevel.of("exec").rank < ExposureLevel.of("full").rank
    with pytest.raises(PolicyRefusal) as exc:
        ExposureLevel.of("mostly-safe")
    assert exc.value.code == "PERMISSION_CEILING_INVALID"


# --- intersection ----------------------------------------------------------

def test_two_ceilings_intersect_and_never_widen() -> None:
    strict_reads = PolicyCeiling.from_record(
        trusted(policyId="a", maximumExposure="read", deny=[], requireApproval=[]))
    blocks_bash = PolicyCeiling.from_record(
        trusted(policyId="b", revision=7, source="host-trusted",
                deny=[{"key": "bash", "pattern": None}],
                requireApproval=[{"key": "edit"}], maximumExposure="exec"))
    effective = intersect_ceilings([strict_reads, blocks_bash])
    assert effective.maximum_exposure is ExposureLevel.READ
    assert effective.blocks("bash", "ls")
    assert effective.requires_approval("edit", "src/app.ts")
    assert effective.revision_digest != strict_reads.revision_digest


def test_intersection_is_order_independent_so_nothing_is_last_wins() -> None:
    a = PolicyCeiling.from_record(trusted(policyId="a"))
    b = PolicyCeiling.from_record(trusted(policyId="b", revision=9, source="host-trusted"))
    forward = intersect_ceilings([a, b])
    backward = intersect_ceilings([b, a])
    assert forward.revision_digest == backward.revision_digest
    assert len(forward.entries_denied) == len(backward.entries_denied) == 2


def test_an_unverified_member_poisons_the_intersection() -> None:
    trusted_ceiling = PolicyCeiling.from_record(trusted())
    effective = intersect_ceilings([trusted_ceiling, PolicyCeiling.unverified("x")])
    assert not effective.is_trusted


def test_intersecting_nothing_is_a_missing_provider_not_an_open_field() -> None:
    with pytest.raises(PolicyRefusal) as exc:
        intersect_ceilings([])
    assert exc.value.code == "POLICY_ADAPTER_MISSING"


def test_a_ceiling_itsown_revision_digest_is_stable_and_bound_to_id_and_revision() -> None:
    ceiling = PolicyCeiling.from_record(trusted())
    assert ceiling.revision_digest == PolicyCeiling.from_record(trusted()).revision_digest
    assert ceiling.revision_digest != PolicyCeiling.from_record(trusted(revision=4)).revision_digest

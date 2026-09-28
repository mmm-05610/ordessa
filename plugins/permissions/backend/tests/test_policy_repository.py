"""T02 (FR-01, FR-10): ceilings and intents live in SEPARATE stores, and a
ceiling is only writable from a trusted-source provenance.

A ceiling record arriving through the ordinary profile/settings path (no
signature, no trusted source) is refused; an intent record has no ceiling
vocabulary at all. Revision history is kept so a mid-flight tightening is
detectable by digest.
"""
from __future__ import annotations

import pytest
from ordessa_permissions_api import (PermissionIntent, PolicyCeiling, PolicyRefusal,
                                     RefusalCode)
from support import admin_ceiling, seeded_database

from ordessa_permissions_backend import PolicyRepository


@pytest.fixture
def repository(tmp_path):
    database = seeded_database(tmp_path)
    store = PolicyRepository(database)
    store.ensure_schema()
    return store


def test_trusted_ceiling_round_trips_by_id_and_revision(repository):
    repository.store_ceiling(admin_ceiling(revision=1))
    current = repository.ceilings_current()
    assert [c.revision_digest for c in current] == ["admin@1"]
    fetched = repository.ceiling("admin", 1)
    assert isinstance(fetched, PolicyCeiling)
    assert fetched.signed and fetched.is_trusted


def test_unsigned_ceiling_from_the_settings_path_is_refused(repository):
    raw = {"policyId": "from-settings", "scope": "user", "revision": 1,
           "maximumExposure": "full", "effectiveFrom": "2020-01-01T00:00:00+00:00"}
    with pytest.raises(PolicyRefusal) as caught:
        PolicyCeiling.from_record(raw)  # the DTO itself refuses...
    assert caught.value.refusal_code is RefusalCode.POLICY_SCOPE_UNVERIFIED
    with pytest.raises(PolicyRefusal):
        repository.store_ceiling_record({**raw, "source": "unverified", "signed": True})
    assert repository.ceilings_current() == ()  # nothing leaked in


def test_even_signed_a_session_scope_record_cannot_become_a_ceiling(repository):
    """Scope rank is provenance: a session/profile-shaped record is refused
    even if it carries a signature - FR-01: low layers cannot raise ceilings."""
    raw = {"policyId": "sneaky", "scope": "session", "revision": 1,
           "source": "signed-admin", "signed": True, "maximumExposure": "full",
           "effectiveFrom": "2020-01-01T00:00:00+00:00"}
    with pytest.raises(PolicyRefusal):
        PolicyCeiling.from_record(raw)
    with pytest.raises(PolicyRefusal):
        repository.store_ceiling_record(raw)


def test_intent_stores_by_id_and_revision_in_its_own_store(repository):
    intent = PermissionIntent.from_record({
        "intentId": "profile-intent", "revision": 1, "harnessId": "pi",
        "scope": "project",
        "rules": [{"key": "read", "action": "allow"}],
    })
    repository.store_intent(intent)
    stored = repository.intent_current("profile-intent")
    assert stored.revision_digest == "profile-intent@1"


def test_an_intent_cannot_carry_ceiling_vocabulary(repository):
    smuggled = {
        "intentId": "smuggled", "revision": 1, "harnessId": "pi", "scope": "project",
        "rules": [], "deny": [{"key": "read"}], "maximumExposure": "full",
        "signed": True, "source": "signed-admin",
    }
    with pytest.raises(PolicyRefusal):
        repository.store_intent_record(smuggled)
    assert repository.intent_current("smuggled") is None


def test_ceiling_history_detects_a_mid_flight_tightening(repository):
    repository.store_ceiling(admin_ceiling(revision=1))
    tightened = PolicyCeiling.from_record({
        "policyId": "admin", "scope": "admin", "revision": 2, "source": "signed-admin",
        "signed": True, "maximumExposure": "read",
        "effectiveFrom": "2020-01-01T00:00:00+00:00",
    })
    repository.store_ceiling(tightened)
    history = repository.ceiling_history("admin")
    assert [c.revision for c in history] == [1, 2]
    assert [c.maximum_exposure.value for c in history] == ["full", "read"]
    assert repository.ceilings_current()[0].revision_digest == "admin@2"


def test_backwards_ceiling_revision_is_refused(repository):
    repository.store_ceiling(admin_ceiling(revision=3))
    with pytest.raises(PolicyRefusal):
        repository.store_ceiling(admin_ceiling(revision=2))
    assert repository.ceilings_current()[0].revision == 3


def test_stores_are_separate_tables(repository, ):
    """The ceiling store never reads or writes the intent rows (FR-01 split)."""
    repository.store_ceiling(admin_ceiling())
    assert repository.ceilings_current()
    tables = repository.store_tables()
    assert tables["ceilings"] != tables["intents"]
    with repository.database.read() as conn:  # direct proof per table
        intent_rows = conn.execute(
            "SELECT COUNT(*) FROM permissions_policy_intents").fetchone()[0]
    assert intent_rows == 0

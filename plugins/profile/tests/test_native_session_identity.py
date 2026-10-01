"""Canonical storage addresses must not be confused with native routing IDs."""
import pytest
from profile_harness_doubles import make_core
from ordessa_profile import ProfileError


def test_distinct_canonical_sessions_can_share_a_native_routing_id(tmp_path):
    core = make_core(tmp_path)
    profile = core.profiles.create("create", harness_id="pi", display_name="Review")
    for uid in ("canonical-a", "canonical-b"):
        core.sessions.open_session(uid, session_id=uid, session_uid=uid,
            native_session_key="same-native-id", harness_id="pi", profile_id=profile["profile_id"])
    with core.db.transaction() as conn:
        rows = conn.execute("SELECT session_uid,native_session_key FROM profile_sessions ORDER BY session_uid").fetchall()
        assert [(row[0], row[1]) for row in rows] == [
            ("canonical-a", "same-native-id"), ("canonical-b", "same-native-id")]


def test_a_new_uid_cannot_overwrite_an_existing_storage_address(tmp_path):
    core = make_core(tmp_path)
    profile = core.profiles.create("create", harness_id="pi", display_name="Review")
    core.sessions.open_session("first", session_id="storage", session_uid="canonical-a",
        harness_id="pi", profile_id=profile["profile_id"])
    with pytest.raises(ProfileError):
        core.sessions.open_session("second", session_id="storage", session_uid="canonical-b",
            harness_id="pi", profile_id=profile["profile_id"])
    with core.db.transaction() as conn:
        assert conn.execute("SELECT session_uid FROM profile_sessions").fetchone()[0] == "canonical-a"


def test_native_identity_is_part_of_registration_idempotency(tmp_path):
    core = make_core(tmp_path)
    profile = core.profiles.create("create", harness_id="pi", display_name="Review")
    args = dict(session_id="canonical", session_uid="canonical", harness_id="pi",
                profile_id=profile["profile_id"], native_session_key="native-a")
    first = core.sessions.open_session("register", **args)
    assert core.sessions.open_session("register", **args) == first
    with pytest.raises(ProfileError):
        core.sessions.open_session("register", **{**args, "native_session_key": "native-b"})

"""T04/T05 — US1 basic Profile management + absent-plugin comparison (G1).

FR-001 stable identity / immutable harness binding.
FR-002 expected-version commits, explicit conflicts, idempotent replays.
FR-003 base capability with zero facet providers (absence comparison).
US1.1-1.4 acceptance scenarios; SC-001.
"""
from __future__ import annotations

import re

import pytest

from ordessa_profile import ProfileError
from ordessa_profile.facets import FacetRegistry
PROFILE_ID = re.compile(r"^profile_[0-9a-f]{32}$")


def test_us1_1_create_records_stable_identity(core):
    view = core.profiles.create("k1", harness_id="pi", display_name="Daily")
    assert PROFILE_ID.match(view["profile_id"])
    assert view["harness_id"] == "pi"
    assert view["version"] == 1
    assert view["current_revision"] == 1
    assert view["archived_at"] is None
    # harness binding is immutable: no mutation path touches it
    renamed = core.profiles.rename(
        "k2", profile_id=view["profile_id"], expected_version=1,
        display_name="Renamed")
    assert renamed["harness_id"] == "pi"
    row = core.profiles.get(view["profile_id"])
    assert row["harness_id"] == "pi" and row["display_name"] == "Renamed"


def test_create_refuses_unknown_harness(core):
    with pytest.raises(ProfileError) as exc:
        core.profiles.create("k1", harness_id="ghost", display_name="X")
    assert exc.value.code == "HARNESS_UNKNOWN" and exc.value.status == 404


def test_us1_2_stale_version_commit_rejected(core):
    view = core.profiles.create("k1", harness_id="pi", display_name="A")
    pid = view["profile_id"]
    first = core.profiles.rename(
        "w1", profile_id=pid, expected_version=1, display_name="Newer")
    assert first["version"] == 2
    with pytest.raises(ProfileError) as exc:
        core.profiles.rename(
            "w2", profile_id=pid, expected_version=1, display_name="Stale")
    assert exc.value.code == "PROFILE_VERSION_CONFLICT"
    assert exc.value.current["display_name"] == "Newer"
    assert core.profiles.get(pid)["display_name"] == "Newer"


def test_fr002_repeated_request_does_not_double_mutate(core):
    view = core.profiles.create("same-key", harness_id="pi", display_name="A")
    pid = view["profile_id"]
    again = core.profiles.create("same-key", harness_id="pi", display_name="A")
    assert again["profile_id"] == pid
    assert len(core.profiles.list(include_archived=True)) == 1
    r1 = core.profiles.rename(
        "rk", profile_id=pid, expected_version=1, display_name="R")
    r2 = core.profiles.rename(
        "rk", profile_id=pid, expected_version=1, display_name="R")
    assert r1["version"] == r2["version"] == 2
    with pytest.raises(ProfileError) as exc:
        core.profiles.rename(
            "rk", profile_id=pid, expected_version=1, display_name="Different")
    assert exc.value.code == "IDEMPOTENCY_KEY_REUSED"


def test_us1_3_archived_profile_cannot_be_selected(core):
    a = core.profiles.create("ka", harness_id="pi", display_name="A")
    b = core.profiles.create("kb", harness_id="pi", display_name="B")
    session = core.sessions.open_session(
        "ks", session_id="s1", harness_id="pi", profile_id=a["profile_id"])
    assert session["switch_state"] == "settled"
    core.profiles.archive("kar", profile_id=b["profile_id"], expected_version=1)
    with pytest.raises(ProfileError) as exc:
        core.sessions.select_profile(
            "ksel", session_id="s1", profile_id=b["profile_id"])
    assert exc.value.code == "PROFILE_ARCHIVED"
    # history remains viewable
    assert core.profiles.get(b["profile_id"])["archived_at"] is not None
    assert core.profiles.list(include_archived=False) == [
        core.profiles.get(a["profile_id"])]
    assert len(core.profiles.list(include_archived=True)) == 2


def test_archive_is_idempotent_and_versioned(core):
    view = core.profiles.create("k1", harness_id="pi", display_name="A")
    pid = view["profile_id"]
    once = core.profiles.archive("ak", profile_id=pid, expected_version=1)
    twice = core.profiles.archive("ak2", profile_id=pid, expected_version=2)
    assert once["archived_at"] == twice["archived_at"]


def test_facet_edits_refused_on_archived(core):
    view = core.profiles.create("k1", harness_id="pi", display_name="A")
    core.profiles.archive("ak", profile_id=view["profile_id"], expected_version=1)
    with pytest.raises(ProfileError) as exc:
        core.profiles.set_facet_values(
            "fk", profile_id=view["profile_id"], expected_version=2, values=[])
    assert exc.value.code == "PROFILE_ARCHIVED"


# --- FR-003 / US1.4: absent-plugin comparison (zero facet providers) -----

def test_fr003_base_management_without_any_facet_plugin(tmp_path):
    from conftest import make_core
    core = make_core(tmp_path)  # no providers registered at all
    created = core.profiles.create("k1", harness_id="codex", display_name="Bare")
    # no facet can be written while its provider is absent
    with pytest.raises(ProfileError) as exc:
        core.profiles.set_facet_values(
            "k4", profile_id=created["profile_id"], expected_version=1,
            values=[{"facet_id": "model", "item_id": "model", "value": "m1"}])
    assert exc.value.code == "FACET_UNKNOWN"
    listed = core.profiles.list(include_archived=False)
    renamed = core.profiles.rename(
        "k2", profile_id=created["profile_id"], expected_version=1,
        display_name="Bare2")
    archived = core.profiles.archive(
        "k3", profile_id=created["profile_id"], expected_version=2)
    assert created["profile_id"] and listed and renamed and archived
    # settings show no empty model/skill/permission sections
    projection = core.profiles.settings_projection(created["profile_id"])
    assert projection["facets"] == []


def test_registry_rejects_malformed_provider(core):
    registry = FacetRegistry()
    with pytest.raises(ProfileError):
        registry.register(object())

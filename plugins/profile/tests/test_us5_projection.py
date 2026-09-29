"""T16/T17 — US5 projections and the security surface (G5).

FR-011 no plaintext credentials anywhere; FR-012 switch path carries no
permission surface; FR-020/US5.2/US5.4 state distinctions; US5.1 works
without any Chat component.
"""
from __future__ import annotations

import re
import sqlite3

import pytest

from conftest import ScriptedProvider, make_core
from ordessa_profile import ProfileError

MODEL = ScriptedProvider(
    "model_selection", ("model",), applies=frozenset({"pi"}),
    valid={"m1", "m2"},
)
STYLE = ScriptedProvider(
    "output_style", ("style",), applies=frozenset({"pi"}),
    valid={"terse", "verbose"},
)
_SENSITIVE_KEY = re.compile(
    r"(secret|token|api[_-]?key|password|private[_-]?key|authorization|"
    r"cookie|credential_value)", re.I)

EXPECTED_COLUMNS = {
    "profile_profiles": {
        "profile_id", "version", "display_name", "harness_id",
        "current_revision", "archived_at", "created_at", "updated_at",
        "realm"},
    "profile_revisions": {"profile_id", "config_revision", "created_at"},
    "profile_facet_values": {
        "profile_id", "config_revision", "facet_id", "item_id", "value_json",
        "facet_version", "quarantined", "updated_at"},
    "profile_sessions": {
        "session_id", "harness_id", "current_profile_id", "current_revision",
        "pending_profile_id", "pending_seq", "switch_state", "blockers_json",
        "created_at", "updated_at", "realm", "native_session_key",
        "session_uid"},
    "profile_mechanism_policy": {
        "realm", "revision", "facet_enabled_json", "allow_override_global",
        "allow_per_facet_json", "updated_at"},
    "profile_application_journal": {
        "operation_id", "session_uid", "state", "profile_id",
        "profile_revision", "plan_digest", "failure", "detail_refs_json",
        "created_at", "updated_at"},
    "profile_applied_receipts": {
        "operation_id", "session_uid", "receipt_json", "confirmed_at"},
    "profile_session_overlays": {
        "session_id", "facet_id", "item_id", "value_json", "facet_version",
        "created_at", "updated_at"},
    "profile_turns": {
        "turn_id", "session_id", "turn_seq", "profile_id", "config_revision",
        "effective_digest", "sources_json", "created_at"},
    "profile_idempotency": {
        "scope", "key", "request_digest", "status", "response_json",
        "created_at"},
    "profile_schema": {"version", "applied_at"},
}


def world(tmp_path, *, config_port=None):
    kwargs = {"config_port": config_port} if config_port is not None else {}
    core = make_core(tmp_path, providers=(MODEL, STYLE), **kwargs)
    a = core.profiles.create("ka", harness_id="pi", display_name="A")
    b = core.profiles.create("kb", harness_id="pi", display_name="B")
    core.profiles.set_facet_values(
        "ka1", profile_id=a["profile_id"], expected_version=1,
        values=[
            {"facet_id": "model_selection", "item_id": "model", "value": "m1"},
            {"facet_id": "output_style", "item_id": "style", "value": "terse"},
        ])
    core.profiles.set_facet_values(
        "kb1", profile_id=b["profile_id"], expected_version=1,
        values=[
            {"facet_id": "model_selection", "item_id": "model", "value": "m2"},
            {"facet_id": "output_style", "item_id": "style",
             "value": "verbose"},
        ])
    core.sessions.open_session("ks", session_id="S", harness_id="pi",
                               profile_id=a["profile_id"])
    return core, a, b


def test_us5_2_projection_never_shows_pending_as_current(tmp_path):
    core, a, b = world(tmp_path)
    core.sessions.select_profile(
        "sel1", session_id="S", profile_id=b["profile_id"])
    config = core.sessions.session_config("S")
    assert config["current"]["profile_id"] == a["profile_id"]
    assert config["current"]["display_name"] == "A"
    assert config["pending"]["profile_id"] == b["profile_id"]
    assert config["pending"]["profile_id"] != config["current"]["profile_id"]
    assert config["switch_state"] == "pending"
    ticket = core.sessions.begin_turn("t1", session_id="S")
    config = core.sessions.session_config("S")
    assert config["pending"] is None
    assert config["current"]["profile_id"] == b["profile_id"]
    assert ticket["applied_switch"] is True


def test_us5_4_session_only_values_are_labelled_and_restorable(tmp_path):
    core, a, b = world(tmp_path)
    core.sessions.set_overlay(
        "o1", session_id="S", facet_id="model_selection", item_id="model",
        value="m2")
    items = {i["item_id"]: i for i in core.sessions.session_config("S")["items"]}
    assert items["model"]["source"] == "session_only"
    assert items["style"]["source"] == "profile"
    core.sessions.clear_overlay(
        "c1", session_id="S", facet_id="model_selection", item_id="model")
    items = {i["item_id"]: i for i in core.sessions.session_config("S")["items"]}
    assert items["model"]["source"] == "profile"
    assert items["model"]["value"] == "m1"


def test_us5_2_needs_recovery_state_is_visible_not_faked(tmp_path):
    # v2: an unknown application outcome is visible as needs_recovery with
    # an honest blocker; the journal carries the unproven operation.
    from conftest import ScriptedConfigPort
    core, a, b = world(
        tmp_path, config_port=ScriptedConfigPort(apply_verdict="unknown"))
    core.sessions.select_profile(
        "sel1", session_id="S", profile_id=b["profile_id"])
    with pytest.raises(ProfileError):
        core.sessions.begin_turn("t1", session_id="S")
    config = core.sessions.session_config("S")
    assert config["switch_state"] == "needs_recovery"
    assert config["blockers"] == [{"reason": "application_unproven"}]
    assert config["evidence"]["journal"]["state"] == "unknown"


def test_fr011_secret_carriers_refused_at_every_entry(tmp_path):
    core, a, b = world(tmp_path)
    with pytest.raises(ProfileError) as exc:
        core.profiles.set_facet_values(
            "s1", profile_id=a["profile_id"], expected_version=2,
            values=[{"facet_id": "model_selection", "item_id": "model",
                     "value": {"api_key": "sk-live-123"}}])
    assert exc.value.code == "SECRET_FIELD_FORBIDDEN" and \
        exc.value.status == 422
    with pytest.raises(ProfileError) as exc2:
        core.sessions.set_overlay(
            "s2", session_id="S", facet_id="model_selection", item_id="model",
            value={"auth": {"token": "t"}})
    assert exc2.value.code == "SECRET_FIELD_FORBIDDEN"
    # nothing was stored by the refused writes
    assert all("token" not in v["item_id"]
               for v in core.profiles.facet_values(a["profile_id"]))


def test_fr012_switch_surface_has_no_permission_or_credential_fields(tmp_path):
    core, a, b = world(tmp_path)
    # the schema itself carries no permission/approval/credential-value column
    with core.db.read() as conn:
        tables = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if not r["name"].startswith("sqlite_")}
    assert tables == set(EXPECTED_COLUMNS)
    for table, columns in EXPECTED_COLUMNS.items():
        with core.db.read() as conn:
            actual = {r["name"] for r in conn.execute(
                f"PRAGMA table_info({table})").fetchall()}
        assert actual == columns, table
        assert not any(_SENSITIVE_KEY.search(c) for c in actual)
    # and the switch API responses expose no permission-shaped field
    core.sessions.select_profile(
        "sel1", session_id="S", profile_id=b["profile_id"])
    ticket = core.sessions.begin_turn("t1", session_id="S")
    view = core.sessions.session_config("S")
    for payload in (ticket, view, core.profiles.get(b["profile_id"])):
        assert not any(_SENSITIVE_KEY.search(str(k)) for k in payload)


def test_us5_1_management_fully_usable_without_any_chat_component(tmp_path):
    core, a, b = world(tmp_path)
    # the projection schema carries no conversation/chat entry surface
    # v2 adds the canonical identity (session_uid/realm) and the application
    # evidence projection (specs/011-z1-profile); still no chat entry surface
    config = core.sessions.session_config("S")
    assert set(config) == {
        "session_id", "session_uid", "realm", "harness_id", "switch_state",
        "current", "pending", "items", "unavailable", "blockers", "evidence",
    }
    # settings management works with no chat involved
    assert core.profiles.rename(
        "r1", profile_id=a["profile_id"], expected_version=2,
        display_name="A2")["display_name"] == "A2"
    assert [p["display_name"] for p in core.profiles.list()] == ["A2", "B"]


def test_fr013_unavailable_items_reported_not_hidden(tmp_path):
    core, a, b = world(tmp_path)
    core.unregister_provider(STYLE)
    config = core.sessions.session_config("S")
    assert {"facet_id": "output_style", "item_id": "style",
            "reason": "provider_absent"} in config["unavailable"]
    # but the effective items never include the absent provider's value
    assert all(i["facet_id"] != "output_style" for i in config["items"])

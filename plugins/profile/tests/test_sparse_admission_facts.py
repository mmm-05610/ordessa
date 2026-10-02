"""Sparse-recovery counterexamples: the frozen admission facts are the fence.

Companion to ``test_sparse_profile_precedence.py`` (the user-ruling set).  Where
that file proves *which items* a Profile may touch, this file proves that a
single operation only ever consumes, clears or settles what it froze at
admission time:

- P06 — a retained effective base is not a user overlay: a later global
  Profile edit reaches the items it covers and never the item the user
  changed.
- P07 — a Profile edit or overlay write made *after* an unproven operation
  started is neither consumed nor clobbered by its reconcile.
- P08 — a newer pick made while an operation was in flight is never
  overwritten by that operation's commit, on any outcome.
- P09 — a same-value overlay rewrite during apply still bumps the overlay
  revision, so the older apply cannot clear it.
- P10 — repeating an operation with the same key has zero new effect.
- C04 — an existing v2 store migrates forward with zero record loss and the
  restarted process can still recover and reconcile.

Controlled port evidence only (``ScriptedConfigPort``); no real model call.
"""
import sqlite3

import pytest

from ordessa_profile.errors import ProfileError
from ordessa_profile.storage import ProfileDatabase
from profile_harness_doubles import ScriptedConfigPort, ScriptedProvider, make_core


def world(tmp_path, *, apply_verdict="confirmed", open_profile="base"):
    port = ScriptedConfigPort()
    port.native_turn_application = True
    core = make_core(tmp_path, config_port=port, providers=(
        ScriptedProvider("model", ("choice",), valid={"a", "b", "override"}),
        ScriptedProvider("style", ("choice", "detail"), valid={"terse", "verbose"}),
    ))
    profiles = {}
    for name, values in (
        ("base", [("model", "choice", "a"), ("style", "choice", "terse"),
                  ("style", "detail", "terse")]),
        ("model-only", [("model", "choice", "b")]),
        ("style-only", [("style", "choice", "verbose")]),
    ):
        created = core.profiles.create(f"create:{name}", harness_id="pi",
                                       display_name=name)
        profiles[name] = core.profiles.set_facet_values(
            f"values:{name}", profile_id=created["profile_id"],
            expected_version=1,
            values=[{"facet_id": f, "item_id": i, "value": v}
                    for f, i, v in values])
    core.sessions.open_session("open", session_id="s", harness_id="pi",
                               profile_id=profiles[open_profile]["profile_id"])
    # the opening turn is always a proven one; only the operation under test
    # may be scripted unproven
    core.sessions.begin_turn("first", session_id="s")
    port.apply_verdict = apply_verdict
    return core, profiles, port


def store_path(tmp_path):
    return tmp_path / "profile-store.sqlite"


def items(core):
    return {(i["facet_id"], i["item_id"]): (i["value"], i["source"])
            for i in core.sessions.session_config("s")["items"]}


def overlays(core):
    from ordessa_profile import repository as repo
    with core.db.read() as conn:
        return {(r["facet_id"], r["item_id"]):
                (r["value_json"], int(r["revision"]), int(r["action_seq"]))
                for r in repo.session_overlays(conn, "s")}


def pick(core, profiles, name, key="pick"):
    core.sessions.select_profile(key, session_id="s",
                                 profile_id=profiles[name]["profile_id"])


# --------------------------------------------------------------------- P06
def test_global_edit_reaches_uncovered_items_but_never_a_user_overlay(tmp_path):
    """P06: the retained effective base and a user overlay are different
    things.  A global Profile edit applies to the items it covers and leaves
    the user's own item alone."""
    core, profiles, port = world(tmp_path)
    try:
        core.sessions.set_overlay("overlay", session_id="s", facet_id="model",
                                  item_id="choice", value="override")
        assert items(core)[("model", "choice")] == ("override", "session_only")
        profile = profiles["base"]
        core.profiles.set_facet_values(
            "global-edit", profile_id=profile["profile_id"],
            expected_version=profile["version"],
            values=[{"facet_id": "style", "item_id": "choice",
                     "value": "verbose"}])
        core.sessions.begin_turn("ordinary", session_id="s")
        effective = items(core)
        # the global update takes effect for the items it covers
        assert effective[("style", "choice")] == ("verbose", "profile")
        # and the user's own item is not overwritten
        assert effective[("model", "choice")] == ("override", "session_only")
        applied = {(i.facet_id, i.item_id): i.value for i in port.applied[-1]}
        assert applied[("style", "choice")] == "verbose"
        assert applied[("model", "choice")] == "override"
    finally:
        core.db.close()


def test_retained_base_is_labelled_and_never_read_from_the_newest_revision(
        tmp_path):
    """P06: an omitted item's effective value comes from the last confirmed
    effective configuration, not from the newest Profile revision."""
    core, profiles, port = world(tmp_path)
    try:
        pick(core, profiles, "model-only")
        core.sessions.begin_turn("switch", session_id="s")
        assert items(core)[("style", "detail")] == ("terse", "retained_base")
        settled = core.sessions.turns("s")[-1]
        # the recorded turn keeps the retained base, labelled as such
        assert {(i["facet_id"], i["item_id"]): (i["value"], i["source"])
                for i in settled["effective"]}[("style", "detail")] == \
            ("terse", "retained_base")
        # A later global edit of the bound Profile must not rewrite the
        # retained base this session already confirmed: it decides the *next*
        # projection, never the past turn.
        core.profiles.set_facet_values(
            "late-global", profile_id=profiles["model-only"]["profile_id"],
            expected_version=core.profiles.get(
                profiles["model-only"]["profile_id"])["version"],
            values=[{"facet_id": "style", "item_id": "detail",
                     "value": "verbose"}])
        assert {(i["facet_id"], i["item_id"]): (i["value"], i["source"])
                for i in core.sessions.turns("s")[-1]["effective"]
                }[("style", "detail")] == ("terse", "retained_base")
    finally:
        core.db.close()


# --------------------------------------------------------------------- P07
def test_reconcile_neither_consumes_nor_clobbers_a_later_overlay(tmp_path):
    """P07: an overlay written after the unproven operation started is not
    part of what that operation proved, so its reconcile consumes nothing."""
    core, profiles, port = world(tmp_path, apply_verdict="unknown")
    try:
        pick(core, profiles, "model-only")
        with pytest.raises(ProfileError):
            core.sessions.begin_turn("unknown", session_id="s")
        assert overlays(core) == {}
        # written while the operation is unproven
        core.sessions.set_overlay("late-overlay", session_id="s",
                                  facet_id="model", item_id="choice",
                                  value="override")
        before = overlays(core)
        core.sessions.reconcile("reconcile", session_id="s")
        assert overlays(core) == before
        assert items(core)[("model", "choice")] == ("override", "session_only")
    finally:
        core.db.close()


def test_reconcile_uses_the_admitted_mask_not_the_profile_it_is_facing_now(
        tmp_path):
    """P07: a Profile edit after admission is not what the operation proved;
    the frozen mask alone may drive consumption."""
    core, profiles, port = world(tmp_path, apply_verdict="unknown")
    try:
        core.sessions.set_overlay("overlay", session_id="s", facet_id="model",
                                  item_id="choice", value="override")
        pick(core, profiles, "style-only")
        with pytest.raises(ProfileError):
            core.sessions.begin_turn("unknown", session_id="s")
        # the Profile gains an item the frozen admission never declared
        target = profiles["style-only"]
        core.profiles.set_facet_values(
            "late-global", profile_id=target["profile_id"],
            expected_version=core.profiles.get(target["profile_id"])["version"],
            values=[{"facet_id": "model", "item_id": "choice",
                     "value": "override"}])
        core.sessions.set_overlay("late-overlay", session_id="s",
                                  facet_id="style", item_id="choice",
                                  value="verbose")
        before = overlays(core)
        core.sessions.reconcile("reconcile", session_id="s")
        # the late overlay is outside the frozen mask: kept, not consumed
        assert ("style", "choice") in overlays(core)
        assert overlays(core)[("style", "choice")] == \
            before[("style", "choice")]
    finally:
        core.db.close()


# --------------------------------------------------------------------- P08
@pytest.mark.parametrize("verdict", ["rejected", "unknown", "commit-failed"])
def test_a_newer_pick_during_a_failed_operation_is_never_overwritten(
        tmp_path, verdict):
    """P08: on every non-success outcome the row is re-read, and a pick made
    while the operation ran keeps its own pending state."""
    core, profiles, port = world(tmp_path)
    original = port.apply

    def apply_then_pick(plan, desired):
        result = original(plan, desired)
        pick(core, profiles, "style-only", "late-pick")
        return result

    try:
        pick(core, profiles, "model-only", "first-pick")
        if verdict == "commit-failed":
            def fail_commit(_operation):
                raise RuntimeError("controlled-commit-failure")
            core.commit_injection = fail_commit
        else:
            port.apply_verdict = verdict
        port.apply = apply_then_pick
        with pytest.raises(ProfileError):
            core.sessions.begin_turn("apply", session_id="s")
        config = core.sessions.session_config("s")
        assert config["pending"]["profile_id"] == \
            profiles["style-only"]["profile_id"]
        assert config["current"]["profile_id"] == \
            profiles["base"]["profile_id"]
    finally:
        core.db.close()


def test_recovery_state_never_rewrites_the_binding_or_the_pending_choice(
        tmp_path):
    """P08/G10: ``needs_recovery`` writes only the safety state."""
    core, profiles, port = world(tmp_path, apply_verdict="unknown")
    try:
        core.sessions.set_overlay("overlay", session_id="s", facet_id="model",
                                  item_id="choice", value="override")
        pick(core, profiles, "model-only")
        before = core.sessions.session_config("s")
        assert before["pending"] is not None
        with pytest.raises(ProfileError):
            core.sessions.begin_turn("unknown", session_id="s")
        after = core.sessions.session_config("s")
        assert after["switch_state"] == "needs_recovery"
        assert after["current"] == before["current"]
        assert after["pending"] == before["pending"]
        assert after["items"] == before["items"]
    finally:
        core.db.close()


# --------------------------------------------------------------------- P09
def test_same_value_rewrite_during_apply_is_not_cleared_by_the_older_apply(
        tmp_path):
    """P09: a rewrite of the *same* value still counts as a new write.  The
    overlay revision therefore no longer matches the admission snapshot, and
    the older apply must not clear it."""
    core, profiles, port = world(tmp_path)
    original = port.apply

    def apply_then_rewrite(plan, desired):
        result = original(plan, desired)
        core.sessions.set_overlay("rewrite", session_id="s", facet_id="model",
                                  item_id="choice", value="override")
        return result

    try:
        core.sessions.set_overlay("overlay", session_id="s", facet_id="model",
                                  item_id="choice", value="override")
        assert overlays(core)[("model", "choice")][0] == '"override"'
        first_revision = overlays(core)[("model", "choice")][1]
        pick(core, profiles, "model-only")
        port.apply = apply_then_rewrite
        core.sessions.begin_turn("apply", session_id="s")
        assert overlays(core)[("model", "choice")][0] == '"override"'
        # the same-value rewrite bumped the revision past the snapshot
        assert overlays(core)[("model", "choice")][1] > first_revision
        assert items(core)[("model", "choice")] == ("override", "session_only")
        assert not any(i.op == "reset" for i in port.applied[-1])
    finally:
        core.db.close()


def test_an_older_apply_cannot_clear_a_same_value_rewrite_under_reconcile(
        tmp_path):
    """P09, reconcile side: the consume is a compare-and-set on the frozen
    revision, so the reconcile cannot clear a same-value rewrite either."""
    core, profiles, port = world(tmp_path, apply_verdict="unknown")
    original = port.apply

    def apply_then_rewrite(plan, desired):
        result = original(plan, desired)
        core.sessions.set_overlay("rewrite", session_id="s", facet_id="model",
                                  item_id="choice", value="override")
        return result

    try:
        core.sessions.set_overlay("overlay", session_id="s", facet_id="model",
                                  item_id="choice", value="override")
        pick(core, profiles, "model-only")
        port.apply = apply_then_rewrite
        with pytest.raises(ProfileError):
            core.sessions.begin_turn("apply", session_id="s")
        before = overlays(core)
        core.sessions.reconcile("reconcile", session_id="s")
        assert overlays(core) == before
    finally:
        core.db.close()


# --------------------------------------------------------------------- P10
def test_repeating_a_turn_operation_has_zero_new_effect(tmp_path):
    """P10: the same operation key replays its recorded result."""
    core, profiles, port = world(tmp_path)
    try:
        pick(core, profiles, "model-only")
        first = core.sessions.begin_turn("apply", session_id="s")
        applies, turns = port.counters["apply"], len(core.sessions.turns("s"))
        second = core.sessions.begin_turn("apply", session_id="s")
        assert second == first
        assert port.counters["apply"] == applies
        assert len(core.sessions.turns("s")) == turns
    finally:
        core.db.close()


def test_repeating_a_reconcile_has_zero_new_effect(tmp_path):
    """P10: reconcile is idempotent under its own key, not by re-running."""
    core, profiles, port = world(tmp_path, apply_verdict="unknown")
    try:
        pick(core, profiles, "model-only")
        with pytest.raises(ProfileError):
            core.sessions.begin_turn("apply", session_id="s")
        first = core.sessions.reconcile("reconcile", session_id="s")
        calls, turns = port.counters["reconcile"], len(core.sessions.turns("s"))
        second = core.sessions.reconcile("reconcile", session_id="s")
        assert second == first
        assert port.counters["reconcile"] == calls
        assert len(core.sessions.turns("s")) == turns
    finally:
        core.db.close()


def test_repeating_recovery_leaves_the_session_blocked_until_reconciled(
        tmp_path):
    """P10: a repeated unproven operation never turns into a second try at
        the native application."""
    core, profiles, port = world(tmp_path, apply_verdict="unknown")
    try:
        pick(core, profiles, "model-only")
        baseline = port.counters["apply"]
        for key in ("apply-1", "apply-2"):
            with pytest.raises(ProfileError):
                core.sessions.begin_turn(key, session_id="s")
        # only the first unproven operation ever reached the native side
        assert port.counters["apply"] == baseline + 1
        assert core.sessions.session_config("s")["switch_state"] == \
            "needs_recovery"
        # the second key is refused before the port is touched at all
        with pytest.raises(ProfileError):
            core.sessions.begin_turn("apply-3", session_id="s")
        assert port.counters["apply"] == baseline + 1
    finally:
        core.db.close()


# --------------------------------------------------------------------- C04
def _downgrade_to_v2(path):
    """Turn a current store back into a genuine v2 store, records intact."""
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("DELETE FROM profile_schema WHERE version=3")
        conn.execute("ALTER TABLE profile_session_overlays DROP COLUMN action_seq")
        conn.execute("ALTER TABLE profile_session_overlays DROP COLUMN revision")
        conn.execute("ALTER TABLE profile_sessions DROP COLUMN action_seq")
        conn.execute("ALTER TABLE profile_sessions DROP COLUMN admission_facts_json")
        conn.commit()
    finally:
        conn.close()


def _counts(path):
    db = ProfileDatabase(path)
    try:
        with db.read() as conn:
            return {
                table: conn.execute(f"SELECT COUNT(*) AS n FROM {table}"
                                     ).fetchone()["n"]
                for table in ("profile_sessions", "profile_session_overlays",
                              "profile_turns", "profile_application_journal",
                              "profile_applied_receipts")
            }
    finally:
        db.close()


def test_v2_store_migrates_forward_without_losing_a_record(tmp_path):
    """C04: the forward migration is additive — every row of the v2 store is
    still there afterwards, with honest defaults on the new columns."""
    core, profiles, port = world(tmp_path)
    path = store_path(tmp_path)
    try:
        core.sessions.set_overlay("overlay", session_id="s", facet_id="model",
                                  item_id="choice", value="override")
        core.db.close()
        _downgrade_to_v2(path)
        before = _counts(path)

        db = ProfileDatabase(path)
        try:
            with db.read() as conn:
                versions = [int(r["version"]) for r in conn.execute(
                    "SELECT version FROM profile_schema ORDER BY version")]
                session = conn.execute(
                    "SELECT * FROM profile_sessions WHERE session_id='s'"
                ).fetchone()
                overlay = conn.execute(
                    "SELECT * FROM profile_session_overlays").fetchone()
            assert versions == [1, 2, 3]
            assert _counts(path) == before
            # honest defaults: the pre-v3 counter was the pending sequence,
            # and a pre-existing overlay row counts as written once
            assert session["action_seq"] == 0
            assert session["admission_facts_json"] is None
            assert overlay["revision"] == 1
        finally:
            db.close()
    finally:
        core.db.close()


def test_restart_after_v2_migration_recovers_and_reconciles(tmp_path):
    """C04: a restarted process over a migrated v2 store still holds the
    unproven operation, and reconciling it reaches a settled session."""
    core, profiles, port = world(tmp_path, apply_verdict="unknown")
    path = store_path(tmp_path)
    try:
        core.sessions.set_overlay("overlay", session_id="s", facet_id="model",
                                  item_id="choice", value="override")
        pick(core, profiles, "model-only")
        with pytest.raises(ProfileError):
            core.sessions.begin_turn("unproven", session_id="s")
        core.db.close()
        _downgrade_to_v2(path)

        restarted_port = ScriptedConfigPort()
        restarted_port.native_turn_application = True
        restarted = make_core(
            tmp_path, config_port=restarted_port, providers=(
                ScriptedProvider("model", ("choice",),
                                 valid={"a", "b", "override"}),
                ScriptedProvider("style", ("choice", "detail"),
                                 valid={"terse", "verbose"}),
            ))
        try:
            config = restarted.sessions.session_config("s")
            assert config["switch_state"] == "needs_recovery"
            # the migration rebuilt the store, not the session
            assert config["current"]["profile_id"] == \
                profiles["base"]["profile_id"]
            outcome = restarted.sessions.reconcile("reconcile", session_id="s")
            assert outcome["state"] == "confirmed-current"
            reconciled = restarted.sessions.session_config("s")
            # the unproven application is resolved, so the session is sendable
            # again; the choice that was still pending waits for its turn
            assert reconciled["switch_state"] == "pending"
            assert reconciled["pending"]["profile_id"] == \
                profiles["model-only"]["profile_id"]
            assert restarted_port.counters["apply"] == 0
            # and the pending choice really applies after the restart
            restarted.sessions.begin_turn("after-restart", session_id="s")
            assert restarted.sessions.session_config("s")["switch_state"] == \
                "settled"
        finally:
            restarted.db.close()
    finally:
        core.db.close()
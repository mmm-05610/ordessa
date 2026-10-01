"""C-line acceptance counterexamples for the neutral session-configuration contract.

Each test here names the acceptance id from
``specs/021-nightly-product-closeout/overnight-acceptance.md`` §C that it
discriminates. These are *controlled* fixtures (constitution IV): the
``ScriptedConfigPort`` confirmation is labelled ``controlled-fixture`` and
proves Profile's journal/fence/overlay logic only, never a real Harness,
native process or product-chain observation.

The five ids C02/C03/C08/C10/C16 additionally require an L3/L4 observation in
the actual product chain; the tests here are their L1 half and say so.
"""
from __future__ import annotations

import pytest

from profile_harness_doubles import ScriptedConfigPort, ScriptedProvider, make_core
from ordessa_profile.errors import ProfileError


MODEL = ScriptedProvider(
    "model_selection", ("model", "reasoning"),
    valid={"m1", "m2", "m3", "low", "high"},
)


def native_world(tmp_path, *, providers=(MODEL,), harnesses=None):
    """A core whose application port applies effective configuration at every
    submit boundary (``native_turn_application``), which is the mode the
    product uses: all configuration application goes through the Harness
    public capability, never a Profile-side native writer."""
    port = ScriptedConfigPort()
    port.native_turn_application = True
    core = make_core(tmp_path, config_port=port, providers=providers,
                     harnesses=harnesses)
    return core, port


def blueprint(core, *, name="P", harness_id="pi", values=None):
    profile = core.profiles.create(f"c-{name}", harness_id=harness_id,
                                  display_name=name)
    values = values or [
        {"facet_id": "model_selection", "item_id": "model", "value": "m1"},
        {"facet_id": "model_selection", "item_id": "reasoning", "value": "low"},
    ]
    profile = core.profiles.set_facet_values(
        f"cv-{name}", profile_id=profile["profile_id"], expected_version=1,
        values=values)
    return profile


def applied_map(port):
    return {i.native_key: i.value for i in port.applied[-1]}


def global_values(core, profile_id):
    return {v["item_id"]: v["value"] for v in core.profiles.facet_values(profile_id)}


def session_items(core, session_id):
    return {(i["facet_id"], i["item_id"]): (i["value"], i["source"])
            for i in core.sessions.session_config(session_id)["items"]}


# --------------------------------------------------------------------------
# C01 -- the Profile stores a configuration blueprint only
# --------------------------------------------------------------------------
def test_c01_profile_record_is_a_blueprint_without_credentials_or_native_home(tmp_path):
    """C01: same blueprint -> two independent sessions; the Profile record
    carries no credential body and no native HOME copy."""
    core = native_world(tmp_path)[0]
    profile = blueprint(core)
    pid = profile["profile_id"]
    try:
        core.sessions.open_session("oa", session_id="A", harness_id="pi",
                                   profile_id=pid)
        core.sessions.open_session("ob", session_id="B", harness_id="pi",
                                   profile_id=pid)
        core.sessions.set_overlay("ov-a", session_id="A",
                                  facet_id="model_selection", item_id="model",
                                  value="m2")

        # The blueprint itself is byte-for-byte unchanged by a session override.
        assert global_values(core, pid) == {"model": "m1", "reasoning": "low"}
        assert core.profiles.get(pid)["current_revision"] == 2

        # The two sessions are distinct instances with independent overlays.
        assert session_items(core, "A")[("model_selection", "model")] == \
            ("m2", "session_only")
        assert session_items(core, "B")[("model_selection", "model")] == \
            ("m1", "profile")

        # No credential plaintext, no secret-shaped key anywhere in the record.
        with core.db.read() as conn:
            dump = "\n".join(
                str(tuple(row)) for row in conn.execute(
                    "SELECT * FROM profile_profiles WHERE profile_id=?",
                    (pid,)).fetchall())
        lowered = dump.lower()
        for forbidden in ("api_key", "apikey", "api-key", "password",
                          "token", "bearer", "sk-"):
            assert forbidden not in lowered, f"profile row leaks {forbidden}"

        # No native HOME directory was created or referenced for the Profile.
        assert not (tmp_path / ".codex").exists()
        assert not (tmp_path / ".claude").exists()
        assert not (tmp_path / "home").exists()
    finally:
        core.db.close()


def test_c01_secret_carrying_blueprint_value_is_refused(tmp_path):
    """C01 counterexample: a credential body may never be stored in a Profile
    value -- the ref is a reference, the secret lives in the keyring."""
    core = native_world(tmp_path)[0]
    profile = core.profiles.create("cb", harness_id="pi", display_name="P")
    try:
        with pytest.raises(ProfileError):
            core.profiles.set_facet_values(
                "cv", profile_id=profile["profile_id"], expected_version=1,
                values=[{"facet_id": "model_selection", "item_id": "model",
                         "value": {"apiKey": "sk-live-secret"}}])
        assert global_values(core, profile["profile_id"]) == {}
    finally:
        core.db.close()


# --------------------------------------------------------------------------
# C05 -- explicit switch to the same Harness Profile clears the overrides
# --------------------------------------------------------------------------
def test_c05_explicit_same_profile_selection_clears_temporary_overrides(tmp_path):
    """C05 counterexample: an explicit re-selection of the Profile the session
    is already bound to clears every temporary override -- silently, with no
    confirmation step -- and the next submit applies the Profile's own intent.

    ``native_turn_application`` mode must not confuse an *explicit* selection
    with the ordinary every-submit re-application, which keeps the overlays.
    """
    core, port = native_world(tmp_path)
    profile = blueprint(core)
    pid = profile["profile_id"]
    try:
        core.sessions.open_session("oa", session_id="s", harness_id="pi",
                                   profile_id=pid)
        core.sessions.begin_turn("t0", session_id="s")
        core.sessions.set_overlay("ov", session_id="s",
                                  facet_id="model_selection", item_id="model",
                                  value="m2")
        assert session_items(core, "s")[("model_selection", "model")][1] == \
            "session_only"

        # The user explicitly re-selects the Profile the session is bound to.
        core.sessions.select_profile("sel", session_id="s", profile_id=pid)
        result = core.sessions.begin_turn("t1", session_id="s")

        # The temporary override no longer governs: the native port is driven
        # back to the Profile's own value. Fields already in force at that
        # value are simply not re-sent.
        assert applied_map(port)["model_selection.model"] == "m1"
        applied_values = set(applied_map(port).values())
        assert applied_values <= {"m1", "low"}
        assert session_items(core, "s") == {
            ("model_selection", "model"): ("m1", "profile"),
            ("model_selection", "reasoning"): ("low", "profile"),
        }
        assert not any(i["source"] == "session_only"
                       for i in result["effective"])

        # Clearing the override layer is not a write-back into the blueprint.
        assert global_values(core, pid) == {"model": "m1", "reasoning": "low"}
    finally:
        core.db.close()


def test_c05_ordinary_submit_without_selection_keeps_the_overrides(tmp_path):
    """The other half of C05, and the reason the two paths must stay
    distinguishable: an ordinary submit with no selection re-applies the
    effective configuration, which includes the live temporary override."""
    core, port = native_world(tmp_path)
    profile = blueprint(core)
    pid = profile["profile_id"]
    try:
        core.sessions.open_session("oa", session_id="s", harness_id="pi",
                                   profile_id=pid)
        core.sessions.begin_turn("t0", session_id="s")
        core.sessions.set_overlay("ov", session_id="s",
                                  facet_id="model_selection", item_id="model",
                                  value="m2")
        core.sessions.begin_turn("t1", session_id="s")
        assert applied_map(port) == {
            "model_selection.model": "m2",
            "model_selection.reasoning": "low",
        }
        assert session_items(core, "s")[("model_selection", "model")][1] == \
            "session_only"
    finally:
        core.db.close()


def test_c05_same_profile_switch_raises_no_confirmation_dialog(tmp_path):
    """C05: there is no confirm/accept step in the switching surface at all --
    the API is select -> (next send applies). Proven structurally over the
    public method set, not by observing a particular response."""
    core = native_world(tmp_path)[0]
    try:
        surface = {name for name in dir(core.sessions)
                   if not name.startswith("_")}
        assert not (surface & {"confirm", "confirm_switch", "accept_switch",
                               "prompt_switch", "request_confirmation"})
    finally:
        core.db.close()


# --------------------------------------------------------------------------
# C06 -- a change made while output is streaming records intent only
# --------------------------------------------------------------------------
def test_c06_selection_and_override_while_streaming_touch_no_port(tmp_path):
    """C06 counterexample: the Harness application port is never called by a
    selection or a temporary override -- no native set, no restore, no cancel.
    The effect count must still be exactly the zero it was before."""
    core, port = native_world(tmp_path)
    profile = blueprint(core)
    other = blueprint(core, name="Q", values=[
        {"facet_id": "model_selection", "item_id": "model", "value": "m3"},
        {"facet_id": "model_selection", "item_id": "reasoning", "value": "high"},
    ])
    pid = profile["profile_id"]
    try:
        core.sessions.open_session("oa", session_id="s", harness_id="pi",
                                   profile_id=pid)
        core.sessions.begin_turn("t0", session_id="s")   # a turn is in flight
        before = dict(port.counters)
        assert before["apply"] == 1 and before["plan"] == 1

        core.sessions.select_profile("sel-1", session_id="s",
                                    profile_id=other["profile_id"])
        core.sessions.set_overlay("ov", session_id="s",
                                  facet_id="model_selection", item_id="model",
                                  value="m2")
        core.sessions.clear_overlay("cl", session_id="s",
                                    facet_id="model_selection", item_id="model")
        core.sessions.set_overlay("ov2", session_id="s",
                                  facet_id="model_selection", item_id="model",
                                  value="m3")

        assert port.counters == before, "a mid-stream change reached the port"
        assert len(port.applied) == 1
        assert port.counters["restart"] == 0

        # Nothing was sent either: only one turn row exists so far.
        assert len(core.sessions.turns("s")) == 1
    finally:
        core.db.close()


# --------------------------------------------------------------------------
# C08 / C11 -- revision race and Unknown converge by query, never by redo
# --------------------------------------------------------------------------
def test_c08_global_revision_change_between_prepare_and_execute_is_refused(tmp_path):
    """C08 counterexample: a plan computed against a stale global revision is
    rejected before any effect, never applied and never confirmed."""
    core, port = native_world(tmp_path)
    profile = blueprint(core)
    pid = profile["profile_id"]
    try:
        core.sessions.open_session("oa", session_id="s", harness_id="pi",
                                   profile_id=pid)
        original_plan = port.plan

        def plan_then_bump(target, desired, operation_key):
            result = original_plan(target, desired, operation_key)
            core.profiles.set_facet_values(
                "bump", profile_id=pid, expected_version=2,
                values=[{"facet_id": "model_selection", "item_id": "model",
                         "value": "m3"}])
            return result

        port.plan = plan_then_bump
        with pytest.raises(ProfileError, match="changed during preparation"):
            core.sessions.begin_turn("stale", session_id="s")
        assert port.applied == [], "a stale plan reached the native port"
        assert core.sessions.turns("s") == []

        # Re-reading and retrying is the user's explicit next send, and it
        # picks up the *new* revision.
        port.plan = original_plan
        result = core.sessions.begin_turn("retry", session_id="s")
        assert applied_map(port) == {
            "model_selection.model": "m3",
            "model_selection.reasoning": "low",
        }
        assert result["config_revision"] == 3
    finally:
        core.db.close()


def test_c11_unknown_converges_by_querying_the_same_operation_exactly_once(tmp_path):
    """C11 counterexample: an Unknown outcome leaves the draft, the pending
    selection and the overlays untouched; it is never marked success; the send
    stays blocked; and the effect count is exactly one -- the same operation
    converges through ``reconcile``, never through a second apply."""
    core, port = native_world(tmp_path)
    profile = blueprint(core)
    other = blueprint(core, name="Q", values=[
        {"facet_id": "model_selection", "item_id": "model", "value": "m3"},
        {"facet_id": "model_selection", "item_id": "reasoning", "value": "high"},
    ])
    pid = profile["profile_id"]
    try:
        core.sessions.open_session("oa", session_id="s", harness_id="pi",
                                   profile_id=pid)
        core.sessions.begin_turn("t0", session_id="s")
        core.sessions.set_overlay("ov", session_id="s",
                                  facet_id="model_selection", item_id="model",
                                  value="m2")
        core.sessions.select_profile("sel", session_id="s",
                                     profile_id=other["profile_id"])
        port.apply_verdict = "unknown"
        with pytest.raises(ProfileError) as excinfo:
            core.sessions.begin_turn("attempt", session_id="s")
        assert excinfo.value.code == "SESSION_NEEDS_RECOVERY"
        assert excinfo.value.current["operation_id"]

        # Exactly one effect attempt ever reached the port (t0 plus the
        # unproven switch -- no retry rode along with it).
        assert port.counters["apply"] == 2
        assert len(port.applied) == 2

        # Sending stays blocked, and blocking costs no further effect.
        with pytest.raises(ProfileError) as again:
            core.sessions.begin_turn("again", session_id="s")
        assert again.value.code == "SESSION_NEEDS_RECOVERY"
        assert port.counters["apply"] == 2

        view = core.sessions.session_view(_session_row(core, "s"))
        assert view["switch_state"] == "needs_recovery"
        assert view["pending_profile_id"] == other["profile_id"], \
            "unknown cleared the selection"
        assert view["current_profile_id"] == pid, "unknown moved the binding"
        # The draft-level overlay is intact and still labelled session-only.
        assert session_items(core, "s")[("model_selection", "model")][1] == \
            "session_only"
        # No turn was recorded for the unproven attempt, so nothing was ever
        # marked as sent.
        assert [t["turn_seq"] for t in core.sessions.turns("s")] == [1]

        # Converging means querying the *same* operation, never a second apply.
        port.apply_verdict = "confirmed"
        recovered = core.sessions.reconcile("query", session_id="s")
        assert recovered["state"] == "confirmed-current"
        assert recovered["operation_id"] == excinfo.value.current["operation_id"]
        assert port.counters["apply"] == 2, "reconcile re-applied the effect"
        assert port.counters["reconcile"] == 1
        assert port.reconciled == [
            f"{view['session_uid']}:{excinfo.value.current['operation_id']}"]
    finally:
        core.db.close()


def _session_row(core, session_id):
    with core.db.read() as conn:
        return core.sessions._require_session(conn, session_id)


# --------------------------------------------------------------------------
# C10 -- a refused first preparation fabricates nothing
# --------------------------------------------------------------------------
def test_c10_refused_first_preparation_fabricates_no_session_and_keeps_intent(tmp_path):
    """C10 counterexample (L1 half): a blocked preparation creates no turn, no
    false registration of an applied switch, and no duplicated session/new --
    the selection survives verbatim so the user can fix the configuration and
    explicitly send again."""
    core, port = native_world(tmp_path)
    profile = blueprint(core)
    other = blueprint(core, name="Q", values=[
        {"facet_id": "model_selection", "item_id": "model", "value": "m3"},
        {"facet_id": "model_selection", "item_id": "reasoning", "value": "high"},
    ])
    pid = profile["profile_id"]
    try:
        core.sessions.open_session("oa", session_id="s", harness_id="pi",
                                   profile_id=pid)
        core.sessions.begin_turn("t0", session_id="s")
        core.sessions.select_profile("sel", session_id="s",
                                     profile_id=other["profile_id"])

        port.apply_verdict = "rejected"
        with pytest.raises(ProfileError) as excinfo:
            core.sessions.begin_turn("refused", session_id="s")
        assert excinfo.value.code == "SWITCH_BLOCKED"

        assert port.counters["apply"] == 2, "a refusal was retried blind"
        assert len(core.sessions.turns("s")) == 1, "a refused turn was recorded"
        row = _session_row(core, "s")
        assert row["current_profile_id"] == pid, "a refusal moved the binding"
        assert row["pending_profile_id"] == other["profile_id"], \
            "a refusal discarded the user's selection"
        assert row["switch_state"] == "pending"

        # Correcting nothing and re-sending is one explicit, counted retry.
        port.apply_verdict = "confirmed"
        core.sessions.begin_turn("retry", session_id="s")
        assert port.counters["apply"] == 3
        assert len(core.sessions.turns("s")) == 2
        assert _session_row(core, "s")["current_profile_id"] == other["profile_id"]
    finally:
        core.db.close()


# --------------------------------------------------------------------------
# C12 -- a refusal yields no usable receipt
# --------------------------------------------------------------------------
def test_c12_refused_operation_yields_no_receipt_and_no_operation_id_reuse(tmp_path):
    """C12 counterexample: a refused application leaves no AppliedReceipt, and
    an operation id is never reusable for different input."""
    core, port = native_world(tmp_path)
    profile = blueprint(core)
    other = blueprint(core, name="Q", values=[
        {"facet_id": "model_selection", "item_id": "model", "value": "m3"},
        {"facet_id": "model_selection", "item_id": "reasoning", "value": "high"},
    ])
    pid = profile["profile_id"]
    try:
        core.sessions.open_session("oa", session_id="s", harness_id="pi",
                                   profile_id=pid)
        core.sessions.begin_turn("t0", session_id="s")
        core.sessions.select_profile("sel", session_id="s",
                                     profile_id=other["profile_id"])
        port.apply_verdict = "rejected"
        with pytest.raises(ProfileError):
            core.sessions.begin_turn("refused", session_id="s")

        with core.db.read() as conn:
            rows = conn.execute(
                "SELECT operation_id, state FROM profile_application_journal"
                " ORDER BY created_at"
            ).fetchall()
        # One journal row per operation; a refusal ends in `rejected` and
        # leaves no receipt behind.
        assert [r["state"] for r in rows] == ["confirmed", "rejected"]
        with core.db.read() as conn:
            receipts = conn.execute(
                "SELECT COUNT(*) AS n FROM profile_applied_receipts"
            ).fetchone()
        assert receipts["n"] == 1, "a refused operation produced a receipt"
        with core.db.read() as conn:
            receipted = {r["operation_id"] for r in conn.execute(
                "SELECT operation_id FROM profile_applied_receipts")}
        assert receipted == {rows[0]["operation_id"]}

        # The corrected retry is a *distinct* operation id, never a replay of
        # the refused one under the same key.
        seen_before = {r["operation_id"] for r in rows}
        port.apply_verdict = "confirmed"
        core.sessions.begin_turn("corrected", session_id="s")
        with core.db.read() as conn:
            after = {r["operation_id"] for r in conn.execute(
                "SELECT operation_id FROM profile_application_journal")}
        assert after - seen_before, "the retry reused the refused operation id"
    finally:
        core.db.close()

# --------------------------------------------------------------------------
# C19 -- base CRUD, naming, harness ownership and persistence do not regress
# --------------------------------------------------------------------------
def test_c19_blueprint_survives_a_restart_and_reads_back_identical(tmp_path):
    """C19: the stored blueprint is durable and unchanged across a restart --
    same name, same harness ownership, same per-item values."""
    core = native_world(tmp_path)[0]
    profile = blueprint(core)
    pid = profile["profile_id"]
    try:
        core.sessions.open_session("oa", session_id="s", harness_id="pi",
                                   profile_id=pid)
        core.sessions.set_overlay("ov", session_id="s",
                                  facet_id="model_selection", item_id="model",
                                  value="m2")
        before = core.profiles.get(pid)
        values_before = global_values(core, pid)
    finally:
        core.db.close()

    restarted, _port = native_world(tmp_path)
    try:
        after = restarted.profiles.get(pid)
        assert after["display_name"] == before["display_name"] == "P"
        assert after["harness_id"] == before["harness_id"] == "pi"
        assert after["current_revision"] == before["current_revision"]
        assert global_values(restarted, pid) == values_before

        # The session overlay is a session fact, and it came back with its
        # session -- it was never folded into the blueprint.
        assert session_items(restarted, "s")[("model_selection", "model")] == \
            ("m2", "session_only")
        assert global_values(restarted, pid) == {"model": "m1", "reasoning": "low"}
    finally:
        restarted.db.close()


def test_c19_a_bound_session_cannot_silently_change_harness(tmp_path):
    """C19: a draft may choose a Harness, but a session already bound to one
    cannot be re-pointed at another. The refusal happens before any state
    change and leaves the binding intact."""
    core = native_world(tmp_path)[0]
    try:
        pi = blueprint(core, name="Pi profile", harness_id="pi")
        codex = blueprint(core, name="Codex profile", harness_id="codex")
        core.sessions.open_session("oa", session_id="s", harness_id="pi",
                                   profile_id=pi["profile_id"])

        with pytest.raises(ProfileError) as excinfo:
            core.sessions.select_profile("cross", session_id="s",
                                         profile_id=codex["profile_id"])
        assert excinfo.value.code == "SESSION_PROFILE_MISMATCH"
        row = _session_row(core, "s")
        assert row["harness_id"] == "pi"
        assert row["current_profile_id"] == pi["profile_id"]
        assert row["pending_profile_id"] is None
    finally:
        core.db.close()


# --------------------------------------------------------------------------
# C09 -- unload removes the editor entry but preserves the data
# --------------------------------------------------------------------------
def test_c09_unload_hides_the_setting_and_reload_restores_the_original_value(tmp_path):
    """C09: a resource contributor that unloads disappears from the editor,
    while its stored value survives untouched and comes back on reload.
    Applicability is never faked while it is gone."""
    style = ScriptedProvider("output_style", ("style",), title="Output style",
                             valid={"terse", "verbose"})
    core = native_world(tmp_path, providers=(MODEL, style))[0]
    try:
        profile = blueprint(core, values=[
            {"facet_id": "model_selection", "item_id": "model", "value": "m1"},
            {"facet_id": "output_style", "item_id": "style", "value": "terse"},
        ])
        pid = profile["profile_id"]
        core.sessions.open_session("oa", session_id="s", harness_id="pi",
                                   profile_id=pid)

        core.unregister_provider(style)
        projection = core.profiles.settings_projection(pid)
        assert [f["facet_id"] for f in projection["facets"]] == \
            ["model_selection"], "the unloaded facet is still in the editor"
        stored = {v["item_id"]: v["value"]
                  for v in core.profiles.facet_values(pid)}
        assert stored == {"model": "m1", "style": "terse"}, "unload deleted data"
        # ...and the retained value is never quietly applied while absent.
        preview = core.profiles.resolution_preview(pid)
        assert {"facet_id": "output_style", "item_id": "style",
                "reason": "provider_absent"} in preview["unavailable"]
        assert all(i["facet_id"] != "output_style" for i in preview["items"])

        reloaded = ScriptedProvider("output_style", ("style",),
                                    title="Output style",
                                    valid={"terse", "verbose"},
                                    stored_ruling="accepted", version="1.1.0")
        report = core.register_provider(reloaded)
        assert (report.accepted, report.quarantined, report.migrated) == (1, 0, 0)
        stored = {v["item_id"]: v["value"]
                  for v in core.profiles.facet_values(pid)}
        assert stored == {"model": "m1", "style": "terse"}, "reload lost the value"
        assert {f["facet_id"] for f in
                core.profiles.settings_projection(pid)["facets"]} == \
            {"model_selection", "output_style"}
    finally:
        core.db.close()


def test_c09_a_required_provider_absent_at_send_time_refuses_explicitly(tmp_path):
    """C09 counterexample: absence is never papered over. A session whose
    required configuration cannot be resolved refuses the send with a typed
    refusal naming the item -- no silent defaults, no partial turn."""
    from profile_harness_doubles import StaticHarnessCatalog

    catalog = StaticHarnessCatalog({
        "pi": frozenset(), "codex": frozenset({"output_style/style"})})
    core = native_world(tmp_path, harnesses=catalog)[0]
    try:
        profile = blueprint(core, name="P1", harness_id="codex", values=[
            {"facet_id": "model_selection", "item_id": "model", "value": "m1"}])
        core.sessions.open_session("oa", session_id="s", harness_id="codex",
                                   profile_id=profile["profile_id"])
        with pytest.raises(ProfileError) as excinfo:
            core.sessions.begin_turn("send", session_id="s")
        assert excinfo.value.code == "FACET_PROVIDER_UNAVAILABLE"
        assert excinfo.value.item == "output_style/style"
        assert core.sessions.turns("s") == [], "a refused send recorded a turn"
    finally:
        core.db.close()

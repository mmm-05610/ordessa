"""EXT-5 — adapter conformance against the published protocol."""
from __future__ import annotations

import pytest
from ordessa_harness_api import (
    ErrorCode, Installation, IntentSet, Match, Mismatch, MountContent,
    SetField, VerificationUnknown,
)

from ordessa_extensions.adapters import hooks_adapters
from ordessa_extensions.adapters.contribution import (
    CONFIGURATION_POINT, POINT_API_VERSION,
    build_claude_intents, build_codex_intents, build_managed_set_payload,
)

from doubles import (
    CLAUDE_INSTALLATION, CODEX_INSTALLATION, claude_settings_target,
    codex_file_target, context_for,
)


def desired_set(**hook_overrides):
    return build_managed_set_payload(
        [definitions_hook(**hook_overrides)],
        runtime_generation="gen-1", project_id="proj-1")


def definitions_hook(**overrides):
    from ordessa_extensions.definitions import HookDefinition
    fields = dict(
        hook_id="notify", event="SessionStart", action_kind="command",
        command=("notify-send", "hello"), handler_ref=None,
        timeout_seconds=30, run_async=False, pin="0.147.0",
        content_sha256="sha256:" + "ab" * 32)
    fields.update(overrides)
    return HookDefinition(**fields)


# -- registration identity -------------------------------------------------

def test_point_constants_match_the_harness_handler():
    """Duplicated-string discipline: pinned against the real constants
    WITHOUT importing them into the package (AGENTS.md rule 3) — the
    TEST imports `ordessa_harness` (the harness plugin dist, installed
    editable in the verification venv per docs/baseline.md, same
    test-only reliance as the Skills registration tests); the PACKAGE
    never does, which test_dependency_direction enforces on src/."""
    from ordessa_harness import contributions
    assert CONFIGURATION_POINT == contributions.CONFIGURATION_POINT
    assert POINT_API_VERSION == contributions.POINT_API_VERSION


def test_descriptor_shape_and_facet():
    for adapter in hooks_adapters():
        d = adapter.descriptor
        assert d.facet_id == "assets.hooks"
        assert d.api_version == "v1"
        assert d.entries == ("acp",)
        assert not hasattr(adapter, "owner")
        # structural conformance with the published Protocol (plain
        # Protocol, not runtime_checkable — shape-asserted here)
        assert callable(adapter.assess) and callable(adapter.compile) \
            and callable(adapter.verify)
        assert d.adapter_id == f"assets.hooks.{d.harness_id}"


def test_claims_reflect_the_slot_shapes():
    codex = hooks_adapters()[0].descriptor
    claude = hooks_adapters()[1].descriptor
    assert codex.claims[0].field_path == ("hooks-document",)
    assert codex.claims[0].target_kind == "file"
    assert claude.claims[0].field_path == ("hooks",)


# -- assess -----------------------------------------------------------------

def test_assess_uninspected_version_is_unknown():
    adapter = hooks_adapters()[0]
    context = context_for(Installation("codex", None, (1, 1, 14), "x"),
                          codex_file_target())
    assert adapter.assess(context, None).status == "unknown"


def test_assess_foreign_identity_is_unknown_never_supported():
    # a foreign brand whose version tuple happens to equal the pin is
    # still never graded (identity gate, review round 5)
    adapter = hooks_adapters()[0]
    foreign = Installation("mystery", (0, 147, 0), (1, 1, 14), "x")
    assert adapter.assess(context_for(foreign, codex_file_target()),
                          None).status == "unknown"


def test_assess_pinned_but_no_target_is_projection_pending():
    # round 10: the supported grade requires a server-issued hooks target
    # — without one the claim cannot be cashed (AR-3)
    adapter = hooks_adapters()[0]
    context = context_for(CODEX_INSTALLATION)  # no targets
    assessment = adapter.assess(context, None)
    assert assessment.status == "unknown"
    assert "projection pending" in assessment.reason


def test_assess_pinned_with_target_still_projection_pending_on_schema():
    # round 12: assess never grades a status compile cannot cash — even
    # with pin+target, the unevidenced native value schema keeps the
    # answer unknown (the supported day waits on the schema gate)
    adapter = hooks_adapters()[0]
    context = context_for(CODEX_INSTALLATION, codex_file_target())
    assessment = adapter.assess(context, None)
    assert assessment.status == "unknown"
    assert "projection pending" in assessment.reason
    assert "source-index.json" in assessment.reason


def test_assess_adapter_version_mismatch_is_unsupported():
    # adapter_version is non-optional in the published contract, so only
    # the mismatch case exists — machine pin -> unsupported (fail-closed)
    adapter = hooks_adapters()[0]
    context = context_for(Installation("codex", (0, 147, 0), (9, 9, 9), "x"),
                          codex_file_target())
    assert adapter.assess(context, None).status == "unsupported"


def test_assess_version_mismatch_is_unsupported_fail_closed():
    adapter = hooks_adapters()[0]
    context = context_for(Installation("codex", (0, 148, 0), (1, 1, 14), "x"),
                          codex_file_target())
    assessment = adapter.assess(context, None)
    assert assessment.status == "unsupported"
    assert "production.py:88" in assessment.reason


def test_assess_claude_comment_grade_mismatch_is_unknown():
    # claude's CLI pin is comment-grade (harnesses.toml:111) — a
    # differing observation is NOT first-hand evidence of anything, so
    # it grades unknown (fail-closed), never unsupported (review round 6)
    adapter = hooks_adapters()[1]
    context = context_for(Installation("claude", (2, 2, 0), (0, 81, 2), "x"),
                          claude_settings_target())
    assessment = adapter.assess(context, None)
    assert assessment.status == "unknown"
    assert "comment" in assessment.reason
    assert "never supported" in assessment.reason


def test_assess_bad_payload_makes_no_capability_claim():
    # a caller-side payload error is never graded as a capability level
    # (round 9: unknown, not unsupported)
    adapter = hooks_adapters()[0]
    context = context_for(CODEX_INSTALLATION, codex_file_target())
    payload = desired_set()
    payload["hooks"][0]["event"] = "PostToolUse"
    assessment = adapter.assess(context, payload)
    assert assessment.status == "unknown"
    assert "caller error" in assessment.reason


# -- compile ----------------------------------------------------------------

def test_compile_refuses_without_a_runtime_target():
    adapter = hooks_adapters()[0]
    context = context_for(CODEX_INSTALLATION)  # no targets: today's truth
    refusal = adapter.compile(context, None, desired_set())
    assert refusal.code == ErrorCode.ADAPTER_MISSING
    assert "declaring the claimed face" in refusal.reason


def test_compile_terminal_refusal_is_the_ar3_deliverable():
    # with a server-issued target present, compile still refuses: the
    # terminal gate is the evidenced AR-3 schema gap (the task-side
    # sanctioned deliverable — api-requests.md)
    adapter = hooks_adapters()[0]
    context = context_for(CODEX_INSTALLATION, codex_file_target())
    refusal = adapter.compile(context, None, desired_set())
    assert refusal.code == ErrorCode.CAPABILITY_UNSUPPORTED
    assert "source-index.json" in refusal.reason


def test_keyed_target_without_the_claimed_part_is_not_ours():
    # round 11: an empty allowed_fields is NOT a wildcard — an
    # unrestricted json file target is NOT ours to write
    adapter = hooks_adapters()[1]
    unrestricted = claude_settings_target(with_allowed_fields=False)
    context = context_for(CLAUDE_INSTALLATION, unrestricted)
    refusal = adapter.compile(context, None, desired_set())
    assert refusal.code == ErrorCode.ADAPTER_MISSING
    restrictive = claude_settings_target()  # declares ("hooks",)
    ok = adapter.compile(
        context_for(CLAUDE_INSTALLATION, restrictive), None, desired_set())
    assert ok.code == ErrorCode.CAPABILITY_UNSUPPORTED  # past target gate
    # a target declaring a DIFFERENT part is equally not ours (round 12)
    from ordessa_harness_api import TargetDescriptor, TargetHandle
    other_face = TargetDescriptor(
        handle=TargetHandle("settings", 1), kind="file", codec="json",
        scope="instance", allowed_fields=(("other",),))
    refusal2 = adapter.compile(
        context_for(CLAUDE_INSTALLATION, other_face), None, desired_set())
    assert refusal2.code == ErrorCode.ADAPTER_MISSING


def test_compile_refuses_a_blocking_claim():
    # the payload schema's enum constraint IS the inexpressibility proof:
    # a "blocking" semantics value never validates
    adapter = hooks_adapters()[0]
    context = context_for(CODEX_INSTALLATION, codex_file_target())
    blocking = desired_set()
    blocking["hooks"][0]["semantics"] = "blocking"
    refusal = adapter.compile(context, None, blocking)
    assert refusal.code == ErrorCode.INVALID_FRAGMENT


def test_compile_refuses_unevidenced_event_before_anything_else():
    adapter = hooks_adapters()[0]
    context = context_for(CODEX_INSTALLATION, codex_file_target())
    payload = desired_set()
    payload["hooks"][0]["event"] = "SessionEnd"
    refusal = adapter.compile(context, None, payload)
    assert refusal.code == ErrorCode.INVALID_FRAGMENT


# -- intent construction (the 定义就绪 half, tested directly) -----------------

def test_codex_intents_mount_whole_file_read_only():
    import re
    from ordessa_harness_api import IntentSource
    target = codex_file_target()
    intents = build_codex_intents(
        IntentSource("assets.hooks", "assets.hooks.codex", "1"),
        target, desired_set())
    assert isinstance(intents, IntentSet)
    (mount,) = intents.intents
    assert isinstance(mount, MountContent)
    assert mount.relative_name == "hooks/hooks.json"
    assert mount.mode == "read-only"
    digest = mount.immutable_content_ref.sha256
    assert re.fullmatch(r"[0-9a-f]{64}", digest), digest
    assert mount.immutable_content_ref.size > 0


def test_claude_intents_set_the_hooks_key():
    from ordessa_harness_api import IntentSource
    target = claude_settings_target()
    source = IntentSource("assets.hooks", "assets.hooks.claude", "1")
    claude_payload = desired_set()
    claude_payload["hooks"][0]["pin"] = "0.81.2"
    intents = build_claude_intents(source, target, claude_payload)
    (setfield,) = intents.intents
    assert isinstance(setfield, SetField)
    assert setfield.field_path.segments == ("hooks",)
    assert setfield.typed_value[0]["event"] == "SessionStart"


# -- verify -----------------------------------------------------------------

def test_verify_digest_match_is_observational_only():
    adapter = hooks_adapters()[0]
    context = context_for(CODEX_INSTALLATION)
    good = "a" * 64
    result = adapter.verify(context, {
        "source": "projection_digest", "expectedDigest": good,
        "observedDigest": good})
    assert isinstance(result, Match)
    assert "NOT claimed" in result.evidence_ref


def test_verify_malformed_digests_never_match():
    adapter = hooks_adapters()[0]
    context = context_for(CODEX_INSTALLATION)
    for expected, seen in (("sha256:ff", "a" * 64),      # prefixed, not hex
                           ("aaa", "a" * 64),            # too short expected
                           ("a" * 64, "b" * 63),         # malformed seen
                           (None, "a" * 64),             # absent expected
                           ("a" * 64, None)):            # absent seen
        result = adapter.verify(context, {
            "source": "projection_digest", "expectedDigest": expected,
            "observedDigest": seen})
        assert isinstance(result, VerificationUnknown), (expected, seen)


def test_verify_native_file_stat_grades_like_placement_fact():
    # the file-stat source is a placement observation too (round 15):
    # matching digests Match; mismatching, missing and malformed digests
    # never do (negatives asserted on THIS source, round 16)
    adapter = hooks_adapters()[0]
    context = context_for(CODEX_INSTALLATION)
    good = "c" * 64
    assert isinstance(adapter.verify(context, {
        "source": "native_file_stat", "expectedDigest": good,
        "observedDigest": good}), Match)
    assert isinstance(adapter.verify(context, {
        "source": "native_file_stat", "expectedDigest": good,
        "observedDigest": "d" * 64}), Mismatch)
    assert isinstance(adapter.verify(context, {
        "source": "native_file_stat", "expectedDigest": good,
        "observedDigest": None}), VerificationUnknown)
    assert isinstance(adapter.verify(context, {
        "source": "native_file_stat", "expectedDigest": "sha256:ff",
        "observedDigest": "sha256:ff"}), VerificationUnknown)


def test_verify_digest_mismatch_is_a_mismatch():
    adapter = hooks_adapters()[0]
    context = context_for(CODEX_INSTALLATION)
    result = adapter.verify(context, {
        "source": "projection_digest", "expectedDigest": "a" * 64,
        "observedDigest": "b" * 64})
    assert isinstance(result, Mismatch)


def test_verify_absent_observed_digest_is_never_a_match():
    adapter = hooks_adapters()[0]
    context = context_for(CODEX_INSTALLATION)
    for seen in (None, "", 7):
        result = adapter.verify(context, {
            "source": "projection_digest", "expectedDigest": "aaa",
            "observedDigest": seen})
        assert isinstance(result, VerificationUnknown), seen


def test_verify_load_event_is_unknown_even_with_a_mismatching_digest():
    # an unevidenced port can neither confirm nor contradict: the load
    # refusal is graded BEFORE any digest comparison
    adapter = hooks_adapters()[0]
    context = context_for(CODEX_INSTALLATION)
    result = adapter.verify(context, {
        "source": "native_load_event", "expectedDigest": "a" * 64,
        "observedDigest": "b" * 64})
    assert isinstance(result, VerificationUnknown)
    assert "never promote" in result.reason


def test_verify_never_promotes_to_loaded():
    adapter = hooks_adapters()[0]
    context = context_for(CODEX_INSTALLATION)
    load_event = adapter.verify(context, {
        "source": "native_load_event", "expectedDigest": "aaa"})
    model_claim = adapter.verify(context, {
        "source": "model_claim", "expectedDigest": "aaa"})
    assert isinstance(load_event, VerificationUnknown)
    assert isinstance(model_claim, VerificationUnknown)


def test_verify_rejects_foreign_identity_and_garbage():
    adapter = hooks_adapters()[0]
    context = context_for(CODEX_INSTALLATION)
    assert isinstance(adapter.verify(context, "not a mapping"),
                      VerificationUnknown)
    assert isinstance(adapter.verify(context_for(CLAUDE_INSTALLATION),
                                     {"source": "projection_digest",
                                      "expectedDigest": "a"}),
                      VerificationUnknown)


# -- capability rows ----------------------------------------------------------

def test_capability_rows_grade_from_the_table():
    from ordessa_harness_api import ApplicationTarget
    adapter = hooks_adapters()[0]
    target = ApplicationTarget("srv", "sess", "chan", 7)
    rows = adapter.configuration_capabilities(target)
    by_op = {row.operation: row for row in rows.capabilities}
    assert by_op["content"].status == "unsupported"  # runtime gap
    assert by_op["reset"].status == "unsupported"
    assert by_op["action"].status == "unknown"       # load_evidence
    assert by_op["secret"].status == "unknown"

"""Fake-green audit + G16: a digest match alone may only yield `projected`.

verification.md G16 counter-examples: "调 digest-verify 即记 loaded、模型
口头声称 used 即记 used". harness-adapters.md §原生包安全与使用事实 fixes
the positive rules: `loaded` needs a native load fact or a deterministic
load result through a FIXED adapter (an evidenced port); `used` needs a
session-specific independent invocation event. The legacy
`harness_delivery.verify_load` (digest-match -> "loaded") is explicitly
retired — these tests pin that the new modules cannot reproduce it.
"""
from __future__ import annotations

import pytest

from ordessa_skills.harness_adapters import base, claude, codex, pi
from ordessa_skills.harness_adapters.base import ObservationResult
from ordessa_skills.harness_adapters.capabilities import (
    SUPPORTED, UNKNOWN, CapabilityFact, statement_for,
)
from ordessa_skills.api import evidence as ladder

DIGEST = "sha256:" + "a" * 64
OTHER = "sha256:" + "b" * 64
BRANDS = ("pi", "codex", "claude-code")


def _obs(source: str, *, observed=DIGEST, harness="pi", session=False,
         name="solo"):
    return ObservationResult(
        harness_id=harness, asset_id="solo-skill", revision=1,
        native_name=name, tree_digest=DIGEST, source=source,
        observed_tree_digest=observed, session_bound=session)


# -- the digest ceiling --------------------------------------------------------

@pytest.mark.parametrize("harness_id", BRANDS)
def test_digest_match_alone_never_produces_loaded_or_used(harness_id):
    """The headline fake-green audit: projection digest + native listing
    are PLACEMENT facts. Graded at most `projected`, for every brand."""
    module = {"pi": pi, "codex": codex, "claude-code": claude}[harness_id]
    for source in (base.SOURCE_PROJECTION_DIGEST, base.SOURCE_NATIVE_LISTING):
        outcome = module.verify(_obs(source, harness=harness_id))
        assert outcome.level == ladder.PROJECTED, (harness_id, source)
        assert outcome.level not in (ladder.LOADED, ladder.USED)
        assert outcome.proves_load is False


def test_digest_mismatch_downgrades_to_unknown():
    outcome = pi.verify(_obs(base.SOURCE_PROJECTION_DIGEST, observed=OTHER))
    assert outcome.level == ladder.UNKNOWN
    assert outcome.reason == "digest_identity_mismatch"


@pytest.mark.parametrize("harness_id", BRANDS)
@pytest.mark.parametrize("source", base.OBSERVATION_SOURCES)
def test_no_brand_no_source_can_ever_report_loaded_or_used_today(harness_id, source):
    """Exhaustive sweep: with every `loaded_evidence` and
    `explicit_invocation` cell `unknown` (the frozen matrix state), the
    ladder tops out at `projected` — nothing in this domain can fake a
    load or a use today."""
    outcome = base.verify(_obs(source, harness=harness_id, session=True),
                          harness_id=harness_id)
    assert outcome.level in (ladder.PROJECTED, ladder.UNKNOWN)
    assert outcome.level not in (ladder.LOADED, ladder.USED)


# -- model claims are not evidence ----------------------------------------------

def test_a_model_saying_it_used_the_skill_promotes_nothing():
    outcome = pi.verify(_obs(base.SOURCE_MODEL_CLAIM, session=True))
    assert outcome.level == ladder.UNKNOWN
    assert outcome.reason == "model_claim_is_not_evidence"


def test_unverified_load_event_degrades_instead_of_being_believed():
    # A "native_load_event" from a brand whose load port has no evidence is
    # not believed into `loaded`; it reports `unknown` honestly.
    outcome = codex.verify(_obs(base.SOURCE_NATIVE_LOAD_EVENT,
                                harness="codex"))
    assert outcome.level == ladder.UNKNOWN
    assert outcome.reason.startswith("load_port_unverified")
    assert outcome.statement_evidence != "no in-repo evidence"


def test_invocation_event_without_evidenced_port_or_session_binding_stops_at_unknown():
    outcome = claude.verify(_obs(base.SOURCE_INVOCATION_EVENT,
                                 harness="claude-code", session=True))
    assert outcome.level == ladder.UNKNOWN
    assert outcome.reason == "invocation_port_unverified"


# -- what WOULD unlock loaded/used (documented, not promised) -------------------

def test_used_requires_both_an_evidenced_invocation_port_and_a_session_event():
    statement = statement_for("pi")
    assert statement.value("loaded_evidence") == UNKNOWN
    assert statement.value("explicit_invocation") == UNKNOWN
    assert base.evidence_ceiling(statement) == ladder.PROJECTED
    # The ladder itself refuses `used` without an invocation_event proof —
    # capability gating is layered ON TOP of the proof requirements.
    assert ladder.attest(ladder.USED, proofs={"projection_digest"}) == ladder.UNKNOWN
    assert ladder.attest(ladder.LOADED, proofs={"projection_digest"}) == ladder.UNKNOWN


def test_a_fabricated_supported_statement_is_the_only_path_past_projected():
    # Guarding the gate direction: if (and ONLY if) a brand gained evidenced
    # load/invocation ports, the same events would grade upward — proving
    # the refusal above is the capability gate and not a hardcoded floor.
    facts = {axis: CapabilityFact(axis=axis, value=UNKNOWN,
                                  evidence="no in-repo evidence")
             for axis in base.AXES}
    facts["loaded_evidence"] = CapabilityFact(
        axis="loaded_evidence", value=SUPPORTED,
        evidence="specs/011-q1-skills/research/brand-matrix.md:40")
    facts["explicit_invocation"] = CapabilityFact(
        axis="explicit_invocation", value=SUPPORTED,
        evidence="specs/011-q1-skills/research/brand-matrix.md:40")
    statement = base.CapabilityStatement(harness_id="probe", facts=facts)
    assert base.evidence_ceiling(statement) == ladder.USED
    # (The registry itself still has no such brand; verify() reads the
    # registry, so the sweep above stays honest for pi/codex/claude-code.)

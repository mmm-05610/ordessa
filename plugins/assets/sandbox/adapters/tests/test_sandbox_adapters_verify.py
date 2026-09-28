"""T05 — verify(observation): a read-only judgement in the PLATFORM vocabulary.

`verify` consumes a read-only ``EffectObservation`` (the backend probe seam) and
answers with ``ordessa_harness_api.contracts.Verification`` — ``Match`` /
``Mismatch`` / ``VerificationUnknown``. The former local ``VerifyResult``/
``VerifyOutcome`` mirror is deleted: one verdict vocabulary, the platform's.

Two things the §C4 rules still require and this file keeps proving:

* ``unsupported`` and ``unknown`` never merge. The platform ``Verification``
  trio has no ``unsupported`` member, so a proven negative is a
  ``VerificationUnknown`` whose reason carries the stable
  ``SANDBOX_NATIVE_UNSUPPORTED`` code (:func:`sandbox_code_of` reads it back),
  while an unresolved probe carries ``SANDBOX_EFFECT_UNKNOWN`` — and the two
  codes resolve to different wire families.
* nothing here is a confirmation of protection: a ``Match`` only says the
  observation agrees; this package applies no configuration and starts no
  effect, and the C4 service is the only thing that can answer ``Confirmed`` —
  from its own verified native readback, never from this call.
"""
from _sandbox_adapters_helpers import effect_observation

from ordessa_harness_api.contracts import Match, Mismatch, VerificationUnknown
from ordessa_sandbox_api import SandboxErrorCode, ToolCategory
from ordessa_sandbox_api.wire_family import wire_family_for
from ordessa_sandbox_adapters import CodexSandboxAdapter, sandbox_code_of


def test_verified_observation_yields_a_platform_match():
    v = CodexSandboxAdapter().verify(
        effect_observation("verified", covered=["bash", "edit"]))
    assert isinstance(v, Match)
    assert v.kind == "match"
    # a match names the evidence it came from, never a bare boolean
    assert v.evidence_ref.startswith("sandbox.effect-observation:codex")


def test_unknown_observation_stays_unknown():
    v = CodexSandboxAdapter().verify(effect_observation("unknown"))
    assert isinstance(v, VerificationUnknown)
    assert not isinstance(v, Match)
    assert sandbox_code_of(v.reason) is SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN


def test_unsupported_observation_stays_unsupported_not_unknown():
    v = CodexSandboxAdapter().verify(effect_observation("unsupported"))
    code = sandbox_code_of(v.reason)
    assert code is SandboxErrorCode.SANDBOX_NATIVE_UNSUPPORTED
    assert code is not SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN
    # and the §C4 pair stays in two different wire families
    other = CodexSandboxAdapter().verify(effect_observation("unknown"))
    assert wire_family_for(code) != wire_family_for(sandbox_code_of(other.reason))
    assert wire_family_for(code) == "CAPABILITY_UNSUPPORTED"


def test_a_non_observation_is_unknown_not_an_exception():
    for junk in (None, "verified", 7, {"outcome": "verified"}):
        v = CodexSandboxAdapter().verify(junk)
        assert isinstance(v, VerificationUnknown), junk
        assert not isinstance(v, (Match, Mismatch)), junk


def test_coverage_the_probe_did_not_observe_is_never_added_to_the_verdict():
    """A Claude adapter may not turn a Bash-only observation into a broader one."""
    from ordessa_sandbox_adapters import ClaudeSandboxAdapter
    v = ClaudeSandboxAdapter().verify(
        effect_observation("verified", covered=[ToolCategory.BASH]))
    assert isinstance(v, Match)
    assert "bash" in v.evidence_ref
    for broader in ("read", "edit", "mcp"):
        assert broader not in v.evidence_ref


def test_verify_starts_no_effect():
    """No apply path exists here: the verdict type carries no write at all."""
    v = CodexSandboxAdapter().verify(effect_observation("unknown"))
    assert type(v).__dataclass_fields__.keys() <= {"reason", "kind"}
    assert not hasattr(v, "effect_started")

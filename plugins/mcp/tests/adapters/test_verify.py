"""verify: projected vs loaded separation on injected observations
(dispatch 需求4). Q4 never observes HOME itself; the observer is passed in."""
import pytest
from native_helpers import (
    DictProvenance,
    build_snapshot,
    instance_target,
    observed,
    observation,
    revision_provider,
    stdio_revision,
)

from backend.native_intents import (
    FACT_CATALOG_CHANGED,
    FACT_LOADED,
    FACT_PROJECTED,
    FACT_UNKNOWN,
)
from adapters import claude

PROVEN = {"lane": "native", "enforcement": "proven"}


def _plan(expected_digests=None):
    alpha = stdio_revision("def-a", 1, "alpha", "/srv/a")
    beta = stdio_revision("def-b", 1, "beta", "/srv/b")
    snap = build_snapshot([alpha, beta], {"def-a": PROVEN, "def-b": PROVEN})
    provider = revision_provider({(r.definition_id, r.revision): r for r in (alpha, beta)})
    return claude.compile(snap, instance_target("claude"), DictProvenance({}),
                          revision_provider=provider,
                          expected_catalog_digests=expected_digests or {})


def _facts(result):
    return {f.native_name: f for f in result.facts}


def test_runtime_load_attestation_relays_as_loaded():
    plan = _plan()
    result = claude.verify(plan, observation(servers=[
        observed("alpha"), observed("beta")]))
    facts = _facts(result)
    assert facts["alpha"].fact == FACT_LOADED
    assert facts["alpha"].reason == "observer-attested-runtime-load"


def test_config_bytes_match_never_yields_loaded():
    plan = _plan()
    result = claude.verify(plan, observation(servers=[
        observed("alpha", load_state="config-bytes-match"),
        observed("beta", load_state="config-bytes-match"),
    ]))
    facts = _facts(result)
    assert facts["alpha"].fact == FACT_PROJECTED
    assert facts["beta"].fact == FACT_PROJECTED
    assert all(f.fact != FACT_LOADED for f in result.facts)


def test_absent_and_failed_states_are_unknown():
    plan = _plan()
    result = claude.verify(plan, observation(servers=[
        observed("alpha", load_state="absent"),
        observed("beta", load_state="load-failed"),
    ]))
    facts = _facts(result)
    assert facts["alpha"].fact == FACT_UNKNOWN
    assert facts["alpha"].reason == "absent-on-host"
    assert facts["beta"].reason == "load-failed"


def test_missing_observation_is_unknown_not_silence():
    plan = _plan()
    result = claude.verify(plan, observation(servers=[observed("alpha")]))
    facts = _facts(result)
    assert facts["beta"].fact == FACT_UNKNOWN
    assert facts["beta"].reason == "not-observed"


def test_catalog_digest_mismatch_is_catalog_changed():
    plan = _plan({"def-a": "sha256:expected"})
    result = claude.verify(plan, observation(servers=[
        observed("alpha", catalog_digest="sha256:actual")]))
    fact = _facts(result)["alpha"]
    assert fact.fact == FACT_CATALOG_CHANGED
    assert fact.observed_catalog_digest == "sha256:actual"


def test_catalog_digest_match_stays_loaded():
    plan = _plan({"def-a": "sha256:expected"})
    result = claude.verify(plan, observation(servers=[
        observed("alpha", catalog_digest="sha256:expected")]))
    assert _facts(result)["alpha"].fact == FACT_LOADED


def test_expected_catalog_without_observation_is_unknown():
    """catalog empty/unobserved must not be read as loaded (research §8 G2-3
    counterexample)."""
    plan = _plan({"def-a": "sha256:expected"})
    result = claude.verify(plan, observation(servers=[observed("alpha")]))
    fact = _facts(result)["alpha"]
    assert fact.fact == FACT_UNKNOWN
    assert fact.reason == "catalog-not-observed"


def test_instance_identity_mismatch_downgrades_everything():
    plan = _plan()
    result = claude.verify(plan, observation(session_ref="session-B",
                                             servers=[observed("alpha"), observed("beta")]))
    assert result.instance_matched is False
    assert all(f.fact == FACT_UNKNOWN and f.reason == "instance-identity-mismatch"
               for f in result.facts)


def test_transport_mismatch_is_unknown():
    plan = _plan()
    result = claude.verify(plan, observation(servers=[observed("alpha", transport="remote")]))
    fact = _facts(result)["alpha"]
    assert fact.fact == FACT_UNKNOWN
    assert fact.reason == "transport-mismatch"


def test_unplanned_observed_servers_listed_read_only():
    """Native-discovered servers (possible pre-existing user entries) are
    surfaced read-only, never folded into managed facts (harness-adapters:17)."""
    plan = _plan()
    result = claude.verify(plan, observation(servers=[
        observed("alpha"), observed("beta"), observed("user-own-server")]))
    assert result.native_discovered == ("user-own-server",)
    assert "user-own-server" not in {f.native_name for f in result.facts}


def test_verify_is_deterministic():
    plan = _plan()
    obs = observation(servers=[observed("alpha"), observed("beta", load_state="absent")])
    first = claude.verify(plan, obs)
    second = claude.verify(plan, obs)
    assert first.serialize() == second.serialize()

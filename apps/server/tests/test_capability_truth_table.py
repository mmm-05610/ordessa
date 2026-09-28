"""Capability honesty: an ability nobody observed is not a supported ability.

The first version of the unified contract let implementation-level abilities be
promoted from their declaration alone, so a Harness that had never run - and an
execution that had not produced its first delta yet - could both report
`supported=true`. These tests pin the corrected semantics:

    supported == (declared is true and observed is true)

The implementation-level / semantic split survives only as a statement about
*where* an observation may come from and how much evidence the ability needs; it
must never stand in for the observation itself.

Every case here is written against the observable product surfaces, not against
the merge helper alone: the static registry view, the execution-time view and
the profile view all have to tell the same story.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from pacthold_runtime_compat.resource_contracts import harness_capabilities as caps
from ordessa_harness.registry.loader import load_builtin_registry
from ordessa_server_compat.execution import HarnessDescriptor, HarnessRegistry


ALL_TRUE = {capability_id: True for capability_id in caps.CANONICAL_CAPABILITY_IDS}


def by_id(declarations) -> dict[str, dict]:
    """Index either a declaration sequence or a canonical view dict by ability."""
    items = declarations["capabilities"] if isinstance(declarations, dict) else declarations
    result: dict[str, dict] = {}
    for item in items:
        entry = item.as_dict() if hasattr(item, "as_dict") else item
        result[entry["id"]] = entry
    return result


# ---------------------------------------------------------------------------
# the truth table itself
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("observed, expected_supported, expected_reason", [
    (True, True, None),
    (False, False, caps.CAPABILITY_OBSERVED_UNSUPPORTED),
    (None, False, caps.CAPABILITY_NOT_OBSERVED),
])
def test_a_declared_ability_is_supported_only_when_it_was_observed(
    observed, expected_supported, expected_reason,
):
    """`declared + not observed` is not a support claim, whatever the class."""
    for capability_id in caps.CANONICAL_CAPABILITY_IDS:
        entry = by_id(caps.merge_capabilities(
            {capability_id: True}, {capability_id: observed},
        ))[capability_id]
        assert entry["declared"] is True, capability_id
        assert entry["observed"] is observed, capability_id
        assert entry["supported"] is expected_supported, (capability_id, entry)
        assert entry["reason"] == expected_reason, (capability_id, entry)


def test_the_invariant_supported_means_declared_and_observed():
    """The single rule every capability must satisfy, across every combination."""
    for capability_id in caps.CANONICAL_CAPABILITY_IDS:
        for declared in (True, False):
            for observed in (True, False, None):
                entry = by_id(caps.merge_capabilities(
                    {capability_id: declared}, {capability_id: observed},
                ))[capability_id]
                assert entry["supported"] is (declared is True and observed is True), (
                    capability_id, declared, observed, entry)


def test_an_unobserved_implementation_level_ability_is_not_promoted():
    """The specific regression: implementation level must not mean "assume yes"."""
    for capability_id in sorted(caps.IMPLEMENTATION_LEVEL_CAPABILITIES):
        entry = by_id(caps.merge_capabilities({capability_id: True}, {}))[capability_id]
        assert entry["observed"] is None, capability_id
        assert entry["supported"] is False, (capability_id, entry)
        assert entry["reason"] == caps.CAPABILITY_NOT_OBSERVED, (capability_id, entry)


def test_observation_alone_still_cannot_exceed_the_declaration():
    """Fail closed: a runtime advertisement is never a product capability."""
    for capability_id in caps.CANONICAL_CAPABILITY_IDS:
        entry = by_id(caps.merge_capabilities({}, {capability_id: True}))[capability_id]
        assert entry["declared"] is False
        assert entry["supported"] is False
        assert entry["reason"] == caps.CAPABILITY_CONFLICT_OBSERVED_WITHOUT_DECLARATION


# ---------------------------------------------------------------------------
# the product surfaces that were reporting the false positive
# ---------------------------------------------------------------------------

def test_the_registry_static_view_never_reports_unrun_abilities_as_supported():
    """A registry view is a ceiling, not a runtime support claim."""
    registry = HarnessRegistry()
    for definition in load_builtin_registry().all():
        registry.register(HarnessDescriptor(
            definition.harness_type,
            capability_claims={name: True for name in definition.capabilities},
        ))
    for definition in load_builtin_registry().all():
        view = registry.capability_view(definition.harness_type)
        for item in view["capabilities"]:
            assert item["observed"] is None, (definition.harness_type, item)
            assert item["supported"] is False, (definition.harness_type, item)


def test_codex_registry_view_still_reports_no_support_before_a_run():
    """A deployment exists, but the static view is still a ceiling, not a claim."""
    registry = HarnessRegistry()
    definition = load_builtin_registry().get("codex")
    registry.register(HarnessDescriptor(
        "codex", capability_claims={name: True for name in definition.capabilities},
    ))
    view = registry.capability_view("codex")
    assert {item["id"] for item in view["capabilities"]} == set(caps.CANONICAL_CAPABILITY_IDS)
    for item in view["capabilities"]:
        assert item["declared"] is (item["id"] in definition.capabilities)
        assert item["supported"] is False, item
        expected = (caps.CAPABILITY_NOT_OBSERVED if item["declared"]
                    else caps.CAPABILITY_NOT_DECLARED)
        assert item["reason"] == expected, item
    # The plugin now has a production deployment whose gate observed five
    # abilities; the *static* view must still refuse to claim any of them, and
    # the two abilities that never happened stay unobserved too.
    from ordessa_harness.codex import production

    assert production.HAS_PRODUCTION_DEPLOYMENT is True
    assert production.observed_capabilities() == frozenset(
        {"start", "observe", "finish", "stream", "native_continuation"})


def test_the_static_profile_view_still_shows_the_declared_ceiling():
    """Profiles keep their existing shape: `{id: declared}` as a candidate ceiling."""
    registry = HarnessRegistry()
    definition = load_builtin_registry().get("pi")
    registry.register(HarnessDescriptor(
        "pi", capability_claims={name: True for name in definition.capabilities},
    ))
    claims = registry.claims_for("pi")
    assert claims == {name: True for name in definition.capabilities}
    assert all(isinstance(value, bool) for value in claims.values())


def test_the_effective_view_is_read_through_the_port_only_after_operations(tmp_path):
    """Execution-time observation: the real paths, in the real order.

    A deployment that declares the four implementation-level abilities must not
    see any of them supported before the corresponding operation actually
    returned, and the stream must stay unsupported until a delta arrives.
    """
    from ordessa_server_compat.execution.sidecar import LocalProcessLauncher, SidecarHarnessPort

    plugin = Path(__file__).resolve().parents[3] / "plugins"  / "harness"
    state: dict = {}
    observed: list[tuple[str, str, dict]] = []
    port = SidecarHarnessPort(
        LocalProcessLauncher(["node", str(plugin / "runtime" / "worker-entry.mjs")]),
        environment={
            "PATH": __import__("os").environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(tmp_path), "AGENTBOX_SIDECAR_ISOLATED": "1",
        },
        profile="pi",
        adapter={"command": "node",
                 "args": [str(plugin / "tests" / "harness_remote" / "fake_acp_peer.mjs")]},
        declared_capabilities={"start": True, "observe": True, "finish": True, "stream": True},
        state_directory=str(tmp_path / "state"), directory=str(tmp_path),
        on_event=lambda execution_id, kind, payload: observed.append(
            (execution_id, kind, payload)),
    )
    try:
        native = port.open_execution("execution-honesty")
        assert native
        before_delta = by_id(port.effective_capabilities("execution-honesty"))
        assert before_delta["start"]["observed"] is True
        assert before_delta["start"]["supported"] is True
        assert before_delta["observe"]["supported"] is True
        # Nothing has produced output or finished a prompt yet.
        assert before_delta["stream"]["observed"] is None, before_delta["stream"]
        assert before_delta["stream"]["supported"] is False, before_delta["stream"]
        assert before_delta["finish"]["observed"] is None, before_delta["finish"]
        assert before_delta["finish"]["supported"] is False, before_delta["finish"]

        port.prompt("execution-honesty", "capability honesty")
        after = by_id(port.effective_capabilities("execution-honesty"))
        assert after["stream"]["observed"] is True, after["stream"]
        assert after["stream"]["supported"] is True, after["stream"]
        assert after["finish"]["observed"] is True, after["finish"]
        assert after["finish"]["supported"] is True, after["finish"]
        assert any(kind == "message.delta" for _execution, kind, _payload in observed)
        state["checked"] = True
    finally:
        port.stop()
    assert state.get("checked") is True


def test_the_effective_view_never_pre_fills_observations(tmp_path):
    """Fail if anyone answers the honesty problem by inventing observations."""
    from ordessa_server_compat.execution.sidecar import LocalProcessLauncher, SidecarHarnessPort

    plugin = Path(__file__).resolve().parents[3] / "plugins"  / "harness"
    port = SidecarHarnessPort(
        LocalProcessLauncher(["node", str(plugin / "runtime" / "worker-entry.mjs")]),
        environment={
            "PATH": __import__("os").environ.get("PATH", "/usr/bin:/bin"),
            "HOME": str(tmp_path), "AGENTBOX_SIDECAR_ISOLATED": "1",
        },
        profile="pi",
        adapter={"command": "node",
                 "args": [str(plugin / "tests" / "harness_remote" / "fake_acp_peer.mjs")]},
        declared_capabilities=dict(ALL_TRUE),
        state_directory=str(tmp_path / "state"), directory=str(tmp_path),
    )
    try:
        port.open_execution("execution-unobserved")
        view = by_id(port.effective_capabilities("execution-unobserved"))
        # Only what an operation actually produced may be observed.
        assert view["start"]["observed"] is True
        assert view["observe"]["observed"] is True
        for capability_id in ("finish", "stream", "steer", "permissions"):
            assert view[capability_id]["observed"] is None, (capability_id, view[capability_id])
            assert view[capability_id]["supported"] is False, (capability_id, view[capability_id])
    finally:
        port.stop()

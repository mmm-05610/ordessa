"""T04b — composition gate: field-claim conflict at stage time, §C4 lifecycle.

A native config field claimed by the sandbox facet and the Permissions native
projection is refused at stage time (verification.md extra-gate 3), never by a
priority ordering; uninstalling hides the UI region while the stored value
stays readable (FR-08); instances still using the adapter make unload busy.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from _sandbox_backend_helpers import HARNESSES_TOML, claude_intent, codex_intent

from ordessa_sandbox_api import (
    FieldClaimRegistry,
    SandboxApiError,
    SandboxErrorCode,
)
from ordessa_sandbox_backend import (
    SandboxNativeService,
    SandboxOptionCatalogue,
)


@pytest.fixture()
def service():
    catalogue = SandboxOptionCatalogue.from_repo(harnesses_toml=Path(HARNESSES_TOML))
    return SandboxNativeService(catalogue=catalogue)


# ------------------------------------------------------- field-claim conflict

def test_same_field_two_facets_refused_at_stage(service):
    service.stage_facet_claims(
        sandbox_fields=("sandbox_mode",),
        permissions_projection_fields=("permissions.deny",),
    )
    # a later Permissions projection touching the same field is refused now,
    # at stage time, not deferred to a runtime priority fight
    with pytest.raises(SandboxApiError) as exc:
        service.claim_native_field("permissions.native-projection", "sandbox_mode")
    assert exc.value.code is SandboxErrorCode.SANDBOX_CONFIG_CONFLICT


@pytest.mark.parametrize("sandbox_first", [True, False])
def test_conflict_refused_regardless_of_claim_order_is_not_priority(service, sandbox_first):
    # no ordering makes the loser win: both orders refuse. A priority rule
    # would let one of these succeed.
    sandbox = ("sandbox_mode",)
    perms = ("sandbox_mode",)
    order = ((sandbox, perms), (perms, sandbox))[0 if sandbox_first else 1]
    registry = FieldClaimRegistry()
    with pytest.raises(SandboxApiError) as exc:
        service.stage_pair(registry, sandbox_fields=order[0],
                           permissions_fields=order[1])
    assert exc.value.code is SandboxErrorCode.SANDBOX_CONFIG_CONFLICT
    # stage-time refusal is atomic: neither facet ended up owning the field,
    # so there is no "winner by order" that a priority rule would have left
    assert registry.claimed_fields() == ()


def test_disjoint_fields_stage_cleanly(service):
    registry = FieldClaimRegistry()
    service.stage_pair(registry, sandbox_fields=("sandbox_mode", "writable_roots"),
                       permissions_fields=("approval_policy",))
    assert registry.owner_of("sandbox_mode") == service.SANDBOX_ADAPTER_ID
    assert registry.owner_of("approval_policy") == service.PERMISSIONS_ADAPTER_ID
    assert set(registry.claimed_fields()) == {
        "sandbox_mode", "writable_roots", "approval_policy"}


# ------------------------------------------------------------ §C4 busy/unload

def test_busy_counts_active_instances_dependent_on_the_adapter(service):
    service.register_instance("harness-instance-1")
    service.register_instance("harness-instance-2")
    assert service.busy() == 2


def test_unload_refused_while_an_instance_still_uses_the_adapter(service):
    service.register_instance("harness-instance-1")
    with pytest.raises(SandboxApiError) as exc:
        service.unload()
    assert exc.value.code is SandboxErrorCode.PROVIDER_BUSY
    # it did not partially unload: the facet is still there to serve/answer
    assert service.state == "ready"


def test_unload_succeeds_once_dependents_are_released(service):
    service.register_instance("harness-instance-1")
    service.release_instance("harness-instance-1")
    assert service.busy() == 0
    service.unload()
    assert service.state == "unloaded"
    # an unloaded provider defers its queries (§C4: never half-serving)
    with pytest.raises(SandboxApiError) as exc:
        service.describe("codex", "2.0", platform_os="linux")
    assert exc.value.code is SandboxErrorCode.PROVIDER_BUSY


def test_query_while_busy_is_provider_busy(service):
    from ordessa_sandbox_api import SandboxEvidence  # noqa: F401
    service.register_instance("harness-instance-1")
    with pytest.raises(SandboxApiError) as exc:
        service.describe("codex", "2.0", platform_os="linux")
    assert exc.value.code is SandboxErrorCode.PROVIDER_BUSY


# -------------------------------------------- uninstall hides region, keeps data

def test_uninstalled_facet_hidden_from_describe_but_value_retained(service):
    service.repository.save_intent(codex_intent(revision=1))
    # the value is present while installed
    assert service.describe("codex", "2.0", platform_os="linux").region_visible is True
    service.uninstall_facet()
    result = service.describe("codex", "2.0", platform_os="linux")
    assert result.region_visible is False      # UI region disappears
    assert result.options == ()                # nothing offered
    # FR-08: data survives the uninstall and stays readable
    kept = service.repository.get_intent("sbx-codex-1", 1)
    assert kept is not None and kept.brand == "codex"


def test_uninstalled_facet_refuses_a_new_compile_without_forwarding(service):
    service.repository.save_intent(codex_intent(revision=1))
    service.uninstall_facet()
    with pytest.raises(SandboxApiError) as exc:
        service.compile(codex_intent(revision=1))
    assert exc.value.code is SandboxErrorCode.PROVIDER_BUSY
    # "no unknown fragment reaches Harness": compile produced no intent set
    assert service.compiled_intents == []


def test_installed_facet_reappears_and_retained_value_is_still_valid(service):
    service.repository.save_intent(claude_intent(revision=1))
    service.uninstall_facet()
    service.install_facet()
    result = service.describe("claude-code", "0.81.2", platform_os="linux")
    assert result.region_visible is True
    assert service.repository.get_intent("sbx-claude-1", 1) is not None


# ------------------------------------------------------- compile gate (no fake)

def test_compile_only_emits_an_unbound_plan_for_verified_intents(service):
    from _sandbox_backend_helpers import claude_evidence, facts
    from ordessa_sandbox_api import NativeSandboxIntent

    intent = claude_intent(revision=1)
    service.repository.save_intent(intent)
    service.repository.record_evidence("th-codex-s-a", claude_evidence())
    plan = service.compile(intent, facts())
    assert service.compiled_intents == [plan]
    # the plan is a hand-off reference, not a config mutation: it carries the
    # stored id+revision and the target handle, and says its binding is UNBOUND
    assert plan.sandbox_id == "sbx-claude-1" and plan.revision == 1
    assert plan.target_handle == "th-codex-s-a"
    assert "UNBOUND" in plan.binding
    # ...and it never reaches Harness's C3 vocabulary in this package
    assert not any(hasattr(plan, name) for name in
                   ("SetField", "ResetField", "InvokeAction", "field", "action"))


def test_compile_refuses_unverified_intent_without_recording_anything(service):
    from _sandbox_backend_helpers import claude_intent as ci, facts
    with pytest.raises(SandboxApiError) as exc:
        service.compile(ci(revision=2), facts())   # no evidence recorded
    assert exc.value.code is SandboxErrorCode.SANDBOX_EFFECT_UNKNOWN
    assert service.compiled_intents == []

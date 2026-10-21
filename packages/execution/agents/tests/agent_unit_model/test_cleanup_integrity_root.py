"""Required original Usage integrity/owner-retirement counterexamples."""
import json
import pytest
from agent_tools_fixtures.lifecycle import lifecycle
from agent_tools_fixtures.node_publication import setup
from ordessa_units.errors import UnitGuaranteeUnavailable
from ordessa_units.definitions.operations import UsageMutation, operation_holder, node_holder
from ordessa_agents.harness.definitions.activation import HarnessActivationRef
from ordessa_units.bindings.materials import MaterialProviderPin
from ordessa_units.bindings.material_operations import material_provider_ref


@pytest.mark.parametrize("corruption", ["unit-string", "provider-no-use"])
def test_cleanup_requires_real_use_rights_on_original_provider_and_unit(lifecycle, corruption):
    coordinator, owner, provider, node_ref, node, env, store, request, pin, current = lifecycle
    rows = store.read_usages("env", node_holder("env", node_ref.instance_id, node_ref.generation))
    target = next(row for row in rows if
                  ("ownerProviderRef" in row["targetRef"]) == (corruption == "unit-string"))
    rights = "use" if corruption == "unit-string" else ["read"]
    store._conn.execute("UPDATE env_usages SET rights=? WHERE usage_id=?",
                        (json.dumps(rights), target["usageId"]))
    store._conn.commit()
    with pytest.raises(UnitGuaranteeUnavailable):
        coordinator.stop(request, node_ref, {})
    assert store.read_operation(request) is None
    assert provider.lifecycle_calls == []


def test_same_activation_material_provider_hold_blocks_runtime_retirement(setup):
    _, store, env, _, _, pub, request, _, intent, activation = setup
    ref = activation.activation
    holder = operation_holder(request, intent.operation_ref)
    material = material_provider_ref(MaterialProviderPin(
        "material.provider", "material-provider-1", ref))
    pub.reserve(request, "digest", intent, usages=(UsageMutation(
        "same-owner-material", 0, None, holder, material, ("use",), "active"),))
    assert store.read_usages("env", holder)[0]["targetRef"] == material
    state, blockers = env.retire_activation(ref)
    assert state == "retire-pending" and "agent-unit-usage:same-owner-material" in blockers
    assert env.registry_snapshot.agent_runtime_provider_ids == ("fixture.runtime",)

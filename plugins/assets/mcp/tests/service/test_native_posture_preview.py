"""T012 exposure surface: ``mcp.resolvePreview`` answers the effective
snapshot AND the honest native permission postures side by side.

The composition is the real one (``service_helpers.Stack``: real
``ServerPluginHost`` + real ``WireService.dispatch`` + the Q4 plugin); the
only seam added for this order is the composition-injected
``native_posture_facts`` (the harness observation/declaration plane is its
product-assembly producer). The counterexamples the converge pins:

* managed-lane previews carry no posture rows (nobody is mislabelled);
* the posture row coexists with the snapshot's ``enforcement: "unproven"``
  word — one is a display fact, the other the gate input; neither cancels
  the other;
* with no facts injected the row is the unattributed default (policy
  "unknown"), never a fabricated mechanism.

UI presentation is T08-r2 (registered in
specs/011-q4-mcp/reports/t012-t014.md); the wire row exists for it here.
"""
from __future__ import annotations

from service_helpers import Stack, make_client, seed_revision

from backend.managed.lease import LeaseCaller
from backend.plugin import McpAssetServerPlugin
from backend.permissions import (
    POSTURE_PROVENANCE_NATIVE_DECLARED,
    POSTURE_PROVENANCE_UNATTRIBUTED,
)

FACTS = {"demo": {"source": "claude-code native permission rules",
                  "scope": "instance",
                  "policyRef": "claude-settings-2026-09",
                  "provenance": POSTURE_PROVENANCE_NATIVE_DECLARED}}


def _native_stack(tmp_path, *, posture_facts=None):
    plugin = McpAssetServerPlugin(
        client_factory=make_client,
        lane_by_definition={"demo": "native"},
        native_posture_facts=posture_facts)
    stack = Stack(tmp_path, plugin=plugin)
    seed_revision(stack)
    # one live catalog observation, so the enable binds a real digest
    service = stack.host.provided_port("asset.mcp.v2")
    caller = LeaseCaller("alice", "sess-1", 1)
    lease = service.sessions.open_lease(caller=caller, server_scope="s1",
                                        definition_id="demo", revision=1)
    service.sessions.plan_connection(caller=caller, lease_id=lease.lease_id,
                                     submission_id="sub-posture-1")
    service.sessions.start_connection(caller=caller, lease_id=lease.lease_id)
    catalog = service.sessions.observe_catalog(caller=caller,
                                               lease_id=lease.lease_id)
    stack.call("mcp.assign", serverScope="s1", principal="alice",
               scopeKind="user-default", scopeId="alice", definitionId="demo",
               decision="enable", approvedRevision=1,
               toolSelection={"mode": "allowNames", "names": ["read_file"],
                              "catalogDigest": catalog.catalog_digest},
               expectedRowVersion=0, operationKey="op-assign-posture")
    return stack


def _preview(stack):
    return stack.call("mcp.resolvePreview", serverScope="s1", principal="alice",
                      sessionRef="sess-1")


def test_preview_exposes_the_declared_posture_next_to_the_snapshot(tmp_path):
    stack = _native_stack(tmp_path, posture_facts=FACTS)
    preview = _preview(stack)
    lane = preview["snapshot"]["laneByDefinition"]["demo"]
    assert lane == {"lane": "native", "enforcement": "unproven"}
    postures = preview["nativePermissionPostures"]
    assert postures == [{
        "definitionId": "demo",
        "source": "claude-code native permission rules",
        "scope": "instance",
        "policyRef": "claude-settings-2026-09",
        "provenance": POSTURE_PROVENANCE_NATIVE_DECLARED,
        "claimsOrdessaAuthority": False,
    }]
    # coexistence, not substitution: the enforcement word stayed
    assert lane["enforcement"] == "unproven"


def test_preview_without_facts_labels_the_unattributed_default(tmp_path):
    stack = _native_stack(tmp_path)  # no native_posture_facts composed
    postures = _preview(stack)["nativePermissionPostures"]
    assert postures == [{
        "definitionId": "demo", "source": "harness-native",
        "scope": "unknown", "policyRef": "unknown",
        "provenance": POSTURE_PROVENANCE_UNATTRIBUTED,
        "claimsOrdessaAuthority": False,
    }]


def test_counterexample_managed_previews_carry_no_posture_rows(saved):
    """The default composition runs everything on the managed lane; a
    posture there would claim harness-native governance that decides
    nothing. The key exists (the display can rely on it) and stays empty."""
    preview = saved.call("mcp.resolvePreview", serverScope="s1",
                         principal="alice")
    assert preview["nativePermissionPostures"] == []
    assert "snapshot" in preview

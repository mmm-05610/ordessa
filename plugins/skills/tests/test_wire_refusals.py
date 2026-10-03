"""Typed refusals of the registered family, answered through the real host.

Covers the counter-examples the slice is accountable for (verification.md
G02/G03/G05–G09/G16/G20 at the registration edge):

* no client-supplied owner/path/principal — the host's shape wall refuses
  an `sourcePath`-style param before any handler runs, and the import
  protocol refuses absolute declared paths on its own bounds;
* no fabricated workspace — a project-layer write against an unknown
  projectId is refused by the injected registry (G07);
* unapproved revision in `enable` (G06);
* stale `expectedVersion` and the create-guard against an existing row;
* replayed `operationKey` answers with the settled result, not a second
  write;
* profile-layer and native-discovery and invoke surfaces stay honestly
  unavailable (§G2/§G3) instead of silently succeeding;
* `invokeDescriptor` = unknown for all three controlled brands.
"""
from __future__ import annotations

import hashlib

import pytest

from server_plugin_api import WireError

from skills_wire_support import (  # noqa: F811
    dispatch, domain_code, expect_domain_refusal, expect_shape_refusal,
    import_skill, manifest_bytes, open_workspace, runtime)


def test_self_reported_owner_or_path_never_reaches_the_handler(runtime):  # noqa: F811
    """A request may not carry an owner, a principal or a local path: the
    declared shape sets do not contain those words, and the host's own
    dispatch wall refuses the extra param (无自报 owner / 任意本地路径)."""
    forbidden = ("sourcePath", "principal", "owner", "serverScope")
    cases = (
        ("skills.importCommit", {"importId": "import_ghost",
                                 "assetId": "whatever-x", "revision": 1}),
        ("skills.assignmentsUpsert", {"scopeKind": "user_global",
                                      "assetId": "whatever-x",
                                      "decision": "enable", "revision": 1}),
    )
    for method, anchor in cases:
        for name in forbidden:
            with pytest.raises(WireError) as info:
                dispatch(runtime, method, **anchor, **{name: "/home/user/x"})
            assert info.value.family == "INVALID_REQUEST", (method, name)
            assert name in str(info.value.details or "") or \
                name in str(info.value), (method, name)


def test_absolute_declared_import_path_is_refused(runtime):  # noqa: F811
    payload = b"data"
    expect_domain_refusal(
        runtime, "skills.importBegin", "IMPORT_PATH_INVALID",
        files=[{"path": "/etc/passwd", "bytes": len(payload),
                "sha256": "sha256:" + hashlib.sha256(payload).hexdigest()}],
        totalBytes=len(payload))


def test_fabricated_workspace_id_is_refused_not_filtered(runtime):  # noqa: F811
    """G07: the project layer only exists for ids the injected workspace
    registry vouches for; a made-up projectId is a typed refusal BEFORE any
    write, never an empty success."""
    import_skill(runtime, asset_id="proj-skill", revision=1)
    expect_domain_refusal(
        runtime, "skills.assignmentsUpsert", "WORKSPACE_UNKNOWN",
        scopeKind="project", scopeId="ws-fabricated-000",
        assetId="proj-skill", decision="enable", revision=1)
    # and resolution against a fabricated project refuses with the type
    # instead of answering with a silently narrower set (G05).
    expect_domain_refusal(runtime, "skills.resolve", "WORKSPACE_UNKNOWN",
                          projectId="ws-fabricated-000")
    # nothing was written by the refused attempts:
    listed = dispatch(runtime, "skills.assignmentsList", scopeKind="project")
    assert listed["items"] == []


def test_real_workspace_project_assignment_works(runtime, tmp_path):  # noqa: F811
    """Positive control for the refusal above: the only ids that pass are
    ones the workspace plugin itself issued."""
    import_skill(runtime, asset_id="proj-ok", revision=1)
    workspace_id = open_workspace(runtime, tmp_path)
    result = dispatch(runtime, "skills.assignmentsUpsert",
                      scopeKind="project", scopeId=workspace_id,
                      assetId="proj-ok", decision="enable", revision=1,
                      expectedVersion=0)
    assert result["assignment"]["scopeId"] == workspace_id
    view = dispatch(runtime, "skills.resolve", projectId=workspace_id)
    assert [item["assetId"] for item in view["resolvedSkills"]] == ["proj-ok"]


def test_enable_of_unapproved_revision_is_refused(runtime):  # noqa: F811
    """G06/G02: installed is not approved; the approval gate is the write
    guard, and the revision stays visible in the catalogue."""
    import_skill(runtime, asset_id="gated-skill", revision=1, approve=False)
    expect_domain_refusal(
        runtime, "skills.assignmentsUpsert", "SKILL_APPROVAL_MISSING",
        scopeKind="user_global", assetId="gated-skill",
        decision="enable", revision=1)
    # visibility without silence: the catalogue still lists it.
    listing = dispatch(runtime, "skills.list")
    assert "gated-skill" in [item["assetId"] for item in listing["items"]]


def test_stale_expected_version_is_a_typed_conflict(runtime):  # noqa: F811
    import_skill(runtime, asset_id="cas-skill", revision=1)
    dispatch(runtime, "skills.assignmentsUpsert", scopeKind="user_global",
             assetId="cas-skill", decision="enable", revision=1,
             operationKey="op-cas-1")
    # duplicate same-layer assignment with the create guard: the row exists.
    expect_domain_refusal(
        runtime, "skills.assignmentsUpsert", "ASSIGNMENT_VERSION_CONFLICT",
        scopeKind="user_global", assetId="cas-skill",
        decision="enable", revision=1, expectedVersion=0)
    # stale version on an update too.
    expect_domain_refusal(
        runtime, "skills.assignmentsUpsert", "ASSIGNMENT_VERSION_CONFLICT",
        scopeKind="user_global", assetId="cas-skill",
        decision="disable", expectedVersion=99)


def test_replayed_operation_key_returns_the_settled_result(runtime):  # noqa: F811
    """Idempotency via the store's own operation ledger (the host
    `idempotency` port stays host-facing; the domain ledger is this
    slice's adjudication of §G1 — see the report)."""
    import_skill(runtime, asset_id="idem-skill", revision=1)
    first = dispatch(runtime, "skills.assignmentsUpsert",
                     scopeKind="user_global", assetId="idem-skill",
                     decision="enable", revision=1,
                     operationKey="op-idem-1")
    second = dispatch(runtime, "skills.assignmentsUpsert",
                      scopeKind="user_global", assetId="idem-skill",
                      decision="enable", revision=1,
                      operationKey="op-idem-1")
    assert second == first
    # the row version did not move: no second write happened
    assert second["assignment"]["rowVersion"] == 1


def test_missing_required_param_is_refused_by_the_wall(runtime):  # noqa: F811
    expect_shape_refusal(runtime, "skills.get")  # no assetId
    expect_shape_refusal(runtime, "skills.assignmentsUpsert",
                          scopeKind="user_global", assetId="x")  # no decision


def test_value_level_bounds_are_typed(runtime):  # noqa: F811
    expect_domain_refusal(runtime, "skills.get", "INVALID_REQUEST",
                          assetId="Not A Slug!")
    expect_domain_refusal(runtime, "skills.assignmentsUpsert",
                          "INVALID_REQUEST",
                          scopeKind="user_global", assetId="ok-skill",
                          decision="maybe")


def test_profile_layer_refuses_honestly(runtime):  # noqa: F811
    """§G3 open: a profile target is refused with a type; resolutions
    without a profile target still answer (the layer inherits, it is not
    faked disabled)."""
    import_skill(runtime, asset_id="plain-skill", revision=1)
    dispatch(runtime, "skills.assignmentsUpsert", scopeKind="user_global",
             assetId="plain-skill", decision="enable", revision=1)
    ok = dispatch(runtime, "skills.resolve")
    assert [item["assetId"] for item in ok["resolvedSkills"]] == ["plain-skill"]
    expect_domain_refusal(runtime, "skills.resolve",
                          "PROFILE_LAYER_UNAVAILABLE", profileId="p-1")


def test_discover_native_refuses_without_the_harness_seam(runtime):  # noqa: F811
    """§G2: no silent empty list; the refusal names the missing seam."""
    expect_domain_refusal(runtime, "skills.discoverNative",
                          "NATIVE_TARGET_ROOT_UNAVAILABLE",
                          harnessId="claude")


@pytest.mark.parametrize("brand", ["claude", "codex", "pi"])
def test_invoke_descriptor_is_unknown_for_every_brand(runtime, brand):  # noqa: F811
    answer = dispatch(runtime, "skills.invokeDescriptor", harnessId=brand)
    assert answer["invocation"] == "unknown"
    assert answer["browseOnly"] is True
    assert "brand-matrix.md" in answer["citation"]

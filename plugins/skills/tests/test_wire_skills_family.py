"""Happy path of the registered `skills.*` family on the real host (L1).

Drives the full import → preview → approve → assign → resolve cycle through
`runtime.wire.dispatch` only, and pins the G16 edge: digest/assignment
evidence never leaves this service as `loaded` or `used`.
"""
from __future__ import annotations

import pytest

from skills_wire_support import (  # noqa: F401
    blob, dispatch, import_skill, manifest_bytes, runtime)


def test_full_cycle_import_approve_assign_resolve(runtime):  # noqa: F811
    committed = import_skill(runtime, asset_id="demo-skill", revision=1)
    assert committed["effect"] == "stored"
    assert committed["asset"]["assetId"] == "demo-skill"

    # the catalogue sees it; the revision list shows the approval fact.
    listing = dispatch(runtime, "skills.list")
    assert [item["assetId"] for item in listing["items"]] == ["demo-skill"]
    detail = dispatch(runtime, "skills.get", assetId="demo-skill")
    assert detail["kind"] == "skill"

    revisions = dispatch(runtime, "skills.revisions", assetId="demo-skill")
    assert revisions["items"][0]["revision"] == 1
    assert revisions["items"][0]["approvalRecord"]["assetId"] == "demo-skill"

    # assignments: user-global enable of the approved revision, guarded.
    upserted = dispatch(runtime, "skills.assignmentsUpsert",
                        scopeKind="user_global", assetId="demo-skill",
                        decision="enable", revision=1, expectedVersion=0,
                        operationKey="op-cycle-1")
    assert upserted["effect"] == "stored"
    assert upserted["assignment"]["rowVersion"] == 1

    listed = dispatch(runtime, "skills.assignmentsList")
    assert [row["assetId"] for row in listed["items"]] == ["demo-skill"]

    # resolve: provenance + per-item evidence, all read-only.
    view = dispatch(runtime, "skills.resolve")
    included = view["resolvedSkills"]
    assert [item["assetId"] for item in included] == ["demo-skill"]
    item = included[0]
    assert item["revision"] == 1
    assert item["selectedBy"]["layer"] == "user_global_any"
    assert item["treeDigest"].startswith("sha256:")
    assert item["capabilityEvidence"]["effect"] == "selected"

    # previewEffective answers with the SAME resolution (one algorithm).
    preview = dispatch(runtime, "skills.previewEffective")
    assert preview == view

    # preview + diff over a second imported revision.
    import_skill(runtime, asset_id="demo-skill", revision=2,
                 body="Changed body.")
    one = dispatch(runtime, "skills.preview", assetId="demo-skill",
                   revision=1, path="SKILL.md")
    assert "Body revision 1." in one["text"]
    diff = dispatch(runtime, "skills.diff", assetId="demo-skill",
                    fromRevision=1, toRevision=2, path="SKILL.md")
    assert "SKILL.md" in blob(diff), diff
    assert "textDiff" in diff

    # disable at the same layer: the item lands in excluded WITH provenance
    # (the six-state walk keeps disable ≠ never-enabled visible, G06).
    dispatch(runtime, "skills.assignmentsUpsert",
             scopeKind="user_global", assetId="demo-skill",
             decision="disable", expectedVersion=1,
             operationKey="op-cycle-disable-1")
    after_disable = dispatch(runtime, "skills.resolve")
    assert after_disable["resolvedSkills"] == []
    excluded = {row["assetId"]: row for row in after_disable["excludedSkills"]}
    assert "demo-skill" in excluded
    assert excluded["demo-skill"]["excludedBy"]["layer"] == "user_global_any"

    # remove: back to inherit — the asset leaves the excluded set entirely,
    # the other side of the same distinguishability.
    dispatch(runtime, "skills.assignmentsRemove",
             scopeKind="user_global", assetId="demo-skill",
             expectedVersion=2, operationKey="op-cycle-remove-1")
    after = dispatch(runtime, "skills.resolve")
    assert [item["assetId"] for item in after["resolvedSkills"]] == []
    assert {row["assetId"] for row in after["excludedSkills"]} == set()
    assert dispatch(runtime, "skills.assignmentsList")["items"] == []


def test_import_cancel_leaves_no_publish(runtime):  # noqa: F811
    payload = manifest_bytes("ghost-skill", "Never committed.")
    begun = dispatch(runtime, "skills.importBegin",
                     files=[{"path": "SKILL.md", "bytes": len(payload),
                              "sha256": _sha(payload)}],
                     totalBytes=len(payload))
    dispatch(runtime, "skills.importCancel", importId=begun["importId"])
    listing = dispatch(runtime, "skills.list")
    assert listing["items"] == []


def _sha(payload: bytes) -> str:
    import hashlib
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def test_g16_digest_only_evidence_never_leaves_loaded_or_used(runtime):  # noqa: F811
    """G16 at the service edge: the wire answers of skills.list and resolve
    cannot contain the two levels nothing here proves."""
    import_skill(runtime, asset_id="quiet-skill", revision=1)
    dispatch(runtime, "skills.assignmentsUpsert",
             scopeKind="user_global", assetId="quiet-skill",
             decision="enable", revision=1)

    for method, params in (("skills.list", {}), ("skills.resolve", {}),
                           ("skills.previewEffective", {})):
        answer = blob(dispatch(runtime, method, **params))
        assert '"loaded"' not in answer, f"{method} claimed a load level"
        assert '"used"' not in answer, f"{method} claimed an invocation"
    # and the control: the selection level IS visible (not filtered), so the
    # assertions above are not green because the answer was empty.
    resolution = blob(dispatch(runtime, "skills.resolve"))
    assert '"selected"' in resolution


def test_resolve_is_projection_free_and_reads_nothing_foreign(runtime):  # noqa: F811
    """unknown capability must stay visible (G05/G10): with no harness
    statement the capability axes answer `unknown`, never a filtered-out
    item."""
    import_skill(runtime, asset_id="visible-skill", revision=1)
    dispatch(runtime, "skills.assignmentsUpsert",
             scopeKind="user_global", harnessId="brand-new",
             assetId="visible-skill", decision="enable", revision=1)
    view = dispatch(runtime, "skills.resolve", harnessId="brand-new")
    assert [item["assetId"] for item in view["resolvedSkills"]] == [
        "visible-skill"]
    evidence = view["resolvedSkills"][0]["capabilityEvidence"]
    assert evidence["effect"] == "selected"
    assert evidence["discovery"] == "unknown"

"""N5 single-resource closed loop (spec 021 night contract): one synthetic
skill walks the REAL chain in one stack — install+approve (storage) → sparse
Profile selection through the published facet API → the ONE shared resolver →
the Harness-facing ``agent-box.skill@1`` delivery set — over an isolated data
root, with the project-disable, A/B session, system-level, no-Profile and
not-installed edges proven on the same wiring the product composition uses
(``SkillsService(profile_services=...)`` derives ``ProfileApiLayerPort`` the
same way). Zero model calls; the harness side is the published contract value
and its documented consumer leg, never a live agent.

Not claimed here: native in-session loading evidence (the spec pins the
delivery grade at ``projected``), the default-release composition question
(registered in docs/known-issues.md), and any live brand behaviour.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
for _module, _src in (("ordessa_profile", REPO_ROOT / "plugins" / "profile" / "src"),
                      ("pacthold_runtime_compat",
                       REPO_ROOT / "plugins" / "runtime-compat" / "src")):
    if (importlib.util.find_spec(_module) is None
            and _src.is_dir() and str(_src) not in sys.path):
        sys.path.append(str(_src))

from assignments_support import (  # noqa: E402
    FakeWorkspaceLookup, make_database, make_skill,
)
from ordessa_harness.registry.loader import load_builtin_registry  # noqa: E402

from ordessa_skills.assignments.model import (  # noqa: E402
    DECISION_DISABLE, DECISION_ENABLE, SCOPE_PROJECT, SCOPE_USER_GLOBAL,
)
from ordessa_skills.assignments.ports import SessionOverride  # noqa: E402
from ordessa_skills.harness_adapters.producer import (  # noqa: E402
    SkillDeliveryError, build_skill_delivery,
)
from ordessa_skills.plugin import PLUGIN_ID  # noqa: E402
from ordessa_skills.profile_contribution import (  # noqa: E402
    FACET_ID, ProfileApiLayerPort, decision_value, register_skills_facet,
)
from ordessa_skills.service import SkillsService  # noqa: E402


def _profile_services(tmp_path):
    from ordessa_profile.core import ProfileCore, StaticHarnessCatalog
    from ordessa_profile.plugin import ProfilePluginServices
    core = ProfileCore(
        str(tmp_path / "profile-store.sqlite"),
        harnesses=StaticHarnessCatalog({"pi": frozenset(), "codex": frozenset()}))
    return ProfilePluginServices(core)


@pytest.fixture()
def loop(tmp_path):
    """The real product wiring: one SkillsService whose fifth resolver layer
    is derived from the real profile-api services (the composition path),
    over one isolated data root with two approved synthetic skills."""
    services = _profile_services(tmp_path)
    register_skills_facet(services, owner_plugin_id=PLUGIN_ID,
                          asset_ids=lambda: ["demo-skill", "beta-skill"])
    database = make_database(tmp_path)
    service = SkillsService(database=database,
                            assets_root=tmp_path / "assets",
                            server_scope="srv-test", principal="user-1",
                            workspace_lookup=FakeWorkspaceLookup(("proj-a", "proj-b")),
                            profile_services=services)
    service.ensure_schema()
    facts = {}
    for asset in ("demo-skill", "beta-skill"):
        facts[asset] = make_skill(tmp_path, database=database,
                                  asset_id=asset, revision=1)
    profile = services.core.profiles.create("ka", harness_id="pi",
                                            display_name="Agent A")
    pid = profile["profile_id"]
    # The sparse Profile selection: exactly one skill enabled at a pinned
    # revision; the other has no Profile row (inherit = absence).
    services.core.profiles.set_facet_values(
        "f1", profile_id=pid, expected_version=1,
        values=[{"facet_id": FACET_ID, "item_id": "demo-skill",
                 "value": decision_value(1)}])
    return {"service": service, "services": services, "profile_id": pid,
            "facts": facts}


def _resolved(service, **kwargs):
    view = service.resolve(**kwargs)
    return {item["assetId"]: item for item in view["resolvedSkills"]}


def _delivered(service, **kwargs):
    # the composition reads the brand definition from the published harness
    # registry the same way; without it the delivery refuses (no hardcoded
    # cardinality), so the loop must carry the real fact.
    value = service.delivery_set(
        harness_definition=load_builtin_registry().get("pi"), **kwargs)
    items = value.resolved_inputs()
    return value, {item.value.contract.name: item for item in items}


# -- the loop: registration -> sparse Profile pick -> resolve -> harness facet


def test_profile_sparse_pick_reaches_resolution_and_the_harness_facet(loop):
    service, pid = loop["service"], loop["profile_id"]
    target = dict(project_id="proj-a", harness_id="pi", profile_id=pid,
                  session_ref="s-a", runtime_generation=1)
    resolved = _resolved(service, **target, session_overrides=())
    assert set(resolved) == {"demo-skill"}
    # provenance names the Profile layer, never a silent default
    assert resolved["demo-skill"]["selectedBy"]["layer"] == "profile"
    assert resolved["demo-skill"]["selectedBy"]["harnessId"] == "pi"
    value, by_name = _delivered(service, **target, session_overrides=())
    assert set(by_name) == {"demo-skill"}
    item = by_name["demo-skill"]
    # the consumer leg shape the harness reads (generic_cli.py:20-38)
    assert item.contract_id == "agent-box.skill@1"
    contract = item.value.contract
    assert contract.name == "demo-skill"
    digest = service.store.revision_digest(asset_id="demo-skill", revision=1)
    assert contract.digest == digest
    assert item.value.source.projection_source() == \
        service.store.revision_dir("demo-skill", 1)
    assert contract.description == \
        loop["facts"]["demo-skill"]["facts"]["description"]


def test_project_disable_excludes_without_leaking_to_the_other_project(loop):
    """Layer semantics (resolver docstring): the profile layer sits ABOVE the
    project layers, so its enable cannot be undone per project; a skill whose
    Profile row is absent (inherit) is decided by the lower layers — that is
    the per-project exclusion edge, and it never leaks across projects."""
    service, pid = loop["service"], loop["profile_id"]
    # system-level (user-global) selection for beta; no Profile row for it
    service.assignments.upsert(scope_kind=SCOPE_USER_GLOBAL, scope_id=None,
                               harness_id=None, asset_id="beta-skill",
                               decision=DECISION_ENABLE, revision=1,
                               operation_key="n5-system-beta")
    service.assignments.upsert(scope_kind=SCOPE_PROJECT, scope_id="proj-a",
                               harness_id=None, asset_id="beta-skill",
                               decision=DECISION_DISABLE, revision=None,
                               operation_key="n5-disable-a")
    proj_a = dict(project_id="proj-a", harness_id="pi", profile_id=pid,
                  session_ref="s-a", runtime_generation=1, session_overrides=())
    proj_b = dict(proj_a, project_id="proj-b")
    resolved_a = _resolved(service, **proj_a)
    resolved_b = _resolved(service, **proj_b)
    assert set(resolved_a) == {"demo-skill"}  # profile pick stays
    assert set(resolved_b) == {"demo-skill", "beta-skill"}
    excluded = next(item for item in service.resolve(**proj_a)["excludedSkills"]
                    if item["assetId"] == "beta-skill")
    assert excluded["excludedBy"]["layer"] == "project_any"
    _value_a, by_name_a = _delivered(service, **proj_a)
    assert set(by_name_a) == {"demo-skill"}  # beta is not injected here
    _value_b, by_name_b = _delivered(service, **proj_b)
    assert set(by_name_b) == {"demo-skill", "beta-skill"}


def test_session_overrides_alternate_without_cross_contamination(loop):
    service, pid = loop["service"], loop["profile_id"]
    base = dict(project_id="proj-a", harness_id="pi", profile_id=pid,
                runtime_generation=1)
    keep = _resolved(service, session_ref="s-a", **base,
                     session_overrides=())
    drop = _resolved(service, session_ref="s-b", **base,
                     session_overrides=(SessionOverride(
                         asset_id="demo-skill", decision="disable",
                         revision=None),))
    assert set(keep) == {"demo-skill"} and drop == {}
    # alternating back: the override is per-commit, never written anywhere
    assert set(_resolved(service, session_ref="s-a", **base,
                         session_overrides=())) == {"demo-skill"}


def test_without_profile_the_native_selection_still_delivers(tmp_path):
    """No Profile composed: the default port stays a typed layer absence and
    the system-level (user-global) selection delivers on its own — the
    native configuration does not depend on Profile."""
    database = make_database(tmp_path)
    service = SkillsService(database=database,
                            assets_root=tmp_path / "assets",
                            server_scope="srv-test", principal="user-1",
                            workspace_lookup=FakeWorkspaceLookup(("proj-a",)))
    service.ensure_schema()
    make_skill(tmp_path, database=database, asset_id="beta-skill", revision=1)
    service.assignments.upsert(scope_kind=SCOPE_USER_GLOBAL, scope_id=None,
                               harness_id=None, asset_id="beta-skill",
                               decision=DECISION_ENABLE, revision=1,
                               operation_key="n5-native")
    target = dict(project_id="proj-a", harness_id="pi", profile_id=None,
                  session_ref="s-a", runtime_generation=1,
                  session_overrides=())
    assert set(_resolved(service, **target)) == {"beta-skill"}
    _value, by_name = _delivered(service, **target)
    assert set(by_name) == {"beta-skill"}


def test_not_installed_revision_refuses_delivery_with_zero_objects(loop):
    """Uninstalled content referenced by a resolution can never grade as a
    delivery: the typed refusal hands out zero objects (cleanup edge)."""
    from ordessa_skills.assignments.snapshot import SkillSnapshot
    service = loop["service"]
    snap = SkillSnapshot(
        target_session="s-a", runtime_generation=1, project_id="proj-a",
        profile_revision=None, assignment_revisions={},
        resolved_skills=({"assetId": "demo-skill", "revision": 99,
                          "treeDigest": "sha256:" + "a" * 64},),
        snapshot_digest="sha256:" + "0" * 64)
    with pytest.raises(SkillDeliveryError) as refused:
        build_skill_delivery(snapshot=snap, store=service.store,
                             approvals=service.approvals, harness_id="pi",
                             harness_definition=load_builtin_registry().get("pi"))
    assert refused.value.code == "SKILL_DELIVERY_NOT_INSTALLED"

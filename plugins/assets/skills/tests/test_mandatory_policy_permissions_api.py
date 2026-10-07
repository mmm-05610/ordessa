"""The mandatory policy layer at the REAL permissions-api boundary.

Every rule here is produced by the published surface and nothing else:

* the administrator ceiling object is `ordessa_permissions_api.PolicyCeiling`
  (`plugins/permissions/api/src/ordessa_permissions_api/ceilings.py:156`),
  built by its own `from_record` (ceilings.py:172), which is the only way a
  ceiling exists at all (untrusted provenance raises);
* the store is the published backend `PolicyRepository`
  (`plugins/permissions/backend/src/ordessa_permissions_backend/policies.py:91`)
  over the product `pacthold_runtime_compat.storage.Database`, whose
  `read()`/`transaction()` pair satisfies the backend's `ApprovalDatabase`
  protocol (`_store.py:27-32`) — the same object the skills tests already use
  for their own tables, so one database holds both authorities and neither is
  faked;
* the service object handed to the plugin in the wiring test is the published
  `Authorizer` built exactly the way the backend plugin builds it
  (`plugin.py:147-149`, ceiling_provider=`policies.ceilings_current`).

NO Q1-OWNED FAKE carries a mandatory rule in this file. The only stand-ins are
the pre-existing `FakeProfileLayer` (Z1's facet, tests/assignments_support.py)
and the lower-layer assignment rows, because those are the layers under test —
the point of the G06 counter-example 「管理员强制规则被覆盖」 is precisely that
the *policy* side is real while the overridable sides push against it.
"""
from __future__ import annotations

import pytest

from assignments_support import (
    PRINCIPAL,
    SERVER_SCOPE,
    FakeProfileLayer,
    FakeWorkspaceLookup,
    make_database,
    make_skill,
    make_store,
)
from ordessa_permissions_api import PolicyCeiling
from ordessa_permissions_backend import ApprovalFacts, Authorizer, PolicyRepository
from ordessa_skills.api.errors import AssetDomainError
from ordessa_skills.assignments.authorization import AssetAuthorization
from ordessa_skills.assignments.model import (
    AssignmentError,
    DECISION_DISABLE,
    DECISION_ENABLE,
    LAYER_MANDATORY,
    SCOPE_USER_GLOBAL,
)
from ordessa_skills.assignments.ports import (
    ProfileSkillEntry,
    SessionOverride,
)
from ordessa_skills.assignments.resolver import (
    ResolverDeps,
    ResolutionTarget,
    SkillsResolutionService,
)
from ordessa_skills.mandatory_policy import (
    MANDATORY_POLICY_CONFLICT,
    MANDATORY_POLICY_UNAVAILABLE,
    NotConfiguredMandatoryPolicyPort,
    PermissionsCeilingMandatoryPolicyPort,
)
from ordessa_skills.service import SkillsService

ASSETS = ("skill-forbidden", "skill-allowed")
EFFECTIVE_FROM = "2026-01-01T00:00:00+00:00"


def ceiling_record(**overrides):
    """A trusted admin ceiling in the API's own record spelling
    (ceilings.py:32-34 `_RECORD_FIELDS`)."""
    record = {
        "policyId": "q1-mandatory",
        "scope": "admin",
        "revision": 1,
        "source": "signed-admin",
        "signed": True,
        "deny": [{"key": "skill", "pattern": "skill-forbidden*"}],
        "requireApproval": [],
        "maximumExposure": "full",
        "effectiveFrom": EFFECTIVE_FROM,
    }
    record.update(overrides)
    return record


@pytest.fixture
def env(tmp_path):
    """Real DB, real skills, real ceiling store."""
    database = make_database(tmp_path)
    made = {}
    for asset_id in ASSETS:
        made[asset_id] = make_skill(tmp_path, database=database,
                                   asset_id=asset_id, revision=1)
        make_skill(tmp_path, database=database, asset_id=asset_id, revision=2)
    store = make_store(database, approvals=made["skill-forbidden"]["approvals"])
    policies = PolicyRepository(database)
    policies.ensure_schema()
    return {"database": database, "assets": made, "store": store,
            "assets_root": tmp_path / "assets",
            "approvals": made["skill-forbidden"]["approvals"],
            "revisions": made["skill-forbidden"]["store"],
            "policies": policies}


def port_for(env, *records):
    """The adapter over the published repository (its `ceilings_current` is
    the very call the backend authorizer is wired on, plugin.py:148)."""
    for record in records:
        env["policies"].store_ceiling_record(record)
    return PermissionsCeilingMandatoryPolicyPort(
        ceiling_source=env["policies"],
        asset_id_source=lambda: list(ASSETS))


def service_for(env, *, profile=None, mandatory=None):
    deps = ResolverDeps(
        assignments=env["store"],
        revisions=env["revisions"],
        approvals=env["approvals"],
        authorization=AssetAuthorization(
            workspace_lookup=FakeWorkspaceLookup(("proj-a",)),
            server_scope=SERVER_SCOPE),
        profile=profile,
        mandatory=mandatory,
    )
    return SkillsResolutionService(deps)


def target(**kwargs):
    base = dict(project_id="proj-a", harness_id="pi", session_ref="s1")
    base.update(kwargs)
    return ResolutionTarget(**base)


def state_of(view):
    merged = {item["assetId"]: ("included", item)
              for item in view["resolvedSkills"]}
    merged.update({item["assetId"]: ("excluded", item)
                   for item in view["excludedSkills"]})
    return merged


# -- G06 at the real boundary ------------------------------------------------------

def test_real_ceiling_denial_survives_project_profile_and_session_enable(env):
    """The administrator ceiling disables a skill; every overridable layer
    says enable — the seventh layer wins because it is not a layer."""
    port = port_for(env, ceiling_record())
    assert [rule.asset_id for rule in port.rules(
        principal=PRINCIPAL, project_id="proj-a", harness_id="pi")] == \
        ["skill-forbidden"]
    assert all(rule.decision == DECISION_DISABLE for rule in port.rules(
        principal=PRINCIPAL, project_id="proj-a", harness_id="pi"))

    store = env["store"]
    store.upsert(scope_kind=SCOPE_USER_GLOBAL, asset_id="skill-forbidden",
                 decision=DECISION_ENABLE, revision=1)
    store.upsert(scope_kind="project", scope_id="proj-a",
                 asset_id="skill-forbidden", decision=DECISION_ENABLE,
                 revision=1)
    profile = FakeProfileLayer(harness="pi", entries=[
        ProfileSkillEntry("skill-forbidden", "enable", 2)])
    service = service_for(env, profile=profile, mandatory=port)

    view = service.preview_effective(target(
        profile_id="profile_a",
        session_overrides=(SessionOverride("skill-forbidden",
                                           DECISION_ENABLE, 2),)))
    kind, row = state_of(view)["skill-forbidden"]
    assert kind == "excluded"                            # 管理员强制规则未被打断
    assert row["excludedBy"]["layer"] == LAYER_MANDATORY
    # the pattern is bounded: the sibling skill is untouched by the ceiling
    store.upsert(scope_kind=SCOPE_USER_GLOBAL, asset_id="skill-allowed",
                 decision=DECISION_ENABLE, revision=1)
    view2 = service.preview_effective(target(profile_id="profile_a"))
    assert state_of(view2)["skill-allowed"][0] == "included"
    assert any(d["kind"] == "mandatory_policy_applied" and
               d["assetId"] == "skill-forbidden" for d in view2["diagnostics"])


def test_ceiling_read_through_the_published_api_types_is_not_reimplemented(env):
    """The rules come from `PolicyCeiling` objects the API itself produced —
    proof that Skills reads the surface rather than a re-spelled table."""
    port = port_for(env, ceiling_record())
    ceilings = env["policies"].ceilings_current()      # the published read
    assert all(isinstance(item, PolicyCeiling) for item in ceilings)
    assert ceilings[0].is_trusted
    assert port.rules(principal=PRINCIPAL, project_id="proj-a",
                      harness_id="pi")  # a MandatoryRule, not a ceiling object
    assert port.layer_status() == {
        "status": "consulted",
        "source": "ordessa_permissions_api.PolicyCeiling",
        "ceilings": ["q1-mandatory@1"],
        "principal": "data-root principal",
        "scopeDimensionsNotExpressed": ["project_id", "harness_id",
                                       "rule revision pin"],
    }


def test_maximum_exposure_below_skill_exposure_denies_every_skill(env):
    """The allow-max face of the same authority: TOOL_EXPOSURE maps `skill`
    to EXEC (ceilings.py:78), so a WRITE ceiling bounds every enable."""
    port = port_for(env, ceiling_record(deny=[], maximumExposure="write"))
    assert sorted(rule.asset_id for rule in port.rules(
        principal=PRINCIPAL, project_id=None, harness_id=None)) == sorted(ASSETS)
    service = service_for(env, mandatory=port)
    env["store"].upsert(scope_kind=SCOPE_USER_GLOBAL, asset_id="skill-allowed",
                        decision=DECISION_ENABLE, revision=1)
    view = service.preview_effective(target())
    assert state_of(view)["skill-allowed"][0] == "excluded"
    assert state_of(view)["skill-allowed"][1]["excludedBy"]["layer"] == \
        LAYER_MANDATORY


# -- what the published surface does NOT say ----------------------------------------

def test_require_approval_is_reflected_never_turned_into_a_disable(env):
    """An approval-required entry is an execution-time constraint; Skills has
    no authority to spend it, so it must not become a fake content decision."""
    port = port_for(env, ceiling_record(
        deny=[], requireApproval=[{"key": "skill", "pattern": "skill-forbidden*"}]))
    assert port.rules(principal=PRINCIPAL, project_id="proj-a",
                      harness_id="pi") == ()
    constraints = port.approval_required(principal=PRINCIPAL, project_id="proj-a",
                                         harness_id="pi")
    assert [item["assetId"] for item in constraints] == ["skill-forbidden"]
    assert constraints[0]["policyId"] == "q1-mandatory"

    env["store"].upsert(scope_kind=SCOPE_USER_GLOBAL, asset_id="skill-forbidden",
                        decision=DECISION_ENABLE, revision=1)
    view = service_for(env, mandatory=port).preview_effective(target())
    assert state_of(view)["skill-forbidden"][0] == "included"
    assert any(d["kind"] == "mandatory_approval_required" and
               d["assetId"] == "skill-forbidden" for d in view["diagnostics"])


def test_project_and_harness_dimensions_have_no_ceiling_vocabulary(env):
    """Honest gap, pinned so a reader cannot mistake it for scoping:
    `PolicyCeiling` carries no project/harness field and a project-scope
    record is not trusted as a ceiling at all (ceilings.py:38, :227)."""
    port = port_for(env, ceiling_record())
    first = port.rules(principal=PRINCIPAL, project_id="proj-a", harness_id="pi")
    other = port.rules(principal=PRINCIPAL, project_id="proj-b", harness_id="codex")
    assert [rule.asset_id for rule in first] == [rule.asset_id for rule in other]
    assert "project_id" in port.scope_dimensions_not_expressed
    assert "harness_id" in port.scope_dimensions_not_expressed


# -- (b) a contradicting assignment is refused with a type ---------------------------

def test_enable_contradicting_a_real_ceiling_is_refused_before_the_write(env):
    port = port_for(env, ceiling_record())
    service = SkillsService(
        database=env["database"], assets_root=env["assets_root"],
        server_scope=SERVER_SCOPE, principal=PRINCIPAL,
        workspace_lookup=FakeWorkspaceLookup(("proj-a",)),
        mandatory_policy=port)
    with pytest.raises(AssetDomainError) as info:
        service.upsert_assignment(
            scope_kind=SCOPE_USER_GLOBAL, scope_id="", harness_id=None,
            asset_id="skill-forbidden", decision=DECISION_ENABLE, revision=1,
            expected_version=None, operation_key=None)
    assert info.value.code == MANDATORY_POLICY_CONFLICT
    # nothing was half-written: the refused row is not in the store
    assert service.assignments.list(asset_id="skill-forbidden") == []
    # the compliant move (honour the denial) is accepted and says it was checked
    stored = service.upsert_assignment(
        scope_kind=SCOPE_USER_GLOBAL, scope_id="", harness_id=None,
        asset_id="skill-forbidden", decision=DECISION_DISABLE, revision=None,
        expected_version=None, operation_key=None)
    assert stored["mandatoryPolicy"]["checked"] is True
    assert stored["mandatoryPolicy"]["mandatoryDecisionForAsset"] == "disable"
    assert stored["mandatoryPolicy"]["ceilings"] == ["q1-mandatory@1"]


# -- (c) absence and outage stay typed ----------------------------------------------

def test_absent_mandatory_layer_is_typed_visible_not_everything_allowed(tmp_path):
    database = make_database(tmp_path)
    make_skill(tmp_path, database=database, asset_id="skill-allowed",
               revision=1)
    service = SkillsService(
        database=database, assets_root=tmp_path / "assets",
        server_scope=SERVER_SCOPE, principal=PRINCIPAL,
        workspace_lookup=FakeWorkspaceLookup(()))
    service.ensure_schema()
    # the default is an explicitly unreadable layer, never a missing one
    assert service.mandatory_policy.layer_status()["status"] == "unavailable"
    view = service.resolve(project_id=None, harness_id="pi", profile_id=None,
                           session_ref="s1", runtime_generation=1,
                           session_overrides=())
    assert any(d["kind"] == "mandatory_policy_unavailable" and
               d["reason"] for d in view["diagnostics"])
    written = service.upsert_assignment(
        scope_kind=SCOPE_USER_GLOBAL, scope_id="", harness_id=None,
        asset_id="skill-allowed", decision=DECISION_ENABLE, revision=1,
        expected_version=None, operation_key=None)
    assert written["mandatoryPolicy"]["status"] == "unavailable"
    assert written["mandatoryPolicy"]["checked"] is False
    assert written["mandatoryPolicy"]["reason"] == \
        NotConfiguredMandatoryPolicyPort().unavailable_reason
    # the write itself still happened (a composition without permissions-api
    # is this tree's documented state) — but it is recorded as NOT CHECKED, so
    # no consumer can read the success as "compliant with policy"
    assert len(service.assignments.list(asset_id="skill-allowed")) == 1


def test_untrusted_ceiling_provenance_refuses_the_read(env):
    """A record that is not admin/user-signed is not a mandatory rule — and
    Skills says so rather than downgrading it to "no limit" (ceilings.py:224)."""
    port = PermissionsCeilingMandatoryPolicyPort(
        ceiling_source=lambda: [PolicyCeiling.unverified("q1-fake")],
        asset_id_source=lambda: list(ASSETS))
    with pytest.raises(AssetDomainError) as info:
        port.rules(principal=PRINCIPAL, project_id=None, harness_id=None)
    assert info.value.code == MANDATORY_POLICY_UNAVAILABLE
    assert "POLICY_SCOPE_UNVERIFIED" in info.value.message
    assert "q1-fake" in str(info.value.detail)


def test_ceiling_source_outage_is_a_typed_refusal_not_an_empty_layer(env):
    def broken():
        raise RuntimeError("the approval database is locked")

    port = PermissionsCeilingMandatoryPolicyPort(
        ceiling_source=broken, asset_id_source=lambda: list(ASSETS))
    with pytest.raises(AssetDomainError) as info:
        port.rules(principal=PRINCIPAL, project_id=None, harness_id=None)
    assert info.value.code == MANDATORY_POLICY_UNAVAILABLE
    # and the resolver propagates it: a resolution is never answered with the
    # six layers alone while the seventh could not be read
    service = service_for(env, mandatory=port)
    with pytest.raises(AssetDomainError) as raised:
        service.preview_effective(target())
    assert raised.value.code == MANDATORY_POLICY_UNAVAILABLE


# -- plugin preference ---------------------------------------------------------------

def test_plugin_prefers_the_real_permissions_authorizer(env):
    """`SkillsServerPlugin(permissions=...)` binds the published service
    object; with no surface it binds the typed unavailable default."""
    from ordessa_skills.plugin import SkillsServerPlugin

    authorizer = Authorizer(facts=ApprovalFacts(env["database"]),
                            policies=env["policies"],
                            ceiling_provider=env["policies"].ceilings_current)
    env["policies"].store_ceiling_record(ceiling_record())
    plugin = SkillsServerPlugin(permissions=authorizer)
    port = plugin._resolve_mandatory_policy({}, asset_id_source=lambda: list(ASSETS))
    assert isinstance(port, PermissionsCeilingMandatoryPolicyPort)
    assert [rule.asset_id for rule in port.rules(
        principal=PRINCIPAL, project_id=None, harness_id=None)] == ["skill-forbidden"]

    bare = SkillsServerPlugin()
    default = bare._resolve_mandatory_policy({}, asset_id_source=lambda: [])
    assert isinstance(default, NotConfiguredMandatoryPolicyPort)
    assert default.unavailable_reason


def test_a_supplied_surface_that_names_no_ceiling_read_is_reported(env):
    """An injected object with no published ceiling call is not silently
    accepted as "the layer is empty"."""
    from ordessa_skills.mandatory_policy import coerce_ceiling_source

    with pytest.raises(AssetDomainError) as info:
        coerce_ceiling_source(object())
    assert info.value.code == MANDATORY_POLICY_UNAVAILABLE


def test_two_mandatory_rules_for_one_asset_refuse_the_write(tmp_path):
    """The service's guard against an unreadable policy SET (the resolver has
    the same rule, ASSIGNMENT_DUPLICATE). This is a SHAPE probe of the guard,
    not a policy source: the real adapter dedupes by construction, so no
    ceiling it produced can reach this branch."""
    from ordessa_skills.assignments.ports import MandatoryRule

    class DoubledRules:
        unavailable_reason = None

        def layer_status(self):
            return {"status": "consulted", "source": "shape probe"}

        def rules(self, *, principal, project_id, harness_id):
            return (MandatoryRule("skill-allowed", "disable"),
                    MandatoryRule("skill-allowed", "disable"))

    database = make_database(tmp_path)
    make_skill(tmp_path, database=database, asset_id="skill-allowed", revision=1)
    service = SkillsService(
        database=database, assets_root=tmp_path / "assets",
        server_scope=SERVER_SCOPE, principal=PRINCIPAL,
        mandatory_policy=DoubledRules())
    service.ensure_schema()
    with pytest.raises(AssignmentError) as info:
        service.upsert_assignment(
            scope_kind=SCOPE_USER_GLOBAL, scope_id="", harness_id=None,
            asset_id="skill-allowed", decision=DECISION_DISABLE, revision=None,
            expected_version=None, operation_key=None)
    assert info.value.code == "ASSIGNMENT_DUPLICATE"

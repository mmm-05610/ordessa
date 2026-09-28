"""T04 / FR03+FR04+FR10, G07/G08/G09: the one deterministic resolver."""
from __future__ import annotations

import dataclasses

import pytest

from ordessa_assets_subagents import ceiling as ceiling_mod
from ordessa_assets_subagents import dto, errors, limits, resolution
from ordessa_assets_subagents.assignments import Assignment, AssignmentDecision
from ordessa_assets_subagents.references import ReferenceResolution
from ordessa_assets_subagents.resolution import (
    UNKNOWN,
    DefinitionSnapshot,
    ExcludedDefinition,
    NativeDefinitionObservation,
    ResolvedDefinition,
    ResolutionRequest,
    build_snapshot,
    inspect_native,
    resolve_preview,
)
from ordessa_assets_subagents.scopes import (
    DefinitionOwnership,
    Principal,
    ProfileId,
    ProjectId,
    ScopeKind,
    ServerScope,
    SessionId,
)

U1 = Principal("u1")
U2 = Principal("u2")
SCOPE = ServerScope("s1")
PROJ_A = ProjectId("proj-a")
DIGEST = "sha256:" + "c" * 64


class Approvals:
    def __init__(self, approved: set[tuple[str, int]]) -> None:
        self._approved = set(approved)

    def has_approved_revision(self, definition_id: str, revision: int) -> bool:
        return (definition_id, revision) in self._approved


def asg(definition_id: str, kind: ScopeKind, *, scope_id: str | None = None,
        decision: AssignmentDecision = AssignmentDecision.ENABLE,
        revision: int | None = 1, harness: str = "any",
        principal: Principal = U1, row_version: int = 1) -> Assignment:
    return Assignment(
        server_scope=SCOPE, principal=principal, scope_kind=kind,
        scope_id=scope_id, harness_id=harness, definition_id=definition_id,
        decision=decision, revision=revision, row_version=row_version,
    )


def defn(definition_id: str, *, slug: str | None = None,
         description: str = "", origin_scope: str = "public",
         origin_owner: str = "u1", latest: int = 1) -> dto.AgentDefinition:
    return dto.AgentDefinition(
        server_scope="s1", definition_id=definition_id,
        slug=slug or definition_id, display_name=definition_id,
        description=description, origin_scope=origin_scope,
        origin_owner=origin_owner, latest_revision=latest,
    )


def own(definition_id: str, *, origin_scope: str = "public",
        origin_owner: str = "u1", principal: Principal = U1) -> DefinitionOwnership:
    return DefinitionOwnership(definition_id, SCOPE, principal, origin_scope,
                               origin_owner)


def rev(definition_id: str, revision: int = 1, **kw) -> dto.DefinitionRevision:
    return dto.DefinitionRevision(definition_id=definition_id, revision=revision,
                                  content_digest=DIGEST, role_body="body", **kw)


def make_request(**overrides) -> ResolutionRequest:
    base = dict(
        server_scope=SCOPE,
        principal=U1,
        harness_id="claude",
        project_id=PROJ_A,
        profile_id=None,
        session_id=SessionId("sess-1"),
        session_profile_id=None,
        session_harness_id=None,
        definitions={},
        ownership={},
        revisions={},
        assignments=[],
        managed_definition_ids=frozenset(),
        native_observations=None,
        ceiling=ceiling_mod.Ceiling(principal=U1, server_scope=SCOPE,
                                    harness_id="claude"),
    )
    base.update(overrides)
    return ResolutionRequest(**base)


def simple_request(**overrides):
    """One public definition d1@1 enabled at the user-global layer."""
    base = dict(
        definitions={"d1": defn("d1")},
        ownership={"d1": own("d1")},
        revisions={("d1", 1): rev("d1", 1)},
        assignments=[asg("d1", ScopeKind.USER_GLOBAL)],
        managed_definition_ids=frozenset({"d1"}),
    )
    base.update(overrides)
    return make_request(**base)


def resolve(request: ResolutionRequest):
    return resolve_preview(request, approvals=Approvals({("d1", 1), ("d2", 1),
                                                         ("d1", 2), ("d1", 3),
                                                         ("d2", 2)}))


class TestDeterministicLayering:
    def test_higher_layer_overrides_lower(self) -> None:
        request = simple_request(
            assignments=[
                asg("d1", ScopeKind.USER_GLOBAL, revision=1),
                asg("d1", ScopeKind.PROJECT, scope_id="proj-a", revision=2),
                asg("d1", ScopeKind.SESSION, scope_id="sess-1", revision=3),
            ],
            revisions={("d1", 1): rev("d1", 1), ("d1", 2): rev("d1", 2),
                       ("d1", 3): rev("d1", 3)},
        )
        effective = resolve(request)
        assert len(effective.resolved) == 1
        item = effective.resolved[0]
        assert item.revision == 3
        assert item.selected_by is ScopeKind.SESSION

    def test_inherit_is_absence_not_a_reset(self) -> None:
        request = simple_request(
            assignments=[
                asg("d1", ScopeKind.USER_GLOBAL, revision=1),
                asg("d1", ScopeKind.PROJECT, scope_id="proj-a",
                    decision=AssignmentDecision.INHERIT, revision=None),
            ],
        )
        effective = resolve(request)
        assert [item.revision for item in effective.resolved] == [1]

    def test_all_six_layer_kinds_are_ordered(self) -> None:
        kinds = [k for k in ScopeKind]
        assert kinds.index(ScopeKind.USER_GLOBAL) < kinds.index(
            ScopeKind.USER_GLOBAL_HARNESS) < kinds.index(ScopeKind.PROJECT) < \
            kinds.index(ScopeKind.PROJECT_HARNESS) < kinds.index(ScopeKind.PROFILE) < \
            kinds.index(ScopeKind.SESSION)

    def test_same_layer_twice_is_a_conflict_not_a_lottery(self) -> None:
        request = simple_request(
            assignments=[
                asg("d1", ScopeKind.USER_GLOBAL, revision=1),
                asg("d1", ScopeKind.USER_GLOBAL, revision=2),
            ],
        )
        with pytest.raises(errors.DomainError) as exc:
            resolve(request)
        assert exc.value.code == errors.ASSIGNMENT_CONFLICT

    def test_input_order_cannot_change_the_result(self) -> None:
        forward = simple_request(
            assignments=[
                asg("d1", ScopeKind.USER_GLOBAL, revision=1),
                asg("d1", ScopeKind.SESSION, scope_id="sess-1", revision=2),
            ],
            revisions={("d1", 1): rev("d1", 1), ("d1", 2): rev("d1", 2)},
        )
        backward = dataclasses.replace(forward, assignments=list(
            reversed(forward.assignments)))
        assert resolve(forward) == resolve(backward)


class TestScopeIsolation:
    def test_project_b_assignment_never_applies_under_project_a(self) -> None:
        request = make_request(
            definitions={"d2": defn("d2", origin_scope="project",
                                    origin_owner="proj-b")},
            ownership={"d2": own("d2", origin_scope="project",
                                 origin_owner="proj-b")},
            revisions={("d2", 1): rev("d2", 1)},
            assignments=[asg("d2", ScopeKind.PROJECT, scope_id="proj-b")],
        )
        effective = resolve_preview(request, approvals=Approvals({("d2", 1)}))
        assert effective.resolved == ()
        assert len(effective.excluded) == 1
        assert effective.excluded[0].definition_id == "d2"

    def test_foreign_principal_is_invisible_without_any_record(self) -> None:
        request = make_request(
            definitions={"dx": defn("dx", origin_owner="u2")},
            ownership={"dx": own("dx", origin_owner="u2", principal=U2)},
            revisions={("dx", 1): rev("dx", 1)},
            assignments=[asg("dx", ScopeKind.USER_GLOBAL, principal=U2)],
        )
        effective = resolve_preview(request, approvals=Approvals({("dx", 1)}))
        assert effective.resolved == ()
        assert effective.excluded == ()

    def test_profile_def_only_resolves_for_its_profile(self) -> None:
        base = dict(
            definitions={"dp": defn("dp", origin_scope="profile",
                                    origin_owner="pf1")},
            ownership={"dp": own("dp", origin_scope="profile",
                                 origin_owner="pf1")},
            revisions={("dp", 1): rev("dp", 1)},
            assignments=[asg("dp", ScopeKind.USER_GLOBAL)],
        )
        wrong = resolve_preview(
            make_request(profile_id=ProfileId("pf2"), **base),
            approvals=Approvals({("dp", 1)}),
        )
        assert wrong.resolved == ()
        right = resolve_preview(
            make_request(profile_id=ProfileId("pf1"), **base),
            approvals=Approvals({("dp", 1)}),
        )
        assert [item.definition_id for item in right.resolved] == ["dp"]

    def test_profile_def_via_session_needs_same_harness_proof(self) -> None:
        base = dict(
            definitions={"dp": defn("dp", origin_scope="profile",
                                    origin_owner="pf1")},
            ownership={"dp": own("dp", origin_scope="profile",
                                 origin_owner="pf1")},
            revisions={("dp", 1): rev("dp", 1)},
            assignments=[asg("dp", ScopeKind.USER_GLOBAL)],
        )
        same = resolve_preview(
            make_request(session_profile_id=ProfileId("pf1"),
                         session_harness_id="claude", **base),
            approvals=Approvals({("dp", 1)}),
        )
        assert len(same.resolved) == 1
        foreign = resolve_preview(
            make_request(session_profile_id=ProfileId("pf1"),
                         session_harness_id="codex", **base),
            approvals=Approvals({("dp", 1)}),
        )
        assert foreign.resolved == ()

    def test_foreign_brand_assignment_is_not_picked_up(self) -> None:
        request = simple_request(
            assignments=[asg("d1", ScopeKind.USER_GLOBAL, harness="codex")],
        )
        effective = resolve(request)
        assert effective.resolved == ()

    def test_any_assignment_layer_keeps_the_targets_brand(self) -> None:
        request = simple_request(
            assignments=[asg("d1", ScopeKind.USER_GLOBAL, harness="any")],
        )
        effective = resolve(request)
        assert request.harness_id == "claude"
        assert len(effective.resolved) == 1


class TestPinsAndFailClosed:
    def test_pin_resolves_to_pinned_revision_not_latest(self) -> None:
        request = simple_request(
            definitions={"d1": defn("d1", latest=5)},
            assignments=[asg("d1", ScopeKind.USER_GLOBAL, revision=1)],
        )
        effective = resolve(request)
        assert effective.resolved[0].revision == 1

    def test_unapproved_pin_is_refused(self) -> None:
        request = simple_request(
            assignments=[asg("d1", ScopeKind.USER_GLOBAL, revision=2)],
        )
        with pytest.raises(errors.DomainError) as exc:
            resolve_preview(request, approvals=Approvals(set()))
        assert exc.value.code == errors.ASSIGNMENT_CONFLICT

    def test_missing_pinned_revision_body_fails_closed_before_apply(self) -> None:
        request = simple_request(revisions={})
        with pytest.raises(errors.DomainError) as exc:
            resolve(request)
        assert exc.value.code == errors.REVISION_STALE

    def test_ceiling_none_refuses_rather_than_defaulting_permissive(self) -> None:
        request = simple_request(ceiling=None)
        with pytest.raises(errors.DomainError) as exc:
            resolve(request)
        assert exc.value.code == errors.ADAPTER_MISSING

    def test_nothing_selected_does_not_need_a_ceiling(self) -> None:
        request = make_request(ceiling=None)
        effective = resolve(request)
        assert effective.resolved == ()

    def test_over_ceiling_definition_is_refused_with_field_name(self) -> None:
        request = simple_request(
            revisions={("d1", 1): rev("d1", 1, tool_refs=(dto.ToolRef("Bash"),))},
        )
        with pytest.raises(errors.DomainError) as exc:
            resolve(request)
        assert exc.value.code == errors.PERMISSION_EXCEEDS_CEILING
        assert "toolRefs" in exc.value.item_id

    def test_unresolvable_reference_refuses_the_runtime_path(self) -> None:
        request = simple_request(
            revisions={("d1", 1): rev("d1", 1, tool_refs=(dto.ToolRef("t1"),))},
            ceiling=ceiling_mod.Ceiling(
                principal=U1, server_scope=SCOPE, harness_id="claude",
                allowed_tools=frozenset({"t1"})),
        )
        with pytest.raises(errors.DomainError) as exc:
            resolve(request)
        assert exc.value.code == errors.REFERENCE_UNRESOLVED
        assert exc.value.item_id == "tool:t1"


class TestNameConflictsAndCaps:
    def test_two_definitions_one_native_name_rejects_both(self) -> None:
        request = make_request(
            definitions={"d1": defn("d1", slug="twin"),
                         "d2": defn("d2", slug="twin")},
            ownership={"d1": own("d1"), "d2": own("d2")},
            revisions={("d1", 1): rev("d1", 1), ("d2", 1): rev("d2", 1)},
            assignments=[asg("d1", ScopeKind.USER_GLOBAL),
                         asg("d2", ScopeKind.USER_GLOBAL)],
        )
        effective = resolve(request)
        assert effective.resolved == ()
        assert {e.reason_code for e in effective.excluded} == {
            errors.NATIVE_NAME_CONFLICT}
        assert len(effective.excluded) == 2

    def test_collision_with_a_native_discovery_rejects_the_manager(self) -> None:
        request = simple_request(
            definitions={"d1": defn("d1", slug="helper")},
            native_observations=[NativeDefinitionObservation(
                native_name="helper", scope="project", source_category="native")],
        )
        effective = resolve(request)
        assert effective.resolved == ()
        assert effective.excluded[0].reason_code == errors.NATIVE_NAME_CONFLICT

    def test_reserved_native_name_is_refused(self) -> None:
        request = simple_request(definitions={"d1": defn("d1", slug="main")})
        effective = resolve(request)
        assert effective.resolved == ()
        assert "reserved" in effective.excluded[0].detail

    def test_enabled_count_cap_refuses_before_apply(self) -> None:
        n = limits.MAX_ENABLED_DEFINITIONS + 1
        request = make_request(
            definitions={f"d{i}": defn(f"d{i}") for i in range(n)},
            ownership={f"d{i}": own(f"d{i}") for i in range(n)},
            revisions={(f"d{i}", 1): rev(f"d{i}", 1) for i in range(n)},
            assignments=[asg(f"d{i}", ScopeKind.USER_GLOBAL) for i in range(n)],
        )
        approvals = Approvals({(f"d{i}", 1) for i in range(n)})
        with pytest.raises(errors.DomainError) as exc:
            resolve_preview(request, approvals=approvals)
        assert exc.value.code == errors.DEFINITION_INVALID
        assert "cap" in exc.value.detail

    def test_aggregate_description_cap_refuses_before_apply(self) -> None:
        n = 64
        size = limits.MAX_AGGREGATE_DESCRIPTION_BYTES // n + 1
        request = make_request(
            definitions={f"d{i}": defn(f"d{i}", description="x" * size)
                         for i in range(n)},
            ownership={f"d{i}": own(f"d{i}") for i in range(n)},
            revisions={(f"d{i}", 1): rev(f"d{i}", 1) for i in range(n)},
            assignments=[asg(f"d{i}", ScopeKind.USER_GLOBAL) for i in range(n)],
        )
        approvals = Approvals({(f"d{i}", 1) for i in range(n)})
        with pytest.raises(errors.DomainError) as exc:
            resolve_preview(request, approvals=approvals)
        assert exc.value.code == errors.DEFINITION_INVALID
        assert "description" in exc.value.detail


class TestHonestDisable:
    def test_disable_of_managed_item_excludes_with_reason(self) -> None:
        request = simple_request(
            assignments=[
                asg("d1", ScopeKind.USER_GLOBAL),
                asg("d1", ScopeKind.SESSION, scope_id="sess-1",
                    decision=AssignmentDecision.DISABLE, revision=None),
            ],
        )
        effective = resolve(request)
        assert effective.resolved == ()
        assert effective.excluded[0].reason_code == "disabled"

    def test_disable_of_native_item_is_reported_not_faked(self) -> None:
        request = simple_request(
            managed_definition_ids=frozenset(),
            assignments=[
                asg("d1", ScopeKind.USER_GLOBAL),
                asg("d1", ScopeKind.SESSION, scope_id="sess-1",
                    decision=AssignmentDecision.DISABLE, revision=None),
            ],
        )
        effective = resolve(request)
        assert effective.resolved == ()
        assert effective.excluded[0].reason_code == errors.NATIVE_DISCOVERY_UNCONTROLLED
        assert "still visible" in effective.excluded[0].detail


class TestUnknownVsEmpty:
    def test_missing_probe_is_unknown_not_empty(self) -> None:
        missing = inspect_native(None)
        looked = inspect_native([])
        assert missing is UNKNOWN
        assert looked == ()
        assert missing != looked
        assert not isinstance(missing, tuple)

    def test_observation_suppression_fact_stays_tri_state(self) -> None:
        observation = NativeDefinitionObservation(
            native_name="n", scope="user", source_category="native")
        assert observation.suppressible is None


class TestSnapshot:
    def snapshot(self, request=None):
        request = request or simple_request()
        effective = resolve(request)
        return build_snapshot(
            request, effective, approvals=Approvals({("d1", 1)}),
            runtime_generation="rt-1", profile_revision=3,
            adapter_generation="ad-1",
        )

    def test_snapshot_pins_every_layer_of_the_freeze(self) -> None:
        snap = self.snapshot()
        assert isinstance(snap, DefinitionSnapshot)
        assert snap.principal == "u1"
        assert snap.runtime_generation == "rt-1"
        assert snap.profile_revision == 3
        assert snap.adapter_generation == "ad-1"
        assert snap.definition_digests == (("d1", 1, DIGEST),)
        assert snap.assignment_revisions == (("user_global::d1", 1),)
        assert snap.snapshot_digest.startswith("sha256:")

    def test_same_data_same_digest_changed_pin_differs(self) -> None:
        assert self.snapshot().snapshot_digest == self.snapshot().snapshot_digest
        bumped = simple_request(
            assignments=[asg("d1", ScopeKind.USER_GLOBAL, row_version=2)])
        assert self.snapshot(bumped).snapshot_digest != self.snapshot().snapshot_digest

    def test_snapshot_is_immutable(self) -> None:
        snap = self.snapshot()
        with pytest.raises(dataclasses.FrozenInstanceError):
            snap.runtime_generation = "other"

    def test_missing_pinned_revision_refuses_before_any_freeze(self) -> None:
        request = simple_request()
        broken = resolution.EffectiveSet(
            resolved=(ResolvedDefinition(
                definition_id="d9", revision=7, native_name="d9",
                selected_by=ScopeKind.USER_GLOBAL,
                effective_references=ReferenceResolution((), ()),
                capability_evidence=(), diagnostics=()),),
            excluded=(),
        )
        with pytest.raises(errors.DomainError) as exc:
            build_snapshot(request, broken, approvals=Approvals({("d1", 1)}),
                           runtime_generation="rt", profile_revision=1,
                           adapter_generation="ad")
        assert exc.value.code == errors.REVISION_STALE

    def test_effective_set_internal_disagreement_refuses(self) -> None:
        request = simple_request()
        effective = resolve(request)
        disagreeing = resolution.EffectiveSet(
            resolved=effective.resolved,
            excluded=effective.excluded + (
                ExcludedDefinition("d1", "disabled", "contradicts the selection"),),
        )
        with pytest.raises(errors.DomainError) as exc:
            build_snapshot(request, disagreeing, approvals=Approvals({("d1", 1)}),
                           runtime_generation="rt", profile_revision=1,
                           adapter_generation="ad")
        assert exc.value.code == errors.REVISION_STALE


class TestSingleSourceOfTruth:
    def test_two_consumers_of_the_same_request_get_the_same_answer(self) -> None:
        request = simple_request()
        assert resolve(request) == resolve(request)

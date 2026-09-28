"""T04 / G07-G08: server-verified scope, ownership, no existence leaks."""
from __future__ import annotations

import pytest

from ordessa_assets_subagents import errors
from ordessa_assets_subagents.scopes import (
    NOT_FOUND,
    AuthorizationContext,
    DefinitionOwnership,
    Principal,
    ProfileId,
    ProjectId,
    ScopeKind,
    ServerScope,
    SessionId,
    ViewerScope,
    harness_binding_matches,
    profile_definition_usable,
    scoped_read,
    visible_definition_ids,
)

U1 = Principal("u1")
U2 = Principal("u2")
SCOPE = ServerScope("s1")


def viewer(**overrides) -> ViewerScope:
    base = dict(
        principal=U1,
        server_scope=SCOPE,
        project=ProjectId("proj-a"),
        profile_id=None,
        session_id=None,
        session_profile_id=None,
        session_harness_id=None,
        harness_id="claude",
    )
    base.update(overrides)
    return ViewerScope(**base)


class TestServerVerifiedProject:
    def test_client_project_claim_without_verification_is_refused(self) -> None:
        ctx = AuthorizationContext.issued_by_service(U1, SCOPE, None)
        with pytest.raises(errors.DomainError) as exc:
            ctx.require_project("proj-a")
        assert exc.value.code == errors.PERMISSION_EXCEEDS_CEILING

    def test_claim_of_another_project_is_refused(self) -> None:
        ctx = AuthorizationContext.issued_by_service(U1, SCOPE, ProjectId("proj-b"))
        with pytest.raises(errors.DomainError) as exc:
            ctx.require_project("proj-a")
        assert exc.value.code == errors.PERMISSION_EXCEEDS_CEILING

    def test_verified_project_is_echoed_back_not_the_claim(self) -> None:
        ctx = AuthorizationContext.issued_by_service(U1, SCOPE, ProjectId("proj-a"))
        assert ctx.require_project("proj-a") is ctx.verified_project

    def test_no_claim_needs_no_verification(self) -> None:
        ctx = AuthorizationContext.issued_by_service(U1, SCOPE, None)
        assert ctx.require_project(None) is None


class TestNoExistenceLeak:
    def test_foreign_read_is_the_same_sentinel_as_missing(self) -> None:
        foreign = DefinitionOwnership("d9", SCOPE, U2, "public", "u2")
        assert scoped_read(foreign, viewer()) is NOT_FOUND
        assert scoped_read(None, viewer()) is NOT_FOUND
        assert scoped_read(foreign, viewer()) is scoped_read(None, viewer())

    def test_not_found_carries_no_distinguishable_marker(self) -> None:
        assert not hasattr(NOT_FOUND, "definition_id")
        assert not hasattr(NOT_FOUND, "hidden")

    def test_visible_ids_hide_foreign_without_a_reason(self) -> None:
        own = DefinitionOwnership("d1", SCOPE, U1, "public", "u1")
        foreign = DefinitionOwnership("d9", SCOPE, U2, "public", "u2")
        viewable, hidden = visible_definition_ids({"d1": own, "d9": foreign}, viewer())
        assert viewable == frozenset({"d1"})
        assert hidden == ()

    def test_own_out_of_scope_def_gets_a_reportable_reason(self) -> None:
        other_project = DefinitionOwnership("d2", SCOPE, U1, "project", "proj-b")
        viewable, hidden = visible_definition_ids({"d2": other_project}, viewer())
        assert viewable == frozenset()
        assert len(hidden) == 1 and hidden[0].code == errors.ASSIGNMENT_CONFLICT


class TestProjectAndProfileOwnership:
    def test_project_def_never_crosses_projects(self) -> None:
        in_a = viewer()
        in_b = viewer(project=ProjectId("proj-b"))
        own = DefinitionOwnership("d1", SCOPE, U1, "project", "proj-a")
        assert scoped_read(own, in_a) is own
        assert scoped_read(own, in_b) is NOT_FOUND

    def test_project_def_without_verified_project_is_invisible(self) -> None:
        own = DefinitionOwnership("d1", SCOPE, U1, "project", "proj-a")
        assert scoped_read(own, viewer(project=None)) is NOT_FOUND

    def test_profile_def_serves_only_its_profile(self) -> None:
        assert profile_definition_usable(
            origin_owner_profile_id="pf1",
            viewer=viewer(profile_id=ProfileId("pf1")),
        )
        assert not profile_definition_usable(
            origin_owner_profile_id="pf1",
            viewer=viewer(profile_id=ProfileId("pf2")),
        )

    def test_profile_def_session_route_requires_same_harness(self) -> None:
        legit = viewer(session_profile_id=ProfileId("pf1"), session_harness_id="claude")
        assert profile_definition_usable(origin_owner_profile_id="pf1", viewer=legit)
        foreign_brand = viewer(
            session_profile_id=ProfileId("pf1"), session_harness_id="codex"
        )
        assert not profile_definition_usable(
            origin_owner_profile_id="pf1", viewer=foreign_brand
        )
        unproven = viewer(session_profile_id=ProfileId("pf1"), session_harness_id=None)
        assert not profile_definition_usable(
            origin_owner_profile_id="pf1", viewer=unproven
        )


class TestHarnessBindingBrands:
    def test_foreign_brand_assignment_never_matches(self) -> None:
        assert not harness_binding_matches(
            target_harness_id="claude", assignment_harness_id="codex"
        )

    def test_any_binding_matches_without_changing_brand(self) -> None:
        assert harness_binding_matches(
            target_harness_id="claude", assignment_harness_id="any"
        )
        assert harness_binding_matches(
            target_harness_id="claude", assignment_harness_id="claude"
        )

    def test_blank_brand_is_not_a_wildcard(self) -> None:
        assert not harness_binding_matches(
            target_harness_id="claude", assignment_harness_id=""
        )


class TestIdentifierValidation:
    def test_empty_principal_is_refused(self) -> None:
        with pytest.raises(errors.DomainError):
            Principal("")

    def test_oversized_principal_is_refused(self) -> None:
        with pytest.raises(errors.DomainError):
            Principal("x" * 129)

    def test_layer_order_is_the_data_model_layering(self) -> None:
        assert [kind.value for kind in ScopeKind] == [
            "user_global", "user_global_harness", "project", "project_harness",
            "profile", "session",
        ]

    def test_session_id_wrappers_still_validate(self) -> None:
        with pytest.raises(errors.DomainError):
            SessionId("")

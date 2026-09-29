"""SR-14: the two §C1/§C5 service-face gaps, closed and made load-bearing.

Gap 1 (§C1 "读操作按公共、项目、Profile 专用归属过滤，不泄露他人存在性"):
`DefinitionService` reads take a keyword-only `viewer` issued ONLY by
`authorize_viewer` (same attested principal + server scope + server-verified
project/Profile/session binding mutations use). A foreign row — another
principal's, another project's, or a profile-origin row outside its own
profile/sessions (G08) — reads back byte-identical to an absent row: the one
`scopes.scoped_read` / `scopes.visible_definition_ids` rule, never a copy.

Gap 2 (§C5 "未知结果必须可查询，不得回退为静默成功"): `operation_status`
re-reads the caller's own idempotency receipt (action + principal-scoped
target + operation key) without synthesising success, and another
principal's receipt is indistinguishable from a receipt that never existed.

The legacy `viewer=None` reads are the pinned in-process seam (module
docstring of service.py): unchanged here, and these tests pin that a
`viewer`-carrying read can never widen to it.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from conftest import (
    OTHER_PRINCIPAL,
    PRINCIPAL,
    SERVER_SCOPE,
    FakeAuthority,
    approval,
    make_revision,
    publish,
)

from ordessa_assets_subagents import dto, errors, scopes
from ordessa_assets_subagents.service import DefinitionService
from ordessa_assets_subagents.store import DefinitionStore


class AttestingAuthority:
    """A FakeAuthority plus the optional read-binding attestations (G07/G08)."""

    def __init__(self, *, principals=(PRINCIPAL, OTHER_PRINCIPAL), projects=(),
                 profiles=(), sessions=()) -> None:
        self.principals = set(principals)
        self.projects = set(projects)
        self.profiles = set(profiles)
        self.sessions = set(sessions)

    def verify_principal(self, principal: str, *, server_scope: str) -> bool:
        return principal in self.principals

    def permission_ceiling(self, principal: str, server_scope: str) -> frozenset:
        return frozenset({"read-only"}) if principal in self.principals else frozenset()

    def verify_project(self, principal: str, *, server_scope: str,
                       project_id: str) -> bool:
        return (principal, server_scope, project_id) in self.projects

    def verify_profile(self, principal: str, *, server_scope: str,
                       profile_id: str) -> bool:
        return (principal, server_scope, profile_id) in self.profiles

    def verify_session(self, principal: str, *, server_scope: str, session_id: str,
                       profile_id: str | None, session_harness_id: str | None,
                       harness_id: str) -> bool:
        return (principal, server_scope, session_id, profile_id,
                session_harness_id, harness_id) in self.sessions


def create(service: DefinitionService, principal: str, *, slug: str,
           origin_scope: str = "public", origin_owner: str = "local",
           key: str | None = None) -> dto.AgentDefinition:
    return service.create_definition(
        principal, server_scope=SERVER_SCOPE, slug=slug,
        display_name=slug.replace("-", " ").title(),
        description=f"The {slug} definition, read-only.",
        origin_scope=origin_scope, origin_owner=origin_owner,
        operation_key=key or f"{principal}:create:{slug}",
    )


def failure(action) -> tuple:
    try:
        action()
    except errors.DomainError as exc:
        return (exc.code, exc.item_id, exc.detail)
    raise AssertionError("expected a typed DomainError refusal")


def absent_shape(definition_id: str) -> tuple:
    return ("DEFINITION_INVALID", definition_id, "no such definition")


def revision_shape(definition_id: str, revision: int) -> tuple:
    return ("DEFINITION_INVALID", f"{definition_id}@{revision}", "no such revision")


# -- the viewer authorization path ------------------------------------------


class TestViewerIssuance:
    def test_an_unattested_principal_cannot_name_a_viewer(
        self, store: DefinitionStore
    ) -> None:
        service = DefinitionService(store, authority=FakeAuthority())
        assert failure(
            lambda: service.authorize_viewer("u:stranger", SERVER_SCOPE)
        )[0] == "PERMISSION_EXCEEDS_CEILING"

    def test_a_client_constructed_viewer_is_refused(
        self, store: DefinitionStore
    ) -> None:
        authority = FakeAuthority()
        service = DefinitionService(store, authority=authority)
        definition = create(service, PRINCIPAL, slug="own-one")
        forged = scopes.ViewerScope(
            principal=scopes.Principal(PRINCIPAL),
            server_scope=scopes.ServerScope(SERVER_SCOPE),
            project=None, profile_id=None, session_id=None,
            session_profile_id=None, session_harness_id=None,
            harness_id=scopes.ANY_HARNESS,
        )
        # not issued anywhere: a viewer is a capability, not a shape
        assert failure(
            lambda: service.get_definition(definition.definition_id, viewer=forged)
        )[0] == "PERMISSION_EXCEEDS_CEILING"
        # even one stamped by a different service instance is refused here
        other = DefinitionService(
            DefinitionStore(Path(store.root) / "other-root"), authority=authority
        )
        borrowed = other.authorize_viewer(PRINCIPAL, SERVER_SCOPE)
        assert failure(
            lambda: service.get_definition(definition.definition_id, viewer=borrowed)
        )[0] == "PERMISSION_EXCEEDS_CEILING"

    def test_an_authority_without_project_attestation_fails_closed(
        self, store: DefinitionStore
    ) -> None:
        service = DefinitionService(store, authority=FakeAuthority())
        # FakeAuthority cannot attest a project, so the claim is refused
        # before any lookup — never silently narrowed to "no project".
        assert failure(
            lambda: service.authorize_viewer(
                PRINCIPAL, SERVER_SCOPE, project_id="proj-a"
            )
        )[0] == "PERMISSION_EXCEEDS_CEILING"

    def test_an_unverified_project_claim_is_refused(
        self, store: DefinitionStore
    ) -> None:
        authority = AttestingAuthority(projects={(PRINCIPAL, SERVER_SCOPE, "proj-a")})
        service = DefinitionService(store, authority=authority)
        assert service.authorize_viewer(
            PRINCIPAL, SERVER_SCOPE, project_id="proj-a"
        ) is not None
        assert failure(
            lambda: service.authorize_viewer(
                PRINCIPAL, SERVER_SCOPE, project_id="proj-b"
            )
        )[:1] == ("PERMISSION_EXCEEDS_CEILING",)


# -- §C1 ownership-filtered reads -------------------------------------------


class TestOwnershipFilteredReads:
    def test_a_foreign_definition_reads_identical_to_absent(
        self, store: DefinitionStore
    ) -> None:
        service = DefinitionService(store, authority=FakeAuthority())
        mine = create(service, PRINCIPAL, slug="mine")
        theirs = create(service, OTHER_PRINCIPAL, slug="theirs")
        viewer = service.authorize_viewer(PRINCIPAL, SERVER_SCOPE)
        assert service.get_definition(mine.definition_id, viewer=viewer) == mine
        hidden = failure(
            lambda: service.get_definition(theirs.definition_id, viewer=viewer)
        )
        absent = failure(
            lambda: service.get_definition("def_absent000000000000000000",
                                           viewer=viewer)
        )
        # same code, same echoed item, same wording: no "hidden exists" signal
        assert hidden == absent_shape(theirs.definition_id)
        assert absent == absent_shape("def_absent000000000000000000")
        assert hidden[0] == absent[0] and hidden[2] == absent[2]
        for word in ("hidden", "foreign", "exists", "other principal"):
            assert word not in hidden[2]

    def test_list_hides_other_principals_without_a_signal(
        self, store: DefinitionStore
    ) -> None:
        service = DefinitionService(store, authority=FakeAuthority())
        mine = create(service, PRINCIPAL, slug="mine")
        theirs = create(service, OTHER_PRINCIPAL, slug="theirs")
        archived = service.archive(OTHER_PRINCIPAL, theirs.definition_id,
                                   server_scope=SERVER_SCOPE, operation_key="o:arch",
                                   expected_row_version=theirs.row_version)
        assert archived.archived
        viewer = service.authorize_viewer(PRINCIPAL, SERVER_SCOPE)
        other_viewer = service.authorize_viewer(OTHER_PRINCIPAL, SERVER_SCOPE)
        assert [row.slug for row in service.list_definitions(viewer=viewer)] == ["mine"]
        # include_archived must not widen past ownership: the archived
        # foreign row stays as absent as it was while active
        assert [
            row.slug for row in
            service.list_definitions(include_archived=True, viewer=viewer)
        ] == ["mine"]
        assert [
            row.slug for row in
            service.list_definitions(include_archived=True, viewer=other_viewer)
        ] == ["theirs"]
        # the legacy no-viewer seam is unchanged (pinned by wire/apply callers)
        assert [
            row.slug for row in service.list_definitions(include_archived=True)
        ] == ["mine", "theirs"]
        assert mine.server_scope == SERVER_SCOPE

    def test_a_project_definition_is_visible_only_inside_its_project(
        self, store: DefinitionStore
    ) -> None:
        authority = AttestingAuthority(projects={
            (PRINCIPAL, SERVER_SCOPE, "proj-a"), (PRINCIPAL, SERVER_SCOPE, "proj-b"),
        })
        service = DefinitionService(store, authority=authority)
        in_a = create(service, PRINCIPAL, slug="in-proj-a",
                      origin_scope="project", origin_owner="proj-a")
        in_b = create(service, PRINCIPAL, slug="in-proj-b",
                      origin_scope="project", origin_owner="proj-b")
        viewer_a = service.authorize_viewer(PRINCIPAL, SERVER_SCOPE,
                                            project_id="proj-a")
        viewer_b = service.authorize_viewer(PRINCIPAL, SERVER_SCOPE,
                                            project_id="proj-b")
        plain = service.authorize_viewer(PRINCIPAL, SERVER_SCOPE)
        assert service.get_definition(in_a.definition_id, viewer=viewer_a) == in_a
        assert service.get_definition(in_b.definition_id, viewer=viewer_b) == in_b
        assert failure(
            lambda: service.get_definition(in_a.definition_id, viewer=viewer_b)
        ) == absent_shape(in_a.definition_id)
        assert failure(
            lambda: service.get_definition(in_a.definition_id, viewer=plain)
        ) == absent_shape(in_a.definition_id)
        assert [
            row.slug for row in service.list_definitions(viewer=viewer_a)
        ] == ["in-proj-a"]

    def test_a_profile_definition_serves_only_its_own_sessions_G08(
        self, store: DefinitionStore
    ) -> None:
        authority = AttestingAuthority(
            profiles={(PRINCIPAL, SERVER_SCOPE, "prof-1"),
                      (PRINCIPAL, SERVER_SCOPE, "prof-2")},
            sessions={(PRINCIPAL, SERVER_SCOPE, "sess-1", "prof-1", "claude", "claude"),
                      (PRINCIPAL, SERVER_SCOPE, "sess-2", "prof-1", "claude", "codex")},
        )
        service = DefinitionService(store, authority=authority)
        profiled = create(service, PRINCIPAL, slug="profile-only",
                          origin_scope="profile", origin_owner="prof-1")
        own_profile = service.authorize_viewer(PRINCIPAL, SERVER_SCOPE,
                                               profile_id="prof-1")
        own_session = service.authorize_viewer(
            PRINCIPAL, SERVER_SCOPE, session_id="sess-1",
            session_profile_id="prof-1", session_harness_id="claude",
            harness_id="claude",
        )
        assert service.get_definition(profiled.definition_id,
                                      viewer=own_profile) == profiled
        assert service.get_definition(profiled.definition_id,
                                      viewer=own_session) == profiled
        # another profile of the same principal may not read it
        other_profile = service.authorize_viewer(PRINCIPAL, SERVER_SCOPE,
                                                 profile_id="prof-2")
        assert failure(
            lambda: service.get_definition(profiled.definition_id,
                                           viewer=other_profile)
        ) == absent_shape(profiled.definition_id)
        # a session that cannot prove it is on this harness fails closed (G08)
        cross_brand = service.authorize_viewer(
            PRINCIPAL, SERVER_SCOPE, session_id="sess-2",
            session_profile_id="prof-1", session_harness_id="claude",
            harness_id="codex",
        )
        assert failure(
            lambda: service.get_definition(profiled.definition_id,
                                           viewer=cross_brand)
        ) == absent_shape(profiled.definition_id)
        assert [
            row.slug for row in service.list_definitions(viewer=other_profile)
        ] == []

    def test_revision_reads_are_scoped_too(
        self, store: DefinitionStore
    ) -> None:
        service = DefinitionService(store, authority=FakeAuthority())
        mine = create(service, PRINCIPAL, slug="mine")
        theirs = create(service, OTHER_PRINCIPAL, slug="theirs")
        publish(service, mine)
        viewer = service.authorize_viewer(PRINCIPAL, SERVER_SCOPE)
        other_viewer = service.authorize_viewer(OTHER_PRINCIPAL, SERVER_SCOPE)
        assert service.latest_revision(mine.definition_id, viewer=viewer).revision == 1
        assert service.get_revision(mine.definition_id, 1, viewer=viewer) == \
            service.get_revision(mine.definition_id, 1)
        assert service.is_compilable(mine.definition_id, 1, viewer=viewer) is True
        for action in (
            lambda: service.get_revision(theirs.definition_id, 1, viewer=viewer),
            lambda: service.latest_revision(theirs.definition_id, viewer=viewer),
            lambda: service.is_compilable(theirs.definition_id, 1, viewer=viewer),
        ):
            assert failure(action) in (
                absent_shape(theirs.definition_id),
                revision_shape(theirs.definition_id, 1),
            )
        # a real gap on a visible definition keeps its own honest shape,
        # indistinguishable from the same gap on a hidden one
        assert failure(
            lambda: service.get_revision(mine.definition_id, 9, viewer=viewer)
        ) == revision_shape(mine.definition_id, 9)
        assert failure(
            lambda: service.get_revision(theirs.definition_id, 9, viewer=viewer)
        ) == revision_shape(theirs.definition_id, 9)

    def test_unattributed_rows_fail_closed_for_a_viewer(
        self, store: DefinitionStore
    ) -> None:
        service = DefinitionService(store, authority=FakeAuthority())
        seeded = dto.AgentDefinition(
            server_scope=SERVER_SCOPE, definition_id="def_direct000000000000000",
            slug="seeded-directly", display_name="Seeded directly",
            description="Written to the store without a service mutation.",
            origin_scope="public", origin_owner="local",
            latest_revision=0, archived=False, row_version=1,
        )
        store.create_definition(seeded)
        viewer = service.authorize_viewer(PRINCIPAL, SERVER_SCOPE)
        # provenance unknown -> invisible (identical to absent), never guessed
        assert failure(
            lambda: service.get_definition(seeded.definition_id, viewer=viewer)
        ) == absent_shape(seeded.definition_id)
        # the legacy seam still returns it (pinned existing behaviour)
        assert service.get_definition(seeded.definition_id) == seeded

    def test_ownership_attribution_survives_a_restart(
        self, store: DefinitionStore
    ) -> None:
        authority = FakeAuthority()
        service = DefinitionService(store, authority=authority)
        mine = create(service, PRINCIPAL, slug="mine")
        theirs = create(service, OTHER_PRINCIPAL, slug="theirs")
        restarted = DefinitionService(store, authority=authority)
        viewer = restarted.authorize_viewer(PRINCIPAL, SERVER_SCOPE)
        assert restarted.get_definition(mine.definition_id, viewer=viewer) == mine
        assert failure(
            lambda: restarted.get_definition(theirs.definition_id, viewer=viewer)
        ) == absent_shape(theirs.definition_id)

    def test_a_clone_belongs_to_the_cloning_principal(
        self, store: DefinitionStore
    ) -> None:
        service = DefinitionService(store, authority=FakeAuthority())
        theirs = create(service, OTHER_PRINCIPAL, slug="theirs")
        service.save_revision(
            OTHER_PRINCIPAL,
            make_revision(theirs.definition_id, 1,
                          source=approval(approved_by_principal=OTHER_PRINCIPAL)),
            server_scope=SERVER_SCOPE, operation_key="o:publish",
            expected_row_version=1,
        )
        cloned = service.clone(OTHER_PRINCIPAL, theirs.definition_id,
                               server_scope=SERVER_SCOPE, operation_key="o:clone",
                               expected_row_version=2, slug="cloned-by-other")
        viewer = service.authorize_viewer(PRINCIPAL, SERVER_SCOPE)
        assert failure(
            lambda: service.get_definition(cloned.definition_id, viewer=viewer)
        ) == absent_shape(cloned.definition_id)
        assert [
            row.slug for row in service.list_definitions(viewer=viewer)
        ] == []


# -- the separately named administrative surface ------------------------------


class AdminAuthority(AttestingAuthority):
    """An authority that can additionally attest an administrative reader."""

    def __init__(self, *, admins=(), **kwargs) -> None:
        super().__init__(**kwargs)
        self.admins = set(admins)

    def admin_read_allowed(self, principal: str, *, server_scope: str) -> bool:
        return (principal, server_scope) in self.admins


class TestAdminReadsAreSeparateAndAttested:
    def test_the_admin_surface_fails_closed_without_attestation(
        self, store: DefinitionStore
    ) -> None:
        for authority in (FakeAuthority(), AttestingAuthority()):
            service = DefinitionService(store, authority=authority)
            assert failure(
                lambda: service.authorize_admin_reader(PRINCIPAL, SERVER_SCOPE)
            )[0] == errors.PERMISSION_EXCEEDS_CEILING

    def test_an_unattested_or_forged_admin_context_is_refused(
        self, store: DefinitionStore
    ) -> None:
        authority = AdminAuthority(admins={(PRINCIPAL, SERVER_SCOPE)})
        service = DefinitionService(store, authority=authority)
        definition = create(service, PRINCIPAL, slug="target")
        stranger_service = DefinitionService(
            DefinitionStore(Path(store.root) / "elsewhere"), authority=authority
        )
        borrowed = stranger_service.authorize_admin_reader(PRINCIPAL, SERVER_SCOPE)
        assert failure(
            lambda: service.admin_get_definition(definition.definition_id,
                                                 admin=borrowed)
        )[0] == errors.PERMISSION_EXCEEDS_CEILING
        forged = service.authorize_viewer(PRINCIPAL, SERVER_SCOPE)
        assert failure(
            lambda: service.admin_get_definition(definition.definition_id,
                                                 admin=forged)
        )[0] == errors.PERMISSION_EXCEEDS_CEILING

    def test_an_attested_admin_reads_across_ownerships(
        self, store: DefinitionStore
    ) -> None:
        authority = AdminAuthority(admins={(PRINCIPAL, SERVER_SCOPE)})
        service = DefinitionService(store, authority=authority)
        mine = create(service, PRINCIPAL, slug="mine")
        theirs = create(service, OTHER_PRINCIPAL, slug="theirs")
        admin = service.authorize_admin_reader(PRINCIPAL, SERVER_SCOPE)
        assert service.admin_get_definition(theirs.definition_id, admin=admin) == theirs
        assert {
            row.slug for row in service.admin_list_definitions(admin=admin)
        } == {"mine", "theirs"}
        # and the ordinary viewer path still cannot see it
        viewer = service.authorize_viewer(PRINCIPAL, SERVER_SCOPE)
        assert failure(
            lambda: service.get_definition(theirs.definition_id, viewer=viewer)
        ) == absent_shape(theirs.definition_id)
        assert mine.archived is False


# -- §C5 queryable unknown ---------------------------------------------------


class TestOperationStatus:
    def test_a_recorded_outcome_is_requeryable(self, store: DefinitionStore) -> None:
        service = DefinitionService(store, authority=FakeAuthority())
        definition = create(service, PRINCIPAL, slug="queryable",
                            key="p:op:queryable")
        status = service.operation_status(
            PRINCIPAL, "create", f"{SERVER_SCOPE}/queryable",
            server_scope=SERVER_SCOPE, operation_key="p:op:queryable",
        )
        assert status.state == "recorded"
        assert status.code is None
        assert status.result is not None
        assert status.result["definition_id"] == definition.definition_id
        assert status.request_digest.startswith("sha256:")
        # the recorded result replays exactly what the mutation returned
        assert dto.AgentDefinition(**status.result) == definition

    def test_an_unknown_outcome_is_never_answered_as_success(
        self, store: DefinitionStore
    ) -> None:
        service = DefinitionService(store, authority=FakeAuthority())
        create(service, PRINCIPAL, slug="busy", key="p:op:busy")
        status = service.operation_status(
            PRINCIPAL, "create", f"{SERVER_SCOPE}/busy",
            server_scope=SERVER_SCOPE, operation_key="p:never-sent",
        )
        assert status.state == "unknown"
        assert status.code == errors.OPERATION_UNKNOWN
        assert status.result is None
        assert status.request_digest is None
        # a non-idempotent action name is the same honest unknown
        assert service.operation_status(
            PRINCIPAL, "delete", "whatever", server_scope=SERVER_SCOPE,
            operation_key="p:op:busy",
        ).code == errors.OPERATION_UNKNOWN
        # and an empty key is the same typed refusal mutations give
        assert failure(
            lambda: service.operation_status(
                PRINCIPAL, "create", "t", server_scope=SERVER_SCOPE,
                operation_key="",
            )
        )[0] == errors.DEFINITION_INVALID

    def test_another_principal_never_sees_the_receipt(
        self, store: DefinitionStore
    ) -> None:
        service = DefinitionService(store, authority=FakeAuthority())
        definition = create(service, PRINCIPAL, slug="private-op",
                            key="shared-key")
        own = service.operation_status(PRINCIPAL, "create",
                                       f"{SERVER_SCOPE}/private-op",
                                       server_scope=SERVER_SCOPE,
                                       operation_key="shared-key")
        assert own.state == "recorded"
        stranger = service.operation_status(OTHER_PRINCIPAL, "create",
                                            f"{SERVER_SCOPE}/private-op",
                                            server_scope=SERVER_SCOPE,
                                            operation_key="shared-key")
        # exactly the shape of a receipt that never existed...
        never = service.operation_status(OTHER_PRINCIPAL, "create",
                                         f"{SERVER_SCOPE}/private-op",
                                         server_scope=SERVER_SCOPE,
                                         operation_key="never-sent")
        assert (stranger.state, stranger.code, stranger.request_digest,
                stranger.result) == (never.state, never.code,
                                     never.request_digest, never.result)
        assert stranger.state == "unknown"
        assert stranger.code == errors.OPERATION_UNKNOWN
        # ...and no byte of the recorded payload leaks into it
        assert definition.definition_id not in repr(stranger)

    def test_an_unattested_principal_cannot_query(
        self, store: DefinitionStore
    ) -> None:
        service = DefinitionService(store, authority=FakeAuthority())
        assert failure(
            lambda: service.operation_status(
                "u:stranger", "create", "t", server_scope=SERVER_SCOPE,
                operation_key="k",
            )
        )[0] == errors.PERMISSION_EXCEEDS_CEILING

    def test_the_receipt_reports_the_original_outcome_after_a_conflicting_replay(
        self, store: DefinitionStore
    ) -> None:
        service = DefinitionService(store, authority=FakeAuthority())
        definition = create(service, PRINCIPAL, slug="once", key="p:op:once")
        with pytest.raises(errors.DomainError) as refused:
            service.create_definition(
                PRINCIPAL, server_scope=SERVER_SCOPE, slug="once",
                display_name="Other", description="A different payload entirely.",
                origin_scope="public", origin_owner="local",
                operation_key="p:op:once", expected_row_version=0,
            )
        assert refused.value.code == errors.ASSIGNMENT_CONFLICT
        status = service.operation_status(PRINCIPAL, "create",
                                          f"{SERVER_SCOPE}/once",
                                          server_scope=SERVER_SCOPE,
                                          operation_key="p:op:once")
        assert status.state == "recorded"
        assert status.result["definition_id"] == definition.definition_id

    def test_every_mutation_action_is_queryable(
        self, store: DefinitionStore
    ) -> None:
        service = DefinitionService(store, authority=FakeAuthority())
        definition = create(service, PRINCIPAL, slug="verbs")
        publish(service, definition, operation_key="p:pub")
        row = service.get_definition(definition.definition_id)
        service.archive(PRINCIPAL, definition.definition_id,
                        server_scope=SERVER_SCOPE, operation_key="p:arch",
                        expected_row_version=row.row_version)
        for action, target, key in (
            ("create", f"{SERVER_SCOPE}/verbs", "u:tester:create:verbs"),
            ("save_revision", definition.definition_id, "p:pub"),
            ("archive", definition.definition_id, "p:arch"),
        ):
            status = service.operation_status(PRINCIPAL, action, target,
                                              server_scope=SERVER_SCOPE,
                                              operation_key=key)
            assert status.state == "recorded", action

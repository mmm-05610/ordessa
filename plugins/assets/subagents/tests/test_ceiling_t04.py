"""T04 / FR06 + US3 + G09: the ceiling refuses; it never narrows-and-claims."""
from __future__ import annotations

import pytest

from ordessa_assets_subagents import ceiling, dto, errors
from ordessa_assets_subagents.ceiling import ItemRuling
from ordessa_assets_subagents.scopes import (
    AuthorizationContext,
    Principal,
    ProjectId,
    ServerScope,
)

U1 = Principal("u1")
SCOPE = ServerScope("s1")
DIGEST = "sha256:" + "b" * 64


def revision(**overrides) -> dto.DefinitionRevision:
    base = dict(
        definition_id="d1", revision=1, content_digest=DIGEST, role_body="body",
    )
    base.update(overrides)
    return dto.DefinitionRevision(**base)


def grant_ceiling(**overrides) -> ceiling.Ceiling:
    base = dict(
        principal=U1, server_scope=SCOPE, harness_id="claude",
        allowed_tools=frozenset({"Read", "Grep"}),
        allowed_models=frozenset({"model-basic"}),
        allowed_mcp=frozenset(),
        allowed_skills=frozenset(),
        allowed_permission_modes=frozenset({"default"}),
        allowed_isolation_keys=frozenset(),
    )
    base.update(overrides)
    return ceiling.Ceiling(**base)


class TestRefuseOverCeiling:
    def test_bash_request_without_grant_is_refused_naming_the_field(self) -> None:
        with pytest.raises(errors.DomainError) as exc:
            ceiling.admit(revision(requested_permission="Bash"), grant_ceiling())
        assert exc.value.code == errors.PERMISSION_EXCEEDS_CEILING
        assert "requested_permission" in exc.value.item_id

    def test_declared_tool_ref_outside_grant_is_refused(self) -> None:
        rev = revision(tool_refs=(dto.ToolRef("Bash"),))
        with pytest.raises(errors.DomainError) as exc:
            ceiling.admit(rev, grant_ceiling())
        assert exc.value.code == errors.PERMISSION_EXCEEDS_CEILING
        assert "toolRefs" in exc.value.item_id

    def test_permission_mode_widening_is_refused(self) -> None:
        rev = revision(retained_native_fields={"permissionMode": "bypassPermissions"})
        with pytest.raises(errors.DomainError) as exc:
            ceiling.admit(rev, grant_ceiling())
        assert "permissionMode" in exc.value.item_id

    def test_isolation_widening_is_refused(self) -> None:
        rev = revision(isolation={"sandbox": "off"})
        with pytest.raises(errors.DomainError) as exc:
            ceiling.admit(rev, grant_ceiling())
        assert exc.value.code == errors.PERMISSION_EXCEEDS_CEILING
        assert "isolation.sandbox" in exc.value.item_id

    def test_ungranted_model_and_mcp_are_refused(self) -> None:
        with pytest.raises(errors.DomainError):
            ceiling.admit(revision(declared_model_ref=dto.ModelRef("model-frontier")),
                          grant_ceiling())
        with pytest.raises(errors.DomainError):
            ceiling.admit(revision(mcp_refs=(dto.McpRef("ungranted-mcp"),)),
                          grant_ceiling())

    def test_zero_grant_ceiling_refuses_any_tool_declaration(self) -> None:
        empty = grant_ceiling(allowed_tools=frozenset())
        with pytest.raises(errors.DomainError) as exc:
            ceiling.admit(revision(tool_refs=(dto.ToolRef("Read"),)), empty)
        assert exc.value.code == errors.PERMISSION_EXCEEDS_CEILING


class TestNoPermissiveDefault:
    def test_absent_authority_refuses_instead_of_defaulting_open(self) -> None:
        with pytest.raises(errors.DomainError) as exc:
            ceiling.admit(revision(), None)
        assert exc.value.code == errors.ADAPTER_MISSING

    def test_unverifiable_content_is_refused_not_assumed(self) -> None:
        with pytest.raises(errors.DomainError) as exc:
            ceiling.admit(revision(content_digest=""), grant_ceiling())
        assert exc.value.code == errors.NATIVE_VERSION_UNKNOWN


class TestAdmissionStaysWithinCeiling:
    def test_within_ceiling_admits_and_keeps_grants_bounded(self) -> None:
        granted = grant_ceiling()
        admitted = ceiling.admit(
            revision(tool_refs=(dto.ToolRef("Read"),),
                     declared_model_ref=dto.ModelRef("model-basic"),
                     requested_permission="Read"),
            granted,
        )
        assert admitted.within_ceiling(granted)
        assert admitted.effective_tools == frozenset({"Read"})

    def test_admission_cannot_raise_the_ceiling(self) -> None:
        granted = grant_ceiling()
        admitted = ceiling.admit(revision(), granted)
        assert admitted.effective_tools <= granted.allowed_tools
        assert granted.allowed_tools == frozenset({"Read", "Grep"})
        with pytest.raises(errors.DomainError):
            ceiling.admit(
                revision(tool_refs=(dto.ToolRef("Read"), dto.ToolRef("Bash"))),
                granted,
            )

    def test_granted_permission_mode_is_recorded_not_widened(self) -> None:
        admitted = ceiling.admit(
            revision(retained_native_fields={"permissionMode": "default"}),
            grant_ceiling(),
        )
        assert admitted.approval_mode == "default"


class ScriptedAuthority:
    """PORT-BOUNDARY FAKE for the `ceiling.CeilingAuthority` protocol.

    It stands in for `permissions_seam.PermissionsSeam` so the *ceiling layer's*
    own contract — which items it puts to the authority, what it does with each
    answer, and what it must never do — is testable without a live backend. The
    rulings are the real `ceiling.ItemRuling` values the seam returns; nothing
    inside `ordessa_permissions_*` is reached or stubbed here.
    """

    def __init__(self, *, available: bool = True, admit: bool = True,
                 standing: bool = False, code: str | None = None,
                 deny_fields: tuple[str, ...] = ()) -> None:
        self.available = available
        self.admit = admit
        self.standing = standing
        self.code = code
        self.deny_fields = deny_fields
        self.calls: list[tuple[str, str, str]] = []

    def is_available(self) -> bool:
        return self.available

    def subject_for(self,
                    revision: dto.DefinitionRevision) -> ceiling.AdmissionContext:
        return ceiling.AdmissionContext.from_service(
            principal=U1, server_scope=SCOPE, harness_id="claude", revision=revision)

    def adjudicate(self, context: ceiling.AdmissionContext, kind: str, value: str, *,
                   field_name: str) -> ItemRuling:
        assert context.verified, "the ceiling layer must hand the authority a verified subject"
        assert context.definition_id == "d1" and context.content_digest
        self.calls.append((kind, value, field_name))
        denied = (not self.admit and
                  (not self.deny_fields or field_name in self.deny_fields))
        if denied:
            return ItemRuling(
                field_name=field_name, admitted=False, standing=False,
                code=self.code or errors.PERMISSION_EXCEEDS_CEILING,
                detail=f"scripted refusal of '{field_name}'",
                authority_code="POLICY_CEILING_VIOLATION",
            )
        return ItemRuling(field_name=field_name, admitted=True,
                          standing=self.standing, authority_code="allowed_once")


def authority_ceiling(**overrides) -> ceiling.Ceiling:
    base = dict(principal=U1, server_scope=SCOPE, harness_id="claude",
                allowed_tools=frozenset({"Read"}),
                allowed_models=frozenset({"model-basic"}),
                allowed_permission_modes=frozenset({"default"}),
                authority=ScriptedAuthority())
    base.update(overrides)
    return ceiling.Ceiling(**base)


class TestTheSubjectIsTheServiceIdentity:
    def test_a_hand_built_context_is_not_a_verified_subject(self) -> None:
        # `AdmissionContext` defaults to unverified: a component that assembles
        # one from request data gets a refusal, not a ruling.
        claim = ceiling.AdmissionContext(
            principal=Principal("attacker"), server_scope=SCOPE, harness_id="claude",
            definition_id="d1", revision=1, content_digest=DIGEST)
        seam_subject = claim
        assert seam_subject.verified is False

    def test_a_service_issued_subject_carries_the_verified_principal(self) -> None:
        authorization = AuthorizationContext.issued_by_service(
            U1, SCOPE, ProjectId("p1"))
        subject = ceiling.AdmissionContext.issued_by_service(
            authorization, harness_id="claude", revision=revision(),
            claimed_project_id="p1")
        assert subject.verified and subject.principal == U1
        assert subject.project_id == ProjectId("p1")
        forged = AuthorizationContext.issued_by_service(U1, SCOPE)
        with pytest.raises(errors.DomainError) as exc:
            ceiling.AdmissionContext.issued_by_service(
                forged, harness_id="claude", revision=revision(),
                claimed_project_id="p-claimed")
        assert exc.value.code == errors.PERMISSION_EXCEEDS_CEILING
        assert exc.value.item_id == "project_id"


class TestRealAuthorityIsConsumed:
    def test_every_declared_item_is_put_to_the_authority(self) -> None:
        scripted = ScriptedAuthority()
        rev = revision(tool_refs=(dto.ToolRef("Read"),),
                       declared_model_ref=dto.ModelRef("model-basic"),
                       requested_permission="Read",
                       retained_native_fields={"permissionMode": "default"})
        admitted = ceiling.admit(rev, authority_ceiling(authority=scripted))
        seen = {field for _kind, _value, field in scripted.calls}
        assert seen == {
            "requested_permission", "retained_native_fields.permissionMode",
            "toolRefs.Read", "declaredModelRef", "definition",
        }, seen
        assert admitted.within_ceiling(authority_ceiling(authority=None))

    def test_a_refusal_from_the_authority_is_typed_and_names_the_field(self) -> None:
        scripted = ScriptedAuthority(admit=False, deny_fields=("toolRefs.Bash",),
                                     code=errors.PERMISSION_EXCEEDS_CEILING)
        granted = authority_ceiling(
            authority=scripted, allowed_tools=frozenset({"Read", "Bash"}))
        with pytest.raises(errors.DomainError) as exc:
            ceiling.admit(revision(tool_refs=(dto.ToolRef("Bash"),)), granted)
        assert exc.value.code == errors.PERMISSION_EXCEEDS_CEILING
        assert "toolRefs.Bash" in exc.value.item_id

    @pytest.mark.parametrize("code", [
        errors.PERMISSION_EXCEEDS_CEILING,
        errors.REFERENCE_UNRESOLVED,
        errors.OPERATION_UNKNOWN,
        errors.ASSIGNMENT_CONFLICT,
        errors.ADAPTER_MISSING,
    ])
    def test_the_authoritys_own_code_is_carried_through(self, code) -> None:
        scripted = ScriptedAuthority(admit=False, code=code)
        with pytest.raises(errors.DomainError) as exc:
            ceiling.admit(revision(), authority_ceiling(authority=scripted))
        assert exc.value.code == code
        assert "definition" in exc.value.item_id

    def test_the_local_ceiling_still_binds_when_the_authority_would_admit(
        self,
    ) -> None:
        # An authority that waves everything through must not be able to raise
        # the recorded ceiling: the recorded guard fires first.
        scripted = ScriptedAuthority(admit=True)
        with pytest.raises(errors.DomainError) as exc:
            ceiling.admit(revision(tool_refs=(dto.ToolRef("Bash"),)),
                          authority_ceiling(authority=scripted))
        assert exc.value.code == errors.PERMISSION_EXCEEDS_CEILING
        assert "toolRefs" in exc.value.item_id
        assert scripted.calls == [], "the authority replaced the guard, not the lookup"

    def test_an_authority_that_cannot_answer_refuses(self) -> None:
        with pytest.raises(errors.DomainError) as exc:
            ceiling.admit(revision(),
                          authority_ceiling(authority=ScriptedAuthority(available=False)))
        assert exc.value.code == errors.ADAPTER_MISSING

    def test_a_bare_authority_admits_what_it_just_ruled_on(self) -> None:
        scripted = ScriptedAuthority(admit=True, standing=True)
        admitted = ceiling.admit(revision(tool_refs=(dto.ToolRef("Read"),)), scripted)
        assert admitted.effective_tools == frozenset({"Read"})
        assert admitted.single_use_fields == ()
        assert not any("against ceiling of" in item for item in admitted.evidence)


class TestOneShotIsNeverStanding:
    def test_single_use_rulings_are_reported_and_do_not_widen_the_ceiling(
        self,
    ) -> None:
        granted = authority_ceiling(authority=ScriptedAuthority(standing=False))
        before = granted.allowed_tools
        admitted = ceiling.admit(revision(tool_refs=(dto.ToolRef("Read"),)), granted)
        assert admitted.is_standing is False
        assert set(admitted.single_use_fields) == {"toolRefs.Read", "definition"}
        assert granted.allowed_tools == before == frozenset({"Read"})
        assert any("single-use" in item for item in admitted.evidence)

    def test_admission_reconsults_every_time_rather_than_caching_a_grant(
        self,
    ) -> None:
        scripted = ScriptedAuthority(standing=False)
        granted = authority_ceiling(authority=scripted)
        first = ceiling.admit(revision(), granted)
        calls_after_first = len(scripted.calls)
        second = ceiling.admit(revision(), granted)
        assert len(scripted.calls) == calls_after_first * 2
        assert first.single_use_fields == second.single_use_fields

    def test_a_standing_ruling_is_the_only_way_to_lose_the_single_use_mark(
        self,
    ) -> None:
        admitted = ceiling.admit(revision(),
                                 authority_ceiling(authority=ScriptedAuthority(
                                     standing=True)))
        assert admitted.single_use_fields == ()
        assert admitted.is_standing
        assert any("standing" in item for item in admitted.evidence)

    def test_absent_authority_still_refuses_with_no_permissive_default(self) -> None:
        # The pre-existing stop-gap guard must survive the real authority: an
        # authority that is simply not wired is still ADAPTER_MISSING.
        with pytest.raises(errors.DomainError) as exc:
            ceiling.admit(revision(), None)
        assert exc.value.code == errors.ADAPTER_MISSING
        with pytest.raises(errors.DomainError) as not_an_authority:
            ceiling.admit(revision(), object())
        assert not_an_authority.value.code == errors.ADAPTER_MISSING

    def test_an_unverifiable_revision_reaches_neither_guard(self) -> None:
        scripted = ScriptedAuthority()
        with pytest.raises(errors.DomainError) as exc:
            ceiling.admit(revision(content_digest=""), authority_ceiling(
                authority=scripted))
        assert exc.value.code == errors.NATIVE_VERSION_UNKNOWN
        assert scripted.calls == []

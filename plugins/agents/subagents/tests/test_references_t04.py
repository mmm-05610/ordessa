"""T04 / FR05 + G09: declarations resolved by owners, never copied secrets."""
from __future__ import annotations

import datetime as dt
import json

import pytest
from ordessa_permissions_api import AuthorizationDecision

from ordessa_assets_subagents import dto, errors
from ordessa_assets_subagents.references import (
    McpResolver,
    ModelResolver,
    SkillResolver,
    ToolResolver,
    rematch_tool_names,
    resolve_references,
    sanitize_facts,
)
from ordessa_assets_subagents.scopes import Diagnostic

from test_ceiling_t04 import ScriptedAuthority


class ModelService:
    def __init__(self, facts: object = None) -> None:
        self.facts = facts if facts is not None else {"context": "200k"}

    def resolve_model(self, ref: dto.ModelRef):
        return None if self.facts is MISSING else self.facts


class ToolService:
    def __init__(self, facts: object = None) -> None:
        self.facts = facts if facts is not None else {"kind": "read-only"}

    def resolve_tool(self, ref: dto.ToolRef):
        return None if self.facts is MISSING else self.facts


class McpService:
    def resolve_mcp(self, ref: dto.McpRef):
        return {"server": "own"}


class SkillService:
    def resolve_skill(self, ref: dto.SkillRef):
        return {"skill": "own"}


MISSING = object()


def revision(**overrides) -> dto.DefinitionRevision:
    base = dict(
        definition_id="d1", revision=1, content_digest="sha256:" + "a" * 64,
        role_body="body",
        declared_model_ref=dto.ModelRef("m1"),
        tool_refs=(dto.ToolRef("t1"),),
        mcp_refs=(dto.McpRef("mcp1"),),
        skill_refs=(dto.SkillRef("s1"),),
    )
    base.update(overrides)
    return dto.DefinitionRevision(**base)


ALL_SERVICES = dict(
    models=ModelService(), tools=ToolService(), mcps=McpService(),
    skills=SkillService(),
)


class TestInjectedResolvers:
    def test_full_resolution_yields_four_clean_references(self) -> None:
        result = resolve_references(revision(), **ALL_SERVICES)
        assert len(result.references) == 4
        assert not result.unresolved

    def test_absent_services_diagnose_but_do_not_raise(self) -> None:
        result = resolve_references(revision())
        assert result.references == ()
        assert len(result.diagnostics) == 4
        assert all(d.code == errors.REFERENCE_UNRESOLVED for d in result.diagnostics)

    def test_runtime_fail_fast_turns_diagnostic_into_refusal(self) -> None:
        with pytest.raises(errors.DomainError) as exc:
            resolve_references(revision(), fail_fast=True)
        assert exc.value.code == errors.REFERENCE_UNRESOLVED
        assert exc.value.item_id == "model:m1"

    def test_owning_service_returning_none_is_unresolved(self) -> None:
        result = resolve_references(
            revision(), **{**ALL_SERVICES, "tools": ToolService(MISSING)}
        )
        assert len(result.references) == 3
        assert result.diagnostics[0].item_id == "tool:t1"


class TestNoSecretsEverSerialized:
    def test_resolver_supplied_credentials_are_dropped(self) -> None:
        leaky = ToolService({
            "kind": "search",
            "token": "TOKENVALUE-DO-NOT-LOG",
            "api_key": "APIKEYVALUE-DO-NOT-LOG",
            "password": "PASSWORDVALUE-DO-NOT-LOG",
            "auth": {"client_secret": "SECRETVALUE-DO-NOT-LOG", "tier": "paid"},
        })
        result = resolve_references(revision(), **{**ALL_SERVICES, "tools": leaky})
        tool_ref = next(r for r in result.references if r.kind == "tool")
        payload = json.dumps(tool_ref.as_mapping(), sort_keys=True)
        for marker in ("TOKENVALUE", "APIKEYVALUE", "PASSWORDVALUE", "SECRETVALUE"):
            assert marker not in payload
        assert tool_ref.facts["kind"] == "search"
        assert tool_ref.facts["auth"] == {"tier": "paid"}

    def test_executable_paths_are_dropped(self) -> None:
        assert sanitize_facts({"executable": "/opt/bin/x", "name": "ok"}) == {"name": "ok"}
        assert sanitize_facts({"nested": {"file_path": "/etc/passwd", "n": 1}}) == {
            "nested": {"n": 1}
        }


class TestToolNameRematch:
    TABLE = {
        "Read": {"grant": "read-only"},
        "Write": {"grant": "workspace-write"},
    }

    def test_typed_string_grants_nothing_unmatched(self) -> None:
        resolved, diagnostics = rematch_tool_names(["Read", "Bash"], self.TABLE)
        assert [r.owner_id for r in resolved] == ["Read"]
        assert len(diagnostics) == 1
        assert diagnostics[0].code == errors.REFERENCE_UNRESOLVED
        assert diagnostics[0].item_id == "tool-name:Bash"

    def test_resolved_facts_come_from_the_table_not_the_string(self) -> None:
        resolved, _ = rematch_tool_names(["Read"], self.TABLE)
        assert resolved[0].facts == {"grant": "read-only"}

    def test_missing_table_fails_closed(self) -> None:
        resolved, diagnostics = rematch_tool_names(["Read"], None)
        assert resolved == ()
        assert diagnostics[0].code == errors.REFERENCE_UNRESOLVED

    def test_diagnostic_shape_is_item_level(self) -> None:
        _, diagnostics = rematch_tool_names(["Bash"], self.TABLE)
        assert isinstance(diagnostics[0], Diagnostic)
        assert diagnostics[0].item_id == "tool-name:Bash"
        assert "grants nothing" in diagnostics[0].detail


class AuthorityShapedToolService:
    """A resolver that echoes the authority's own decision record — plus a
    credential it must never have carried, and the executable path a sloppy
    owner service might leak. Real payloads of this shape do occur: the ruling
    arrives as their `AuthorizationDecision`, and the row it refers to has a
    launch path."""

    def __init__(self, record: dict) -> None:
        self.record = record

    def resolve_tool(self, ref: dto.ToolRef):
        return {
            **self.record,
            "auth": {"token": "TOKEN-FROM-AUTHORITY-PAYLOAD", "tier": "paid"},
            "authorization": "Bearer APIKEY-FROM-AUTHORITY-PAYLOAD",
            "command": "PASSWORD-FROM-AUTHORITY-PAYLOAD --do-a-thing",
            "executable": "/opt/bin/SURFACE-FROM-AUTHORITY-PAYLOAD",
            "name": "read",
        }


class TestReferenceAuthorisationGoesThroughTheAuthority:
    def test_each_owner_is_put_to_the_authority_by_name(self) -> None:
        scripted = ScriptedAuthority(admit=True, standing=True)
        result = resolve_references(revision(), **ALL_SERVICES, authority=scripted)
        assert [(kind, value) for kind, value, _field in scripted.calls] == [
            ("model", "m1"), ("tool", "t1"), ("mcp", "mcp1"), ("skill", "s1"),
        ]
        assert len(result.references) == 4
        assert not result.unresolved

    def test_an_authority_denial_keeps_its_own_code_and_names_the_reference(
        self,
    ) -> None:
        scripted = ScriptedAuthority(admit=False, deny_fields=(),
                                     code=errors.PERMISSION_EXCEEDS_CEILING)
        result = resolve_references(revision(), **ALL_SERVICES, authority=scripted)
        assert result.references == ()
        assert {d.item_id for d in result.diagnostics} == {
            "model:m1", "tool:t1", "mcp:mcp1", "skill:s1"}
        assert all(d.code == errors.PERMISSION_EXCEEDS_CEILING for d in result.diagnostics)
        # Not flattened into REFERENCE_UNRESOLVED: "the authority says no" and
        # "the owner has no answer" are different §C5 findings.

    def test_an_admitted_reference_still_needs_its_owner_to_answer(self) -> None:
        scripted = ScriptedAuthority(admit=True, standing=True)
        result = resolve_references(
            revision(), tools=ToolService(MISSING), authority=scripted)
        unresolved = {d.item_id for d in result.diagnostics}
        assert "tool:t1" in unresolved
        tool_diagnostic = next(d for d in result.diagnostics if d.item_id == "tool:t1")
        assert tool_diagnostic.code == errors.REFERENCE_UNRESOLVED
        assert "declaration only" in tool_diagnostic.detail
        # The declaration is still storable: nothing raised here.

    def test_the_runtime_path_refuses_with_the_authoritys_code(self) -> None:
        scripted = ScriptedAuthority(admit=False, code=errors.ASSIGNMENT_CONFLICT)
        with pytest.raises(errors.DomainError) as exc:
            resolve_references(revision(), **ALL_SERVICES, authority=scripted,
                               fail_fast=True)
        assert exc.value.code == errors.ASSIGNMENT_CONFLICT
        assert exc.value.item_id == "model:m1"

    def test_an_authority_that_cannot_answer_grants_nothing(self) -> None:
        scripted = ScriptedAuthority(available=False)
        with pytest.raises(errors.DomainError) as exc:
            resolve_references(revision(), **ALL_SERVICES, authority=scripted,
                               fail_fast=True)
        assert exc.value.code == errors.ADAPTER_MISSING
        assert scripted.calls == []

    def test_no_authority_keeps_the_stored_declaration_semantics(self) -> None:
        # The pre-existing behaviour (no authority wired at all) is unchanged:
        # storable declaration, item-level diagnostic, no silent permission.
        result = resolve_references(revision(), **ALL_SERVICES)
        assert len(result.references) == 4
        assert not result.unresolved


class TestAuthorityPayloadReachesNoSnapshot:
    def test_a_self_reported_authority_payload_is_stripped_of_secrets(self) -> None:
        record = AuthorizationDecision.of(
            native_request_id="native-1", operation_digest="a" * 64, tool="read",
            subject="u1", action="allow", reason="the authority allows this read",
            policy_digest="q3-admin@1",
            expires_at=dt.datetime(2026, 9, 28, 12, 5, tzinfo=dt.timezone.utc),
        ).as_record()
        leaky = AuthorityShapedToolService(record)
        result = resolve_references(revision(tool_refs=(dto.ToolRef("Read"),)),
                                    tools=leaky)
        payload = json.dumps([item.as_mapping() for item in result.references],
                             sort_keys=True)
        for marker in ("TOKEN-FROM-AUTHORITY-PAYLOAD", "APIKEY-FROM-AUTHORITY-PAYLOAD",
                       "PASSWORD-FROM-AUTHORITY-PAYLOAD",
                       "SURFACE-FROM-AUTHORITY-PAYLOAD"):
            assert marker not in payload
        reference = result.references[0]
        assert reference.facts["name"] == "read"
        assert reference.facts["reason"] == {"code": None,
                                            "message": "the authority allows this read"}
        # Only the secret-bearing entries go; a benign nested fact stays, so the
        # sanitizer is targeted and not a sledgehammer.
        assert reference.facts["auth"] == {"tier": "paid"}
        assert "executable" not in reference.facts
        assert "command" not in reference.facts
        assert "authorization" not in reference.facts

    def test_a_real_authority_ruling_leaves_no_secret_in_the_snapshot(
        self, tmp_path
    ) -> None:
        # The ruling here comes from Q5's real Authorizer over the real
        # approval store (see test_permissions_seam_t04.wire), so this proves the
        # guarantee against an authority-shaped payload, not a hand-written one.
        from test_permissions_seam_t04 import intent_allowing, wire

        _facts, _authorizer, seam = wire(
            tmp_path, intent=intent_allowing("task", "read"))
        record = AuthorizationDecision.of(
            native_request_id="native-1", operation_digest="b" * 64, tool="read",
            subject="u1", action="allow", reason="allowed by the real authority",
            policy_digest="q3-admin@1+q3-intent@1",
            expires_at=dt.datetime(2026, 9, 28, 12, 5, tzinfo=dt.timezone.utc),
        ).as_record()
        result = resolve_references(
            revision(tool_refs=(dto.ToolRef("Read"),), declared_model_ref=None,
                     mcp_refs=(), skill_refs=()),
            tools=AuthorityShapedToolService(record), authority=seam)
        assert [item.owner_id for item in result.references] == ["Read"], \
            result.diagnostics
        payload = json.dumps([item.as_mapping() for item in result.references],
                             sort_keys=True)
        for marker in ("TOKEN-FROM-AUTHORITY-PAYLOAD", "APIKEY-FROM-AUTHORITY-PAYLOAD",
                       "PASSWORD-FROM-AUTHORITY-PAYLOAD",
                       "SURFACE-FROM-AUTHORITY-PAYLOAD", "/opt/bin/"):
            assert marker not in payload
        reference = result.references[0]
        assert set(reference.authority) <= {
            "admitted", "standing", "code", "authorityCode", "approvalId", "payload"}
        assert reference.authority["admitted"] is True
        assert reference.authority["standing"] is False
        assert reference.authority["authorityCode"] == "allowed_once"
        # The authority's own record rides as sanitized data, and it carries no
        # credential- or path-shaped entry: their record has no such field.
        payload = reference.authority["payload"]
        assert payload["singleUse"] is True
        assert not any(marker in json.dumps(payload) for marker in
                       ("TOKEN", "APIKEY", "PASSWORD", "/opt/bin", "authorization"))

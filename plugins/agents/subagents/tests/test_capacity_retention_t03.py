"""G04 negative column — capacity, encoding and field retention (FR01/FR06)."""
from __future__ import annotations

import json

import pytest

from conftest import (PRINCIPAL, SERVER_SCOPE, approval, make_revision,
                      publish, revision_mapping)
from ordessa_assets_subagents import decoder, digest, dto, errors, limits
from ordessa_assets_subagents.service import DefinitionService


class TestFieldRetention:
    def test_an_unknown_top_level_field_is_kept_verbatim(self) -> None:
        mapping = revision_mapping(
            hooks={"command": "notify.sh"}, permissionMode="acceptEdits",
        )
        revision = decoder.decode_revision(mapping)
        assert revision.retained_native_fields == {
            "hooks": {"command": "notify.sh"}, "permissionMode": "acceptEdits",
        }

    def test_a_retained_field_never_reaches_the_declared_view(self) -> None:
        revision = decoder.decode_revision(revision_mapping(
            mcpServers=["private-registry"], tools=["Bash"],
        ))
        assert revision.mcp_refs == ()
        assert revision.tool_refs == ()
        assert "mcpServers" in revision.retained_native_fields
        assert "tools" in revision.retained_native_fields

    def test_is_compilable_is_false_while_anything_is_retained(
        self, service: DefinitionService, definition: dto.AgentDefinition
    ) -> None:
        plain = make_revision(definition.definition_id, 1)
        assert decoder.is_compilable(plain) is True
        held_back = make_revision(definition.definition_id, 1,
                                  retained_native_fields={"isolation": "mac2"})
        assert decoder.is_compilable(held_back) is False
        service.save_revision(
            PRINCIPAL, held_back, server_scope=SERVER_SCOPE,
            operation_key="u:retain", expected_row_version=1,
        )
        assert service.is_compilable(definition.definition_id, 1) is False

    def test_a_retained_field_survives_the_store_round_trip_verbatim(
        self, service: DefinitionService, definition: dto.AgentDefinition
    ) -> None:
        held = {"hooks": [{"command": "a.sh"}, {"command": "b.sh"}]}
        published = publish(service, definition, 1, retained_native_fields=held)
        read_back = service.get_revision(definition.definition_id, 1)
        assert read_back == published
        assert read_back.retained_native_fields == held

    def test_a_retained_fragment_that_is_not_json_shaped_is_refused(self) -> None:
        mapping = revision_mapping()
        mapping["object"] = object()
        with pytest.raises(errors.DomainError) as caught:
            decoder.decode_revision(mapping)
        assert caught.value.code == errors.DEFINITION_INVALID
        assert caught.value.item_id == "retained_native_fields.object"

    def test_a_retained_fragment_beyond_its_own_cap_is_refused(self) -> None:
        mapping = revision_mapping()
        mapping["extra"] = "y" * (limits.MAX_RETAINED_NATIVE_BYTES + 1)
        with pytest.raises(errors.DomainError) as caught:
            decoder.decode_revision(mapping)
        assert caught.value.code == errors.DEFINITION_INVALID


class TestStrictTypes:
    def test_a_wrong_type_names_the_item(self) -> None:
        cases = {
            "revision": "1",
            "role_body": 42,
            "tool_refs": {"owner_id": "Read"},
            "isolation": ["x"],
            "source": "approved",
        }
        for item, value in cases.items():
            with pytest.raises(errors.DomainError) as caught:
                decoder.decode_revision(revision_mapping(**{item: value}))
            assert caught.value.code == errors.DEFINITION_INVALID
            assert caught.value.item_id.startswith(item), item

    def test_a_missing_required_field_is_refused(self) -> None:
        for item in ("definition_id", "revision", "content_digest", "role_body"):
            mapping = revision_mapping()
            del mapping[item]
            with pytest.raises(errors.DomainError) as caught:
                decoder.decode_revision(mapping)
            assert caught.value.item_id == item

    def test_content_without_a_source_is_refused(self) -> None:
        mapping = revision_mapping()
        del mapping["source"]
        with pytest.raises(errors.DomainError) as caught:
            decoder.decode_revision(mapping)
        assert caught.value.code == errors.DEFINITION_INVALID
        assert caught.value.item_id == "source"

    def test_a_definition_row_rejects_unknown_fields(self) -> None:
        with pytest.raises(errors.DomainError) as caught:
            decoder.decode_definition({
                "server_scope": SERVER_SCOPE, "definition_id": "def_x1", "slug": "x",
                "display_name": "X", "description": "d", "origin_scope": "public",
                "origin_owner": "local", "role_body": "smuggled content",
            })
        assert caught.value.code == errors.DEFINITION_INVALID
        assert "role_body" in caught.value.detail


class TestCapacity:
    def test_a_role_body_over_the_cap_is_refused(self) -> None:
        body = "x" * (limits.MAX_ROLE_BODY_BYTES + 1)
        with pytest.raises(errors.DomainError) as caught:
            decoder.decode_revision(revision_mapping(role_body=body))
        assert caught.value.code == errors.DEFINITION_INVALID
        assert str(limits.MAX_ROLE_BODY_BYTES) in caught.value.detail
        assert "x" * 20 not in str(caught.value)

    def test_a_description_over_the_legacy_cap_is_refused(
        self, service: DefinitionService
    ) -> None:
        assert limits.MAX_DESCRIPTION_CHARS == 160
        with pytest.raises(errors.DomainError) as caught:
            service.create_definition(
                PRINCIPAL, server_scope=SERVER_SCOPE, slug="long-desc",
                display_name="Long description", description="d" * 161,
                origin_scope="public", origin_owner="local", operation_key="u:long-desc",
            )
        assert caught.value.code == errors.DEFINITION_INVALID
        assert caught.value.item_id == "description"

    def test_a_slug_over_the_cap_or_off_the_pattern_is_refused(
        self, service: DefinitionService
    ) -> None:
        for slug in ("A" + "a" * 64, "CodeReviewer", "../escape", "with space", ""):
            with pytest.raises(errors.DomainError) as caught:
                service.create_definition(
                    PRINCIPAL, server_scope=SERVER_SCOPE, slug=slug,
                    display_name="Slug probe", description="Pattern check.",
                    origin_scope="public", origin_owner="local",
                    operation_key=f"u:slug-{abs(hash(slug))}",
                )
            assert caught.value.code == errors.DEFINITION_INVALID, slug
            assert caught.value.item_id == "slug", slug

    def test_a_reference_list_over_its_cap_is_refused(self) -> None:
        refs = [{"owner_id": f"Tool{index}"} for index in range(limits.MAX_TOOL_REFS + 1)]
        with pytest.raises(errors.DomainError) as caught:
            decoder.decode_revision(revision_mapping(tool_refs=refs))
        assert caught.value.item_id == "tool_refs"
        assert str(limits.MAX_TOOL_REFS) in caught.value.detail

    def test_a_reference_list_at_its_cap_is_accepted(self) -> None:
        refs = [{"owner_id": f"Tool{index}"} for index in range(limits.MAX_TOOL_REFS)]
        revision = decoder.decode_revision(revision_mapping(tool_refs=refs))
        assert len(revision.tool_refs) == limits.MAX_TOOL_REFS

    def test_an_aggregate_description_budget_is_enforced(
        self, service: DefinitionService
    ) -> None:
        filler = "d" * limits.MAX_DESCRIPTION_CHARS
        filled = limits.MAX_AGGREGATE_DESCRIPTION_BYTES // len(filler)
        for index in range(filled):
            service.create_definition(
                PRINCIPAL, server_scope=SERVER_SCOPE, slug=f"bulk-{index}",
                display_name=f"Bulk {index}", description=filler,
                origin_scope="public", origin_owner="local",
                operation_key=f"u:bulk-{index}",
            )
        with pytest.raises(errors.DomainError) as caught:
            service.create_definition(
                PRINCIPAL, server_scope=SERVER_SCOPE, slug="bulk-final",
                display_name="Bulk final", description=filler,
                origin_scope="public", origin_owner="local", operation_key="u:bulk-final",
            )
        assert caught.value.code == errors.DEFINITION_INVALID
        assert caught.value.item_id == "aggregate_description"
        assert len(service.list_definitions()) == filled

    def test_an_aggregate_count_budget_is_enforced(
        self, service: DefinitionService
    ) -> None:
        for index in range(limits.MAX_ENABLED_DEFINITIONS):
            service.create_definition(
                PRINCIPAL, server_scope=SERVER_SCOPE, slug=f"count-{index}",
                display_name=f"Count {index}", description="short",
                origin_scope="public", origin_owner="local",
                operation_key=f"u:count-{index}",
            )
        with pytest.raises(errors.DomainError) as caught:
            service.create_definition(
                PRINCIPAL, server_scope=SERVER_SCOPE, slug="count-final",
                display_name="Count final", description="short",
                origin_scope="public", origin_owner="local", operation_key="u:count-final",
            )
        assert caught.value.item_id == "aggregate_count"


class TestEncoding:
    @pytest.mark.parametrize("body, item_part", [
        ("review\x00code", "NUL"),
        ("review\x07code", "control character"),
        ("review\u0085code", "control character"),
        ("review\ud800code", "surrogate"),
        ("review\ufffdcode", "lossy"),
        ("review\ufffecode", "non-character"),
    ])
    def test_an_undecodable_or_lossy_body_is_refused(self, body: str, item_part: str) -> None:
        with pytest.raises(errors.DomainError) as caught:
            decoder.decode_revision(revision_mapping(role_body=body))
        assert caught.value.code == errors.DEFINITION_INVALID
        assert item_part in caught.value.detail

    def test_a_body_that_would_not_round_trip_byte_identically_is_refused(
        self, tmp_path
    ) -> None:
        raw = b"review \xff\xfe code"
        lossy = raw.decode("utf-8", errors="replace")
        assert lossy.encode("utf-8") != raw
        with pytest.raises(errors.DomainError) as caught:
            decoder.decode_revision(revision_mapping(role_body=lossy))
        assert caught.value.code == errors.DEFINITION_INVALID

    def test_a_multiline_unicode_body_round_trips_byte_identically(
        self, service: DefinitionService, definition: dto.AgentDefinition, tmp_path
    ) -> None:
        body = "审阅代码。\n\nQuote «verbatim» — emoji ✅ tab\there."
        publish(service, definition, 1, role_body=body)
        path = tmp_path / "store-root" / "definitions" / definition.definition_id \
            / "revisions" / "1.json"
        stored = json.loads(path.read_text(encoding="utf-8"))
        assert stored["role_body"] == body
        assert service.get_revision(definition.definition_id, 1).role_body == body


class TestReferenceDeclarations:
    @pytest.mark.parametrize("owner_id", [
        "/etc/passwd", "./local-tool", "~/bin/tool", "../escape", "C:\\tools\\x",
        "https://example.test/tool", "sh -c 'rm -rf /'",
    ])
    def test_a_path_shaped_reference_is_refused(self, owner_id: str) -> None:
        with pytest.raises(errors.DomainError) as caught:
            decoder.decode_revision(revision_mapping(tool_refs=[{"owner_id": owner_id}]))
        assert caught.value.code == errors.DEFINITION_INVALID
        assert caught.value.item_id.startswith("tool_refs[0]")

    @pytest.mark.parametrize("owner_id", ["api_key", "AUTH_TOKEN", "my-secret-key"])
    def test_a_credential_shaped_reference_is_refused(self, owner_id: str) -> None:
        with pytest.raises(errors.DomainError) as caught:
            decoder.decode_revision(revision_mapping(mcp_refs=[{"owner_id": owner_id}]))
        assert caught.value.code == errors.PERMISSION_EXCEEDS_CEILING

    def test_a_reference_revision_must_be_a_pinned_token(self) -> None:
        with pytest.raises(errors.DomainError) as caught:
            decoder.decode_revision(revision_mapping(
                skill_refs=[{"owner_id": "review-notes", "revision": "latest / main"}],
            ))
        assert caught.value.code == errors.DEFINITION_INVALID

    def test_a_pinned_reference_round_trips(self) -> None:
        revision = decoder.decode_revision(revision_mapping(
            declared_model_ref={"owner_id": "claude-sonnet", "revision": "2026-09-01"},
            tool_refs=[{"owner_id": "Read", "revision": None}],
        ))
        assert revision.declared_model_ref == dto.ModelRef("claude-sonnet", "2026-09-01")
        assert revision.tool_refs == (dto.ToolRef("Read", None),)


class TestSourceApproval:
    def test_a_git_source_without_a_full_commit_id_is_refused(self) -> None:
        for ref in ("org/repo@main", "org/repo@0a1b2c3", "org/repo@" + "0" * 40 + "abc",
                    "org/repo@HEAD"):
            with pytest.raises(errors.DomainError) as caught:
                decoder.decode_revision(revision_mapping(source=dto.SourceApproval(
                    origin="git-revision", origin_ref=ref,
                    content_digest="sha256:" + "1" * 64,
                    approved_by_principal=PRINCIPAL, approved_at="2026-09-28T10:00:00+00:00",
                )))
            assert caught.value.code == errors.DEFINITION_INVALID, ref
            assert "commit id" in caught.value.detail

    def test_a_git_source_with_a_pinned_revision_is_kept(self) -> None:
        revision = decoder.decode_revision(revision_mapping(
            source=dto.SourceApproval(
                origin="git-revision",
                origin_ref="org/repo@" + "a" * 38 + "ef#agents/reviewer.md",
                content_digest="sha256:" + "1" * 64,
                approved_by_principal=PRINCIPAL,
                approved_at="2026-09-28T10:00:00+00:00",
            ),
        ))
        assert revision.source.origin == "git-revision"

    def test_an_unknown_origin_is_refused(self) -> None:
        with pytest.raises(errors.DomainError) as caught:
            decoder.decode_revision(revision_mapping(source=dto.SourceApproval(
                origin="downloaded", origin_ref="somewhere",
                content_digest="sha256:" + "1" * 64,
                approved_by_principal=PRINCIPAL, approved_at="2026-09-28T10:00:00+00:00",
            )))
        assert caught.value.item_id == "source"

    def test_an_approval_by_another_principal_is_refused_before_a_write(
        self, service: DefinitionService, definition: dto.AgentDefinition, tmp_path
    ) -> None:
        revision = make_revision(definition.definition_id, 1, source=approval(
            approved_by_principal="u:whoever",
        ))
        with pytest.raises(errors.DomainError) as caught:
            service.save_revision(
                PRINCIPAL, revision, server_scope=SERVER_SCOPE,
                operation_key="u:not-my-approval", expected_row_version=1,
            )
        assert caught.value.code == errors.PERMISSION_EXCEEDS_CEILING
        assert not (tmp_path / "store-root" / "definitions" / definition.definition_id
                    / "revisions" / "1.json").exists()

    def test_an_approval_covering_other_content_is_refused(
        self, service: DefinitionService, definition: dto.AgentDefinition
    ) -> None:
        revision = make_revision(definition.definition_id, 1)
        stale = dto.SourceApproval(**{
            **vars(revision.source), "content_digest": "sha256:" + "b" * 64,
        })
        tampered = dto.DefinitionRevision(**{**vars(revision), "source": None})
        with pytest.raises(errors.DomainError):
            decoder.validate_revision(tampered)
        held = dto.DefinitionRevision(**{
            **vars(revision), "source": stale,
            "content_digest": "sha256:" + "0" * 64,
        })
        from ordessa_assets_subagents.digest import revision_digest

        held = dto.DefinitionRevision(**{**vars(held),
                                         "content_digest": revision_digest(held)})
        with pytest.raises(errors.DomainError) as caught:
            service.save_revision(
                PRINCIPAL, held, server_scope=SERVER_SCOPE,
                operation_key="u:stale-approval", expected_row_version=1,
            )
        assert caught.value.code == errors.DEFINITION_INVALID
        assert caught.value.item_id == "source.content_digest"


class TestPermissionCeiling:
    def test_a_declaration_above_the_ceiling_is_refused(
        self, service: DefinitionService, definition: dto.AgentDefinition
    ) -> None:
        with pytest.raises(errors.DomainError) as caught:
            publish(service, definition, 1, requested_permission="shell")
        assert caught.value.code == errors.PERMISSION_EXCEEDS_CEILING
        assert caught.value.item_id == "requested_permission"
        assert service.get_definition(definition.definition_id).latest_revision == 0

    def test_a_declaration_inside_the_ceiling_is_stored_as_a_declaration(
        self, service: DefinitionService, definition: dto.AgentDefinition
    ) -> None:
        published = publish(service, definition, 1, requested_permission="read-only")
        assert published.requested_permission == "read-only"
        assert service.get_revision(definition.definition_id, 1) == published

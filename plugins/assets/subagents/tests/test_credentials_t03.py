"""G05 negative column / FR14 — a credential never enters a definition or a log."""
from __future__ import annotations

from pathlib import Path

import pytest

from conftest import PRINCIPAL, SERVER_SCOPE, approval, document, make_revision, publish
from ordessa_assets_subagents import decoder, dto, errors, limits
from ordessa_assets_subagents.service import DefinitionService

SECRET = "sk-abcdef0123456789abcdef01"
def store_bytes(store_root: Path) -> bytes:
    return b"".join(
        path.read_bytes() for path in sorted(store_root.rglob("*")) if path.is_file()
    )


class TestCredentialRefusals:
    @pytest.mark.parametrize("field, value", [
        ("role_body", f"Always send the api_key: {SECRET} header."),
        ("role_body", f"token = {SECRET}"),
        ("role_body", "-----BEGIN RSA PRIVATE KEY-----\nMIIB\n"),
        ("role_body", "use Bearer " + "abcDEF0123456789_-xyz"),
        ("role_body", "the AKIA0A1B2C3D4E5F6078 account"),
    ])
    def test_a_credential_shaped_body_is_refused(
        self, service: DefinitionService, definition: dto.AgentDefinition,
        tmp_path: Path, field: str, value: str,
    ) -> None:
        with pytest.raises(errors.DomainError) as caught:
            publish(service, definition, 1, **{field: value})
        assert caught.value.code == errors.PERMISSION_EXCEEDS_CEILING
        assert SECRET not in str(caught.value)
        assert not (tmp_path / "store-root" / "definitions" / definition.definition_id
                    / "revisions" / "1.json").exists()

    def test_a_credential_in_a_retained_native_field_is_refused(
        self, service: DefinitionService, definition: dto.AgentDefinition, tmp_path: Path
    ) -> None:
        held = {"mcpServers": [{"apiKey": SECRET}]}
        with pytest.raises(errors.DomainError) as caught:
            publish(service, definition, 1, retained_native_fields=held)
        assert caught.value.code == errors.PERMISSION_EXCEEDS_CEILING
        assert SECRET not in str(caught.value)
        assert store_bytes(tmp_path / "store-root").count(SECRET.encode()) == 0

    def test_a_credential_shaped_key_is_refused_even_without_a_value(
        self, service: DefinitionService, definition: dto.AgentDefinition
    ) -> None:
        with pytest.raises(errors.DomainError) as caught:
            publish(service, definition, 1, retained_native_fields={"auth_token": "unset"})
        assert caught.value.code == errors.PERMISSION_EXCEEDS_CEILING

    def test_a_credential_in_the_description_is_refused(
        self, service: DefinitionService
    ) -> None:
        with pytest.raises(errors.DomainError) as caught:
            service.create_definition(
                PRINCIPAL, server_scope=SERVER_SCOPE, slug="leaky",
                display_name="Leaky", description=f"uses api_key: {SECRET[:20]}",
                origin_scope="public", origin_owner="local", operation_key="u:leaky",
            )
        assert caught.value.code == errors.PERMISSION_EXCEEDS_CEILING
        assert SECRET[:20] not in str(caught.value)

    def test_a_prose_mention_of_a_secret_word_still_saves(
        self, service: DefinitionService, definition: dto.AgentDefinition
    ) -> None:
        published = publish(
            service, definition, 1,
            role_body="Budget the token count and keep the review focused.",
        )
        assert "token" in published.role_body

    def test_a_credential_shaped_reference_owner_is_refused(
        self, service: DefinitionService, definition: dto.AgentDefinition
    ) -> None:
        for kind in ("tool_refs", "mcp_refs", "skill_refs"):
            with pytest.raises(errors.DomainError) as caught:
                publish(service, definition, 1, **{
                    kind: [dto.ToolRef(owner_id=f"ghp_{ 'A' * 20 }")]
                    if kind == "tool_refs" else
                    [dto.McpRef(owner_id="access_key_primary")] if kind == "mcp_refs" else
                    [dto.SkillRef(owner_id="client-secret")]})
            assert caught.value.code == errors.PERMISSION_EXCEEDS_CEILING, kind

    def test_a_credential_in_an_imported_document_never_reaches_storage(
        self, service: DefinitionService, import_root: Path, tmp_path: Path
    ) -> None:
        (import_root / "leaky.md").write_text(
            document(body=f"Read the config.\napi_key: {SECRET}\n"), encoding="utf-8",
        )
        preview = service.import_preview(import_root, import_root=import_root)
        assert {entry.relative_path for entry in preview.files if entry.selectable} == set()
        assert any(entry.diagnostics for entry in preview.files)
        with pytest.raises(errors.DomainError) as caught:
            service.approve_import(
                preview.preview_id, principal=PRINCIPAL, server_scope=SERVER_SCOPE,
                selects=["leaky.md"], operation_key="u:approve-leaky",
            )
        assert caught.value.code == errors.PERMISSION_EXCEEDS_CEILING
        assert SECRET not in str(caught.value)
        if (tmp_path / "store-root").exists():
            assert store_bytes(tmp_path / "store-root").count(SECRET.encode()) == 0

    def test_the_raised_error_carries_no_rejected_value(
        self, service: DefinitionService, definition: dto.AgentDefinition
    ) -> None:
        body = f"api_key: {SECRET}"
        with pytest.raises(errors.DomainError) as caught:
            publish(service, definition, 1, role_body=body)
        error = caught.value
        assert SECRET not in str(error)
        assert SECRET not in repr(error)
        assert SECRET not in (error.detail or "")
        assert SECRET not in (error.item_id or "")
        assert error.item_id == "role_body"

    def test_no_stored_definition_holds_a_credential_shaped_field(
        self, service: DefinitionService, definition: dto.AgentDefinition, tmp_path: Path
    ) -> None:
        published = publish(
            service, definition, 1,
            declared_model_ref=dto.ModelRef("claude-sonnet", "2026-09-01"),
            tool_refs=[dto.ToolRef("Read")],
            limits={"max_output_tokens": 4096},
        )
        assert published.requested_permission is None
        stored = store_bytes(tmp_path / "store-root")
        assert b"api_key" not in stored
        assert SECRET.encode() not in stored

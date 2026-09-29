"""Each refusal is attributable: remove the guard and the bad write lands.

These tests exist so the suite cannot go fake-green when a guard is deleted.
Every case names the guard, disables it, and shows the exact effect the guard
was preventing.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import (PRINCIPAL, SERVER_SCOPE, document, make_revision,
                      publish, revision_mapping)
from ordessa_assets_subagents import decoder, digest, dto, errors, limits
from ordessa_assets_subagents import service as service_module
from ordessa_assets_subagents import store as store_module
from ordessa_assets_subagents.service import DefinitionService

SECRET = "sk-abcdef0123456789abcdef01"


def revision_file(store_root: Path, definition_id: str, revision: int) -> Path:
    return store_root / "definitions" / definition_id / "revisions" / f"{revision}.json"


class TestCapacityGuards:
    def test_the_role_body_cap_is_what_refuses(
        self, service: DefinitionService, definition: dto.AgentDefinition, monkeypatch
    ) -> None:
        body = "x" * (limits.MAX_ROLE_BODY_BYTES + 1)
        with pytest.raises(errors.DomainError):
            publish(service, definition, 1, role_body=body)
        monkeypatch.setattr(limits, "MAX_ROLE_BODY_BYTES", 8 * limits.MAX_ROLE_BODY_BYTES)
        published = publish(
            service, definition, 1, role_body=body, operation_key="u:no-body-cap",
        )
        assert len(published.role_body) == len(body)

    def test_the_description_cap_is_what_refuses(
        self, service: DefinitionService, monkeypatch
    ) -> None:
        long_description = "d" * 161
        with pytest.raises(errors.DomainError):
            service.create_definition(
                PRINCIPAL, server_scope=SERVER_SCOPE, slug="capped",
                display_name="Capped", description=long_description,
                origin_scope="public", origin_owner="local", operation_key="u:cap-desc",
            )
        monkeypatch.setattr(limits, "MAX_DESCRIPTION_CHARS", 4096)
        row = service.create_definition(
            PRINCIPAL, server_scope=SERVER_SCOPE, slug="capped",
            display_name="Capped", description=long_description,
            origin_scope="public", origin_owner="local", operation_key="u:cap-desc-2",
        )
        assert row.description == long_description

    def test_the_reference_count_cap_is_what_refuses(self) -> None:
        refs = [dto.ToolRef(f"Tool{index}") for index in range(limits.MAX_TOOL_REFS + 1)]
        with pytest.raises(errors.DomainError) as caught:
            decoder._check_refs(refs, item="tool_refs", expected_kind=dto.ToolRef,
                                max_entries=limits.MAX_TOOL_REFS)
        assert str(limits.MAX_TOOL_REFS) in caught.value.detail
        kept = decoder._check_refs(refs, item="tool_refs", expected_kind=dto.ToolRef,
                                   max_entries=len(refs))
        assert len(kept) == len(refs)

    def test_the_aggregate_budget_is_what_refuses(
        self, service: DefinitionService, monkeypatch
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
        with pytest.raises(errors.DomainError):
            service.create_definition(
                PRINCIPAL, server_scope=SERVER_SCOPE, slug="bulk-final",
                display_name="Bulk final", description=filler,
                origin_scope="public", origin_owner="local", operation_key="u:bulk-final",
            )
        monkeypatch.setattr(DefinitionService, "_check_aggregate_budget",
                            lambda self, incoming: None)
        service.create_definition(
            PRINCIPAL, server_scope=SERVER_SCOPE, slug="bulk-final",
            display_name="Bulk final", description=filler,
            origin_scope="public", origin_owner="local", operation_key="u:bulk-final-2",
        )
        assert len(service.list_definitions()) == filled + 1


class TestRetentionGuard:
    def test_disabling_retention_lets_an_unknown_field_vanish_silently(
        self, monkeypatch
    ) -> None:
        mapping = revision_mapping(permissionMode="acceptEdits")
        held = decoder.decode_revision(mapping)
        assert held.retained_native_fields == {"permissionMode": "acceptEdits"}
        assert decoder.is_compilable(held) is False

        monkeypatch.setattr(decoder, "_check_retained", lambda value, *, item: {})
        dropped = decoder.decode_revision(mapping)
        assert dropped.retained_native_fields == {}
        assert decoder.is_compilable(dropped) is True, (
            "without the retention guard an unmapped field reads as applied"
        )


class TestImmutabilityAndCasGuards:
    def test_a_non_exclusive_publish_rewrites_an_old_revision(
        self, service: DefinitionService, definition: dto.AgentDefinition, tmp_path: Path,
        monkeypatch,
    ) -> None:
        publish(service, definition, 1, role_body="first body")
        path = revision_file(tmp_path / "store-root", definition.definition_id, 1)
        before = path.read_bytes()
        monkeypatch.setattr(store_module, "_write_exclusive",
                            lambda path, payload, *, read_only=False:
                            store_module._write_atomic(path, payload))
        service.store.write_revision(make_revision(
            definition.definition_id, 1, role_body="rewritten history",
        ))
        assert path.read_bytes() != before
        assert b"rewritten history" in path.read_bytes()

    def test_without_the_validator_a_forged_digest_is_stored(
        self, service: DefinitionService, definition: dto.AgentDefinition, tmp_path: Path,
        monkeypatch,
    ) -> None:
        honest = make_revision(definition.definition_id, 1, role_body="approved body")
        forged = dto.DefinitionRevision(**{
            **vars(honest), "role_body": "content nobody hashed",
        })
        assert forged.content_digest != digest.revision_digest(forged)
        with pytest.raises(errors.DomainError) as caught:
            service.save_revision(
                PRINCIPAL, forged, server_scope=SERVER_SCOPE,
                operation_key="u:forged", expected_row_version=1,
            )
        assert caught.value.item_id == "content_digest"
        assert not revision_file(tmp_path / "store-root", definition.definition_id, 1).exists()
        monkeypatch.setattr(decoder, "validate_revision", lambda revision: revision)
        service.store.write_revision(forged)
        path = revision_file(tmp_path / "store-root", definition.definition_id, 1)
        assert b"content nobody hashed" in path.read_bytes()
        stored = json.loads(path.read_text(encoding="utf-8"))
        assert stored["content_digest"] != digest.revision_digest(
            dto.DefinitionRevision(**stored)
        ), "the guard was the only thing keeping a mismatched digest off disk"

    def test_the_witness_and_ceiling_guards_are_the_only_ones_asking(
        self, service: DefinitionService, definition: dto.AgentDefinition, monkeypatch
    ) -> None:
        with pytest.raises(errors.DomainError) as caught:
            publish(service, definition, 1,
                    requested_permission="shell", operation_key="u:ceiling")
        assert caught.value.code == errors.PERMISSION_EXCEEDS_CEILING
        monkeypatch.setattr(DefinitionService, "_check_permission_ceiling",
                            lambda self, principal, server_scope, revision: None)
        monkeypatch.setattr(DefinitionService, "_check_source_is_witnessed",
                            lambda self, principal, revision: None)
        published = publish(
            service, definition, 1, requested_permission="shell",
            role_body="another body entirely", operation_key="u:no-guards",
        )
        assert published.requested_permission == "shell"


class TestCredentialGuard:
    def test_disabling_the_scan_stores_the_secret_verbatim(
        self, service: DefinitionService, definition: dto.AgentDefinition, tmp_path: Path,
        monkeypatch,
    ) -> None:
        body = f"api_key: {SECRET}"
        with pytest.raises(errors.DomainError):
            publish(service, definition, 1, role_body=body)
        monkeypatch.setattr(decoder, "has_credential_shape", lambda value: False)
        monkeypatch.setattr(decoder, "is_credential_named", lambda value: False)
        publish(service, definition, 1, role_body=body, operation_key="u:no-scan")
        stored = revision_file(tmp_path / "store-root", definition.definition_id, 1)
        assert SECRET.encode() in stored.read_bytes()


class TestImportPathGuards:
    def test_the_containment_gate_is_what_blocks_an_outside_read(
        self, service: DefinitionService, import_root: Path, tmp_path: Path, monkeypatch
    ) -> None:
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        (outside / "secret.md").write_text(document(name="outside"), encoding="utf-8")
        with pytest.raises(errors.DomainError):
            service.import_preview(outside / "secret.md", import_root=import_root)
        monkeypatch.setattr(service_module, "_inside",
                            lambda root, target, *, label: Path(target).resolve())
        preview = service.import_preview(outside / "secret.md", import_root=import_root)
        assert [entry.relative_path for entry in preview.files] == ["secret.md"], (
            "without the gate an arbitrary host path reaches a server-side read"
        )

    def test_the_include_and_remote_scans_are_what_refuse_a_fetch(
        self, service: DefinitionService, import_root: Path, monkeypatch
    ) -> None:
        (import_root / "fetch.md").write_text(
            document(name="fetch", body="![[more.md]] https://example.test/x"),
            encoding="utf-8",
        )
        preview = service.import_preview(import_root, import_root=import_root)
        assert preview.files and all(not entry.selectable for entry in preview.files)
        monkeypatch.setattr(service_module, "_unsafe_directive", lambda text: None)
        reopened = service.import_preview(import_root, import_root=import_root)
        assert any(entry.selectable for entry in reopened.files), (
            "without the directive scan an include or URL would be followed"
        )

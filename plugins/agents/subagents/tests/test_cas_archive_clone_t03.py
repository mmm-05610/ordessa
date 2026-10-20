"""G06 — CAS, idempotency, archive/restore/clone."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import OTHER_PRINCIPAL, PRINCIPAL, SERVER_SCOPE, make_revision, publish
from ordessa_assets_subagents import dto, errors
from ordessa_assets_subagents.service import DefinitionService


def definition_file(store_root: Path, definition_id: str) -> Path:
    return store_root / "definitions" / definition_id / "definition.json"


def revision_file(store_root: Path, definition_id: str, revision: int) -> Path:
    return store_root / "definitions" / definition_id / "revisions" / f"{revision}.json"


def stored_rows(store_root: Path) -> list[Path]:
    return sorted(path for path in (store_root / "definitions").rglob("*.json"))


class TestCompareAndSet:
    def test_a_stale_row_version_refuses_and_writes_nothing(
        self, service: DefinitionService, definition: dto.AgentDefinition, tmp_path: Path
    ) -> None:
        root = tmp_path / "store-root"
        before = definition_file(root, definition.definition_id).read_bytes()
        with pytest.raises(errors.DomainError) as refused:
            service.save_revision(
                PRINCIPAL, make_revision(definition.definition_id, 1),
                server_scope=SERVER_SCOPE, operation_key="u:stale",
                expected_row_version=7,
            )
        assert refused.value.code == errors.REVISION_STALE
        assert definition_file(root, definition.definition_id).read_bytes() == before
        assert not revision_file(root, definition.definition_id, 1).exists()

    def test_a_late_writer_does_not_overwrite_the_current_row(
        self, service: DefinitionService, definition: dto.AgentDefinition
    ) -> None:
        publish(service, definition, 1, operation_key="u:first")
        with pytest.raises(errors.DomainError) as refused:
            service.save_revision(
                PRINCIPAL,
                make_revision(definition.definition_id, 2, role_body="late writer body"),
                server_scope=SERVER_SCOPE, operation_key="u:late",
                expected_row_version=1,
            )
        assert refused.value.code == errors.REVISION_STALE
        row = service.get_definition(definition.definition_id)
        assert (row.latest_revision, row.row_version) == (1, 2)

    def test_archive_with_a_stale_row_version_refuses(
        self, service: DefinitionService, definition: dto.AgentDefinition
    ) -> None:
        with pytest.raises(errors.DomainError) as refused:
            service.archive(
                PRINCIPAL, definition.definition_id, server_scope=SERVER_SCOPE,
                operation_key="u:stale-archive", expected_row_version=42,
            )
        assert refused.value.code == errors.REVISION_STALE
        assert not service.get_definition(definition.definition_id).archived


class TestIdempotency:
    def test_replaying_a_key_returns_the_recorded_result_without_a_second_write(
        self, service: DefinitionService, definition: dto.AgentDefinition, tmp_path: Path
    ) -> None:
        root = tmp_path / "store-root"
        revision = make_revision(definition.definition_id, 1)
        first = service.save_revision(
            PRINCIPAL, revision, server_scope=SERVER_SCOPE,
            operation_key="u:once", expected_row_version=1,
        )
        files = stored_rows(root)
        row_before = definition_file(root, definition.definition_id).read_bytes()
        again = service.save_revision(
            PRINCIPAL, revision, server_scope=SERVER_SCOPE,
            operation_key="u:once", expected_row_version=1,
        )
        assert again == first
        assert stored_rows(root) == files
        assert definition_file(root, definition.definition_id).read_bytes() == row_before
        assert service.get_definition(definition.definition_id).row_version == 2

    def test_the_same_key_with_another_payload_is_refused(
        self, service: DefinitionService, definition: dto.AgentDefinition, tmp_path: Path
    ) -> None:
        service.save_revision(
            PRINCIPAL, make_revision(definition.definition_id, 1, role_body="first body"),
            server_scope=SERVER_SCOPE, operation_key="u:reused", expected_row_version=1,
        )
        with pytest.raises(errors.DomainError) as refused:
            service.save_revision(
                PRINCIPAL, make_revision(definition.definition_id, 1, role_body="other body"),
                server_scope=SERVER_SCOPE, operation_key="u:reused", expected_row_version=2,
            )
        assert refused.value.code == errors.ASSIGNMENT_CONFLICT
        assert service.get_definition(definition.definition_id).latest_revision == 1

    def test_the_receipt_scope_holds_the_principal(
        self, service: DefinitionService, definition: dto.AgentDefinition
    ) -> None:
        from conftest import approval

        service.save_revision(
            PRINCIPAL, make_revision(definition.definition_id, 1),
            server_scope=SERVER_SCOPE, operation_key="u:shared-key", expected_row_version=1,
        )
        theirs = service.save_revision(
            OTHER_PRINCIPAL,
            make_revision(
                definition.definition_id, 2, role_body="another principal's body",
                source=approval(approved_by_principal=OTHER_PRINCIPAL),
            ),
            server_scope=SERVER_SCOPE, operation_key="u:shared-key", expected_row_version=2,
        )
        assert theirs.revision == 2
        assert service.get_definition(definition.definition_id).latest_revision == 2

    def test_another_principal_may_not_publish_content_it_never_approved(
        self, service: DefinitionService, definition: dto.AgentDefinition
    ) -> None:
        with pytest.raises(errors.DomainError) as refused:
            service.save_revision(
                OTHER_PRINCIPAL, make_revision(definition.definition_id, 1),
                server_scope=SERVER_SCOPE, operation_key="u:impersonate",
                expected_row_version=1,
            )
        assert refused.value.code == errors.PERMISSION_EXCEEDS_CEILING
        assert service.get_definition(definition.definition_id).latest_revision == 0

    def test_a_mutation_without_an_operation_key_is_refused(
        self, service: DefinitionService, definition: dto.AgentDefinition
    ) -> None:
        with pytest.raises(errors.DomainError) as refused:
            service.save_revision(
                PRINCIPAL, make_revision(definition.definition_id, 1),
                server_scope=SERVER_SCOPE, operation_key="", expected_row_version=1,
            )
        assert refused.value.code == errors.DEFINITION_INVALID
        assert refused.value.item_id == "operation_key"

    def test_replaying_a_duplicate_archive_is_one_effect(
        self, service: DefinitionService, definition: dto.AgentDefinition
    ) -> None:
        first = service.archive(
            PRINCIPAL, definition.definition_id, server_scope=SERVER_SCOPE,
            operation_key="u:archive-once", expected_row_version=1,
        )
        replay = service.archive(
            PRINCIPAL, definition.definition_id, server_scope=SERVER_SCOPE,
            operation_key="u:archive-once", expected_row_version=1,
        )
        assert replay == first
        assert service.get_definition(definition.definition_id).row_version == 2

    def test_replaying_a_clone_does_not_create_a_second_definition(
        self, service: DefinitionService, definition: dto.AgentDefinition
    ) -> None:
        publish(service, definition, 1)
        row = service.get_definition(definition.definition_id)
        cloned = service.clone(
            PRINCIPAL, definition.definition_id, server_scope=SERVER_SCOPE,
            operation_key="u:clone-once", expected_row_version=row.row_version,
        )
        again = service.clone(
            PRINCIPAL, definition.definition_id, server_scope=SERVER_SCOPE,
            operation_key="u:clone-once", expected_row_version=row.row_version,
        )
        assert again == cloned
        assert len(service.list_definitions(include_archived=True)) == 2


class TestArchiveAndClone:
    def test_archive_hides_from_listing_but_keeps_frozen_references(
        self, service: DefinitionService, definition: dto.AgentDefinition
    ) -> None:
        published = publish(service, definition, 1)
        service.archive(
            PRINCIPAL, definition.definition_id, server_scope=SERVER_SCOPE,
            operation_key="u:archive", expected_row_version=2,
        )
        assert service.list_definitions() == []
        assert [row.slug for row in service.list_definitions(include_archived=True)] == [
            definition.slug,
        ]
        assert service.get_revision(definition.definition_id, 1) == published
        assert service.latest_revision(definition.definition_id) == published

    def test_an_archived_definition_takes_no_new_revision(
        self, service: DefinitionService, definition: dto.AgentDefinition
    ) -> None:
        service.archive(
            PRINCIPAL, definition.definition_id, server_scope=SERVER_SCOPE,
            operation_key="u:archive", expected_row_version=1,
        )
        with pytest.raises(errors.DomainError) as refused:
            service.save_revision(
                PRINCIPAL, make_revision(definition.definition_id, 1),
                server_scope=SERVER_SCOPE, operation_key="u:while-archived",
                expected_row_version=2,
            )
        assert refused.value.code == errors.ASSIGNMENT_CONFLICT

    def test_restore_brings_the_definition_back(
        self, service: DefinitionService, definition: dto.AgentDefinition
    ) -> None:
        publish(service, definition, 1)
        service.archive(
            PRINCIPAL, definition.definition_id, server_scope=SERVER_SCOPE,
            operation_key="u:archive", expected_row_version=2,
        )
        restored = service.restore(
            PRINCIPAL, definition.definition_id, server_scope=SERVER_SCOPE,
            operation_key="u:restore", expected_row_version=3,
        )
        assert not restored.archived
        assert [row.definition_id for row in service.list_definitions()] == [
            definition.definition_id,
        ]
        published = service.save_revision(
            PRINCIPAL, make_revision(definition.definition_id, 2),
            server_scope=SERVER_SCOPE, operation_key="u:after-restore",
            expected_row_version=4,
        )
        assert published.revision == 2

    def test_double_archive_with_another_key_is_one_state_change(
        self, service: DefinitionService, definition: dto.AgentDefinition
    ) -> None:
        service.archive(
            PRINCIPAL, definition.definition_id, server_scope=SERVER_SCOPE,
            operation_key="u:archive-a", expected_row_version=1,
        )
        with pytest.raises(errors.DomainError) as refused:
            service.archive(
                PRINCIPAL, definition.definition_id, server_scope=SERVER_SCOPE,
                operation_key="u:archive-b", expected_row_version=2,
            )
        assert refused.value.code == errors.ASSIGNMENT_CONFLICT

    def test_clone_is_a_new_id_at_revision_one_with_its_own_storage(
        self, service: DefinitionService, definition: dto.AgentDefinition, tmp_path: Path
    ) -> None:
        root = tmp_path / "store-root"
        published = publish(service, definition, 1, role_body="Cloned body.")
        row = service.get_definition(definition.definition_id)
        cloned = service.clone(
            PRINCIPAL, definition.definition_id, server_scope=SERVER_SCOPE,
            operation_key="u:clone", expected_row_version=row.row_version,
        )
        assert cloned.definition_id != definition.definition_id
        assert (cloned.latest_revision, cloned.row_version) == (1, 1)
        clone_file = revision_file(root, cloned.definition_id, 1)
        source_file = revision_file(root, definition.definition_id, 1)
        assert clone_file.exists() and clone_file != source_file
        before = source_file.read_bytes()
        assert service.get_revision(cloned.definition_id, 1).role_body == "Cloned body."
        assert source_file.read_bytes() == before

    def test_a_later_revision_of_a_clone_leaves_the_source_bytes_alone(
        self, service: DefinitionService, definition: dto.AgentDefinition, tmp_path: Path
    ) -> None:
        root = tmp_path / "store-root"
        published = publish(service, definition, 1, role_body="Source body.")
        source_file = revision_file(root, definition.definition_id, 1)
        source_bytes = source_file.read_bytes()
        row = service.get_definition(definition.definition_id)
        cloned = service.clone(
            PRINCIPAL, definition.definition_id, server_scope=SERVER_SCOPE,
            operation_key="u:clone", expected_row_version=row.row_version,
        )
        service.save_revision(
            PRINCIPAL,
            make_revision(cloned.definition_id, 2, role_body="Clone-only edit."),
            server_scope=SERVER_SCOPE, operation_key="u:clone-edit",
            expected_row_version=1,
        )
        assert source_file.read_bytes() == source_bytes
        assert service.get_definition(definition.definition_id).latest_revision == 1
        assert published.revision == 1

    def test_cloning_a_definition_without_content_is_refused(
        self, service: DefinitionService, definition: dto.AgentDefinition
    ) -> None:
        with pytest.raises(errors.DomainError) as refused:
            service.clone(
                PRINCIPAL, definition.definition_id, server_scope=SERVER_SCOPE,
                operation_key="u:clone-empty", expected_row_version=1,
            )
        assert refused.value.code == errors.DEFINITION_INVALID
        assert len(service.list_definitions()) == 1

    def test_an_unknown_definition_target_is_reported_as_unknown(
        self, service: DefinitionService
    ) -> None:
        with pytest.raises(errors.DomainError) as refused:
            service.archive(
                PRINCIPAL, "def_missing0000000000000000", server_scope=SERVER_SCOPE,
                operation_key="u:archive-missing", expected_row_version=1,
            )
        assert refused.value.code == errors.DEFINITION_INVALID


class TestCrossSliceBoundary:
    @pytest.mark.parametrize("method", ["resolve_preview", "approve_assignment_update",
                                        "inspect_native"])
    def test_surface_owned_by_another_task_is_not_fake_implemented(
        self, service: DefinitionService, method: str
    ) -> None:
        with pytest.raises(NotImplementedError):
            getattr(service, method)(target="anything")


class TestStoredShapes:
    def test_a_stored_revision_round_trips_through_the_strict_decoder(
        self, service: DefinitionService, definition: dto.AgentDefinition
    ) -> None:
        published = publish(service, definition, 1, tool_refs=[dto.ToolRef("Read")])
        read_back = service.get_revision(definition.definition_id, 1)
        assert read_back == published

    def test_the_store_holds_no_dispatch_tables(
        self, service: DefinitionService, definition: dto.AgentDefinition, tmp_path: Path
    ) -> None:
        publish(service, definition, 1)
        names = {path.name for path in (tmp_path / "store-root").rglob("*")}
        for legacy in ("grant_edges", "roster", "run_subagent", "subagent_grants"):
            assert legacy not in names
        payloads = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in (tmp_path / "store-root").rglob("*.json")
        ]
        assert not [
            payload for payload in payloads
            if {"parent_profile_id", "child_profile_id", "turns_limit"} & set(payload)
        ]

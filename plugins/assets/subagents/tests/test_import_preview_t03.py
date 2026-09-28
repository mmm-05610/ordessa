"""G05 — import preview and separate approval (spec FR01/FR14, US1)."""
from __future__ import annotations

import os
import socket
from pathlib import Path

import pytest

from conftest import PRINCIPAL, SERVER_SCOPE, document, make_revision
from ordessa_assets_subagents import decoder, digest, dto, errors, limits
from ordessa_assets_subagents.service import DefinitionService


def write(root: Path, name: str, text: str) -> Path:
    target = root / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    return target


def selectable(preview: dto.ImportPreview) -> set[str]:
    return {entry.relative_path for entry in preview.files if entry.selectable}


class TestPreview:
    def test_a_preview_reports_each_file_with_its_digest_and_format(
        self, service: DefinitionService, import_root: Path
    ) -> None:
        write(import_root, "reviewer.md", document())
        preview = service.import_preview(import_root, import_root=import_root)
        entry = next(item for item in preview.files if item.relative_path == "reviewer.md")
        assert entry.selectable is True
        assert entry.declared_slug == "code-reviewer"
        assert entry.content_digest == digest.bytes_digest(
            (import_root / "reviewer.md").read_bytes()
        )
        assert entry.diagnostics == ()

    def test_a_preview_writes_nothing_and_executes_nothing(
        self, service: DefinitionService, import_root: Path, tmp_path: Path
    ) -> None:
        write(import_root, "reviewer.md", document())
        before = sorted(os.listdir(tmp_path))
        service.import_preview(import_root, import_root=import_root)
        assert sorted(os.listdir(tmp_path)) == before
        assert not (tmp_path / "store-root").exists()
        assert service.list_definitions() == []

    def test_a_non_document_file_is_reported_but_never_applied(
        self, service: DefinitionService, import_root: Path
    ) -> None:
        write(import_root, "notes.txt", "just prose, no frontmatter")
        preview = service.import_preview(import_root, import_root=import_root)
        assert selectable(preview) == set()
        assert any("frontmatter" in line for line in preview.diagnostics)

    def test_a_file_beyond_the_body_cap_is_reported(
        self, service: DefinitionService, import_root: Path
    ) -> None:
        write(import_root, "huge.md", document(body="x" * (limits.MAX_ROLE_BODY_BYTES + 1)))
        preview = service.import_preview(import_root, import_root=import_root)
        assert selectable(preview) == set()
        assert any(str(limits.MAX_ROLE_BODY_BYTES) in line for line in preview.diagnostics)

    def test_an_unmapped_frontmatter_field_is_retained_and_not_compilable(
        self, service: DefinitionService, import_root: Path
    ) -> None:
        write(import_root, "reviewer.md", document(extra="hooks: run-notify"))
        preview = service.import_preview(import_root, import_root=import_root)
        assert selectable(preview) == {"reviewer.md"}
        assert any("hooks" in line for line in preview.diagnostics)
        (definition,) = service.approve_import(
            preview.preview_id, principal=PRINCIPAL, server_scope=SERVER_SCOPE,
            selects=["reviewer.md"], operation_key="u:import-hooks",
        )
        revision = service.get_revision(definition.definition_id, 1)
        assert revision.retained_native_fields["hooks"] == "run-notify"
        assert decoder.is_compilable(revision) is False
        assert service.is_compilable(definition.definition_id, 1) is False


class TestPathSafety:
    def test_a_source_outside_the_approved_root_is_refused(
        self, service: DefinitionService, import_root: Path, tmp_path: Path
    ) -> None:
        outside = write(tmp_path / "elsewhere", "secret.md", document(name="outside"))
        with pytest.raises(errors.DomainError) as caught:
            service.import_preview(outside, import_root=import_root)
        assert caught.value.code == errors.DEFINITION_INVALID
        assert "escapes" in caught.value.detail

    def test_a_relative_escape_is_refused(
        self, service: DefinitionService, import_root: Path, tmp_path: Path
    ) -> None:
        write(tmp_path, "escape.md", document(name="escape"))
        with pytest.raises(errors.DomainError) as caught:
            service.import_preview("../escape.md", import_root=import_root)
        assert "escapes" in caught.value.detail

    def test_a_symlinked_source_is_never_followed(
        self, service: DefinitionService, import_root: Path, tmp_path: Path
    ) -> None:
        real = write(tmp_path / "elsewhere", "real.md", document(name="real-one"))
        link = import_root / "linked.md"
        link.symlink_to(real)
        with pytest.raises(errors.DomainError) as caught:
            service.import_preview(link, import_root=import_root)
        assert caught.value.code == errors.DEFINITION_INVALID
        assert "symlink" in caught.value.detail

    def test_a_symlinked_directory_inside_the_root_is_refused(
        self, service: DefinitionService, import_root: Path, tmp_path: Path
    ) -> None:
        write(import_root, "reviewer.md", document())
        (tmp_path / "elsewhere").mkdir(exist_ok=True)
        (import_root / "subdir").symlink_to(tmp_path / "elsewhere")
        with pytest.raises(errors.DomainError) as caught:
            service.import_preview(import_root, import_root=import_root)
        assert "symlink" in caught.value.detail

    def test_a_symlinked_root_component_is_refused(
        self, service: DefinitionService, tmp_path: Path
    ) -> None:
        real = tmp_path / "real-root"
        real.mkdir()
        write(real, "reviewer.md", document())
        fake = tmp_path / "fake-root"
        fake.symlink_to(real, target_is_directory=True)
        with pytest.raises(errors.DomainError) as caught:
            service.import_preview(fake / "reviewer.md", import_root=fake)
        assert caught.value.code == errors.DEFINITION_INVALID

    def test_the_store_itself_is_never_an_import_source(
        self, service: DefinitionService, tmp_path: Path
    ) -> None:
        store_root = tmp_path / "store-root"
        (store_root / "definitions").mkdir(parents=True)
        with pytest.raises(errors.DomainError) as caught:
            service.import_preview(store_root / "definitions", import_root=store_root)
        assert caught.value.code == errors.DEFINITION_INVALID

    def test_a_home_directory_root_is_refused(
        self, service: DefinitionService, tmp_path: Path, monkeypatch
    ) -> None:
        home = tmp_path / "fake-home"
        (home / ".claude" / "agents").mkdir(parents=True)
        write(home / ".claude" / "agents", "user.md", document(name="user-owned"))
        monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
        with pytest.raises(errors.DomainError) as caught:
            service.import_preview(home / ".claude" / "agents", import_root=home)
        assert caught.value.code == errors.DEFINITION_INVALID
        assert "HOME" in caught.value.detail

    def test_an_escaping_path_is_refused_before_any_file_read(
        self, service: DefinitionService, import_root: Path, tmp_path: Path, monkeypatch
    ) -> None:
        outside = write(tmp_path / "elsewhere", "secret.md", document(name="outside"))
        real_read_bytes = Path.read_bytes

        def guarded(self: Path) -> bytes:
            if str(self).startswith(str(outside)):
                raise AssertionError("an unapproved path reached a file read")
            return real_read_bytes(self)

        monkeypatch.setattr(Path, "read_bytes", guarded)
        with pytest.raises(errors.DomainError):
            service.import_preview(outside, import_root=import_root)


class TestNoFetchNoInclude:
    @pytest.fixture(autouse=True)
    def _no_network(self, monkeypatch):
        def refuse(*args, **kwargs):
            raise AssertionError("an import must never reach the network")

        monkeypatch.setattr(socket, "socket", refuse)
        monkeypatch.setattr(socket, "create_connection", refuse)

    @pytest.mark.parametrize("marker", [
        "![[other-file.md]]",
        "@import 'other.md'",
        "{{ include 'x' }}",
        "include: /etc/passwd",
    ])
    def test_a_recursive_include_is_refused_in_preview_and_approval(
        self, service: DefinitionService, import_root: Path, marker: str
    ) -> None:
        write(import_root, "reviewer.md", document(body=f"Read the rest:\n{marker}"))
        preview = service.import_preview(import_root, import_root=import_root)
        assert selectable(preview) == set()
        assert any("recursive-include" in line for line in preview.diagnostics)

    @pytest.mark.parametrize("reference", [
        "https://example.test/reviewer.md",
        "http://example.test/x",
    ])
    def test_a_remote_reference_is_a_refusal_not_a_fetch(
        self, service: DefinitionService, import_root: Path, reference: str
    ) -> None:
        write(import_root, "reviewer.md", document(body=f"See {reference}"))
        preview = service.import_preview(import_root, import_root=import_root)
        assert selectable(preview) == set()
        assert any("remote-reference" in line for line in preview.diagnostics)

    def test_a_git_source_without_a_pinned_commit_is_refused(
        self, service: DefinitionService, import_root: Path
    ) -> None:
        write(import_root, "reviewer.md", document())
        preview = service.import_preview(import_root, import_root=import_root)
        with pytest.raises(errors.DomainError) as caught:
            service.approve_import(
                preview.preview_id, principal=PRINCIPAL, server_scope=SERVER_SCOPE,
                selects=["reviewer.md"], origin="git-revision",
                origin_ref="org/repo@main#reviewer.md", operation_key="u:float",
            )
        assert caught.value.code == errors.DEFINITION_INVALID
        assert service.list_definitions() == []

    def test_a_pinned_git_revision_is_recorded_as_the_source(
        self, service: DefinitionService, import_root: Path
    ) -> None:
        write(import_root, "reviewer.md", document())
        preview = service.import_preview(import_root, import_root=import_root)
        pin = "a" * 38 + "ef"
        (definition,) = service.approve_import(
            preview.preview_id, principal=PRINCIPAL, server_scope=SERVER_SCOPE,
            selects=["reviewer.md"], origin="git-revision",
            origin_ref=f"org/repo@{pin}#reviewer.md", operation_key="u:pinned",
        )
        source = service.get_revision(definition.definition_id, 1).source
        assert source.origin == "git-revision"
        assert source.origin_ref == f"org/repo@{pin}#reviewer.md"


class TestBounds:
    def test_too_many_entries_is_a_typed_refusal(
        self, service: DefinitionService, import_root: Path
    ) -> None:
        for index in range(limits.MAX_IMPORT_FILES + 1):
            write(import_root, f"agents/doc{index}.md", document(name=f"doc{index}"))
        with pytest.raises(errors.DomainError) as caught:
            service.import_preview(import_root, import_root=import_root)
        assert caught.value.item_id == "import_bounds"

    def test_too_many_total_bytes_is_a_typed_refusal(
        self, service: DefinitionService, import_root: Path
    ) -> None:
        chunk = "x" * (limits.MAX_IMPORT_TOTAL_BYTES // 4)
        for index in range(6):
            write(import_root, f"doc{index}.md", document(name=f"doc{index}", body=chunk))
        with pytest.raises(errors.DomainError) as caught:
            service.import_preview(import_root, import_root=import_root)
        assert caught.value.item_id == "import_bounds"

    def test_a_directory_nested_too_deeply_is_refused(
        self, service: DefinitionService, import_root: Path
    ) -> None:
        deep = "/".join(f"level{index}" for index in range(limits.MAX_IMPORT_DEPTH))
        write(import_root, f"{deep}/reviewer.md", document())
        with pytest.raises(errors.DomainError) as caught:
            service.import_preview(import_root, import_root=import_root)
        assert caught.value.item_id == "import_depth"


class TestApproval:
    def test_only_the_selected_items_are_persisted(
        self, service: DefinitionService, import_root: Path
    ) -> None:
        write(import_root, "one.md", document(name="one", description="First review role."))
        write(import_root, "two.md", document(name="two", description="Second review role."))
        preview = service.import_preview(import_root, import_root=import_root)
        created = service.approve_import(
            preview.preview_id, principal=PRINCIPAL, server_scope=SERVER_SCOPE,
            selects=["one.md"], operation_key="u:pick-one",
        )
        assert [row.slug for row in created] == ["one"]
        assert [row.slug for row in service.list_definitions()] == ["one"]

    def test_an_approval_carries_the_principal_and_the_exact_digest(
        self, service: DefinitionService, import_root: Path
    ) -> None:
        path = write(import_root, "one.md", document(name="one"))
        preview = service.import_preview(import_root, import_root=import_root)
        entry = next(item for item in preview.files if item.relative_path == "one.md")
        (definition,) = service.approve_import(
            preview.preview_id, principal=PRINCIPAL, server_scope=SERVER_SCOPE,
            selects=["one.md"], operation_key="u:approve-one",
        )
        revision = service.get_revision(definition.definition_id, 1)
        assert revision.revision == 1
        assert revision.source.approved_by_principal == PRINCIPAL
        assert revision.source.content_digest == entry.content_digest
        assert digest.bytes_digest(path.read_bytes()) == entry.content_digest
        assert revision.role_body.strip() == "Cite file and line for every finding."

    def test_an_unpreviewed_selection_is_refused(
        self, service: DefinitionService, import_root: Path
    ) -> None:
        write(import_root, "one.md", document(name="one"))
        preview = service.import_preview(import_root, import_root=import_root)
        with pytest.raises(errors.DomainError) as caught:
            service.approve_import(
                preview.preview_id, principal=PRINCIPAL, server_scope=SERVER_SCOPE,
                selects=["/etc/passwd"], operation_key="u:sneak",
            )
        assert caught.value.code == errors.PERMISSION_EXCEEDS_CEILING
        assert service.list_definitions() == []

    def test_a_refused_item_may_not_be_approved(
        self, service: DefinitionService, import_root: Path
    ) -> None:
        write(import_root, "bad.md", document(name="bad", body="![[other.md]]"))
        write(import_root, "good.md", document(name="good"))
        preview = service.import_preview(import_root, import_root=import_root)
        with pytest.raises(errors.DomainError) as caught:
            service.approve_import(
                preview.preview_id, principal=PRINCIPAL, server_scope=SERVER_SCOPE,
                selects=["good.md", "bad.md"], operation_key="u:mixed",
            )
        assert caught.value.code == errors.PERMISSION_EXCEEDS_CEILING
        assert service.list_definitions() == []

    def test_a_selection_that_is_not_a_list_is_refused(
        self, service: DefinitionService, import_root: Path
    ) -> None:
        write(import_root, "one.md", document(name="one"))
        preview = service.import_preview(import_root, import_root=import_root)
        with pytest.raises(errors.DomainError) as caught:
            service.approve_import(
                preview.preview_id, principal=PRINCIPAL, server_scope=SERVER_SCOPE,
                selects="one.md", operation_key="u:string-select",
            )
        assert caught.value.item_id == "selects"

    def test_an_unknown_preview_is_reported_as_unknown(
        self, service: DefinitionService
    ) -> None:
        with pytest.raises(errors.DomainError) as caught:
            service.approve_import(
                "imp_missing0000000000000000", principal=PRINCIPAL,
                server_scope=SERVER_SCOPE, selects=["one.md"], operation_key="u:ghost",
            )
        assert caught.value.code == errors.OPERATION_UNKNOWN

    def test_a_source_that_drifted_after_the_preview_is_refused(
        self, service: DefinitionService, import_root: Path
    ) -> None:
        path = write(import_root, "one.md", document(name="one"))
        preview = service.import_preview(import_root, import_root=import_root)
        path.write_text(document(name="one", body="silently changed after preview"),
                        encoding="utf-8")
        with pytest.raises(errors.DomainError) as caught:
            service.approve_import(
                preview.preview_id, principal=PRINCIPAL, server_scope=SERVER_SCOPE,
                selects=["one.md"], operation_key="u:after-drift",
            )
        assert "drifted" in caught.value.detail
        assert service.list_definitions() == []

    def test_replaying_an_approval_creates_one_definition(
        self, service: DefinitionService, import_root: Path
    ) -> None:
        write(import_root, "one.md", document(name="one"))
        preview = service.import_preview(import_root, import_root=import_root)
        first = service.approve_import(
            preview.preview_id, principal=PRINCIPAL, server_scope=SERVER_SCOPE,
            selects=["one.md"], operation_key="u:twice",
        )
        again = service.approve_import(
            preview.preview_id, principal=PRINCIPAL, server_scope=SERVER_SCOPE,
            selects=["one.md"], operation_key="u:twice",
        )
        assert again == first
        assert len(service.list_definitions()) == 1

    def test_an_import_plan_persists_nothing(
        self, service: DefinitionService, import_root: Path, tmp_path: Path
    ) -> None:
        write(import_root, "one.md", document(name="one"))
        preview = service.import_preview(import_root, import_root=import_root)
        plans = service.import_plan(
            PRINCIPAL, preview.preview_id, server_scope=SERVER_SCOPE, selects=["one.md"],
        )
        assert len(plans) == 1
        assert plans[0].revision.source.origin == "user-upload"
        assert not (tmp_path / "store-root").exists()
        assert service.list_definitions() == []

    def test_a_published_import_rejects_a_hand_written_source_forgery(
        self, service: DefinitionService, import_root: Path
    ) -> None:
        write(import_root, "one.md", document(name="one"))
        preview = service.import_preview(import_root, import_root=import_root)
        (definition,) = service.approve_import(
            preview.preview_id, principal=PRINCIPAL, server_scope=SERVER_SCOPE,
            selects=["one.md"], operation_key="u:approve",
        )
        forged = make_revision(
            definition.definition_id, 2,
            role_body="second body",
        )
        assert forged.source.origin == "user-upload"
        with pytest.raises(errors.DomainError):
            service.save_revision(
                PRINCIPAL, dto.DefinitionRevision(**{
                    **vars(forged),
                    "source": dto.SourceApproval(**{
                        **vars(forged.source), "origin": "not-an-origin",
                    }),
                }),
                server_scope=SERVER_SCOPE, operation_key="u:forged-origin",
                expected_row_version=2,
            )

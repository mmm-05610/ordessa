"""G04 — immutable revisions, stable digests, definition identity."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from conftest import PRINCIPAL, SERVER_SCOPE, make_revision, publish
from ordessa_assets_subagents import dto, errors
from ordessa_assets_subagents.decoder import validate_revision
from ordessa_assets_subagents.digest import revision_digest, revision_payload
from ordessa_assets_subagents.service import DefinitionService


def revision_file(store_root: Path, definition_id: str, revision: int) -> Path:
    return store_root / "definitions" / definition_id / "revisions" / f"{revision}.json"


class TestImmutableRevisions:
    def test_publishing_appends_the_next_revision(
        self, service: DefinitionService, definition: dto.AgentDefinition
    ) -> None:
        first = publish(service, definition, 1)
        second = publish(service, definition, 2, role_body="Now with review checklists.")
        row = service.get_definition(definition.definition_id)
        assert (first.revision, second.revision) == (1, 2)
        assert row.latest_revision == 2
        assert service.get_revision(definition.definition_id, 1) == first
        assert service.get_revision(definition.definition_id, 2) == second

    def test_writing_over_a_stored_revision_is_refused(
        self, service: DefinitionService, definition: dto.AgentDefinition
    ) -> None:
        publish(service, definition, 1)
        with pytest.raises(errors.DomainError) as refused:
            service.save_revision(
                PRINCIPAL,
                make_revision(definition.definition_id, 1, role_body="rewritten history"),
                server_scope=SERVER_SCOPE, operation_key="u:rewrite",
                expected_row_version=2,
            )
        assert refused.value.code == errors.REVISION_STALE

    def test_a_numbered_gap_is_refused(
        self, service: DefinitionService, definition: dto.AgentDefinition
    ) -> None:
        with pytest.raises(errors.DomainError) as refused:
            service.save_revision(
                PRINCIPAL, make_revision(definition.definition_id, 3),
                server_scope=SERVER_SCOPE, operation_key="u:gap", expected_row_version=1,
            )
        assert refused.value.code == errors.DEFINITION_INVALID
        assert refused.value.item_id == "revision"
        assert service.get_definition(definition.definition_id).latest_revision == 0

    def test_an_older_revision_keeps_its_exact_bytes(
        self, service: DefinitionService, definition: dto.AgentDefinition, tmp_path: Path
    ) -> None:
        publish(service, definition, 1, role_body="Original body.")
        path = revision_file(tmp_path / "store-root", definition.definition_id, 1)
        before = path.read_bytes()
        publish(service, definition, 2, role_body="Later body.")
        assert path.read_bytes() == before
        assert service.get_revision(definition.definition_id, 1).role_body == "Original body."

    def test_a_stored_revision_is_read_only_at_rest(
        self, service: DefinitionService, definition: dto.AgentDefinition, tmp_path: Path
    ) -> None:
        publish(service, definition, 1)
        path = revision_file(tmp_path / "store-root", definition.definition_id, 1)
        assert not path.stat().st_mode & 0o200

    def test_editing_content_never_mutates_the_published_object(
        self, service: DefinitionService, definition: dto.AgentDefinition
    ) -> None:
        published = publish(service, definition, 1)
        assert published.role_body == "You review code read-only and cite findings."
        publish(service, definition, 2, role_body="different")
        assert service.get_revision(definition.definition_id, 1) == published


class TestDigests:
    def test_the_same_content_yields_the_same_digest(
        self, service: DefinitionService, definition: dto.AgentDefinition
    ) -> None:
        first = make_revision(definition.definition_id, 1)
        same = make_revision(definition.definition_id, 1)
        assert first.content_digest == same.content_digest
        assert revision_digest(first) == revision_digest(same)

    def test_one_changed_byte_yields_a_different_digest(
        self, service: DefinitionService, definition: dto.AgentDefinition
    ) -> None:
        first = make_revision(definition.definition_id, 1, role_body="body one")
        other = make_revision(definition.definition_id, 1, role_body="body onc")
        assert first.content_digest != other.content_digest

    def test_the_digest_is_sha256_over_canonical_json_of_the_content(
        self, service: DefinitionService, definition: dto.AgentDefinition
    ) -> None:
        import hashlib

        revision = make_revision(definition.definition_id, 1,
                                 tool_refs=[dto.ToolRef(owner_id="Read", revision=None)])
        canonical = json.dumps(
            revision_payload(revision), sort_keys=True, separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        assert revision.content_digest == "sha256:" + hashlib.sha256(canonical).hexdigest()

    def test_a_digest_that_does_not_match_its_content_is_refused(
        self, service: DefinitionService, definition: dto.AgentDefinition
    ) -> None:
        revision = make_revision(definition.definition_id, 1)
        forged = dto.DefinitionRevision(**{
            **vars(revision),
            "role_body": revision.role_body + " appended",
        })
        with pytest.raises(errors.DomainError) as refused:
            validate_revision(forged)
        assert refused.value.code == errors.DEFINITION_INVALID
        assert refused.value.item_id == "content_digest"

    def test_a_non_sha256_digest_is_refused_before_any_write(
        self, service: DefinitionService, definition: dto.AgentDefinition, tmp_path: Path
    ) -> None:
        revision = make_revision(definition.definition_id, 1)
        broken = dto.DefinitionRevision(
            **{**vars(revision), "content_digest": "md5:" + "0" * 32}
        )
        with pytest.raises(errors.DomainError) as refused:
            service.save_revision(
                PRINCIPAL, broken, server_scope=SERVER_SCOPE,
                operation_key="u:bad-digest", expected_row_version=1,
            )
        assert refused.value.code == errors.DEFINITION_INVALID
        assert not revision_file(tmp_path / "store-root", definition.definition_id, 1).exists()


class TestDefinitionIdentity:
    def test_the_id_is_not_derived_from_the_slug(
        self, service: DefinitionService, definition: dto.AgentDefinition
    ) -> None:
        assert definition.slug not in definition.definition_id

    def test_two_definitions_with_the_same_slug_get_distinct_ids(
        self, service: DefinitionService, definition: dto.AgentDefinition
    ) -> None:
        twin = service.create_definition(
            PRINCIPAL, server_scope=SERVER_SCOPE, slug=definition.slug,
            display_name="Another reviewer", description="Same slug, other content.",
            origin_scope="project", origin_owner="p:alpha", operation_key="u:create-twin",
        )
        assert twin.definition_id != definition.definition_id
        assert {row.definition_id for row in service.list_definitions()} == {
            definition.definition_id, twin.definition_id,
        }

    def test_origin_scope_is_a_closed_set(
        self, service: DefinitionService
    ) -> None:
        for scope in dto.ORIGIN_SCOPES:
            service.create_definition(
                PRINCIPAL, server_scope=SERVER_SCOPE, slug=f"scope-{scope}",
                display_name="Scope probe", description="One probe per scope.",
                origin_scope=scope, origin_owner="local",
                operation_key=f"u:scope-{scope}",
            )
        with pytest.raises(errors.DomainError) as refused:
            service.create_definition(
                PRINCIPAL, server_scope=SERVER_SCOPE, slug="scope-bogus",
                display_name="Bogus scope", description="Not a declared scope.",
                origin_scope="team", origin_owner="local", operation_key="u:scope-bogus",
            )
        assert refused.value.code == errors.DEFINITION_INVALID
        assert refused.value.item_id == "origin_scope"

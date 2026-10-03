"""G04 — the store's own guards, driven directly at the store boundary.

`service.py` re-checks the row version and the revision number before it ever
calls the store (service.py:170-180), so a mutation that disables either store
guard is invisible to service-driven tests. These tests call
`DefinitionStore.replace_definition` / `DefinitionStore.write_revision`
themselves and assert both the typed refusal and the byte-level absence of any
side effect, so the last line of defence stays reachable and tested.

Helpers are self-contained on purpose: this file shares no fixture with the
other slices' tests beyond pytest's `tmp_path`.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from ordessa_assets_subagents import dto, errors
from ordessa_assets_subagents.digest import bytes_digest, revision_digest
from ordessa_assets_subagents.store import DefinitionStore

SERVER_SCOPE = "server:local"
#: Path-safe, opaque, and never contains the slug (see validate_definition).
DEFINITION_ID = "def_57075726573746f72656775617264"
SLUG = "store-guard-reviewer"
PRINCIPAL = "u:guardian"
APPROVED_AT = "2026-09-28T10:00:00+00:00"


def make_definition(
    *,
    row_version: int,
    latest_revision: int = 0,
    description: str = "the row as stored",
    archived: bool = False,
) -> dto.AgentDefinition:
    return dto.AgentDefinition(
        server_scope=SERVER_SCOPE,
        definition_id=DEFINITION_ID,
        slug=SLUG,
        display_name="Store guard reviewer",
        description=description,
        origin_scope="public",
        origin_owner="local",
        latest_revision=latest_revision,
        archived=archived,
        row_version=row_version,
    )


def make_revision(revision: int, body: str) -> dto.DefinitionRevision:
    """A revision whose content_digest is its own canonical digest (decoder-legal)."""
    source = dto.SourceApproval(
        origin="user-upload",
        origin_ref=f"upload/{PRINCIPAL}",
        content_digest=bytes_digest(body.encode("utf-8")),
        approved_by_principal=PRINCIPAL,
        approved_at=APPROVED_AT,
    )
    provisional = dto.DefinitionRevision(
        definition_id=DEFINITION_ID,
        revision=revision,
        content_digest="sha256:" + "0" * 64,
        role_body=body,
        source=source,
    )
    return dto.DefinitionRevision(
        **{**vars(provisional), "content_digest": revision_digest(provisional)}
    )


def row_path(store: DefinitionStore) -> Path:
    return store.definition_path(DEFINITION_ID)


def revision_file(store: DefinitionStore, revision: int) -> Path:
    return store.revision_path(DEFINITION_ID, revision)


@pytest.fixture
def guard_store(tmp_path: Path) -> DefinitionStore:
    store = DefinitionStore(tmp_path / "guard-store-root")
    store.create_definition(make_definition(row_version=3))
    return store


class TestStoreCasGuardDirectly:
    def test_a_stale_expected_row_version_is_refused_and_the_row_bytes_do_not_move(
        self, guard_store: DefinitionStore
    ) -> None:
        before = row_path(guard_store).read_bytes()
        late_writer = make_definition(
            row_version=4, description="a late writer's overwrite"
        )
        with pytest.raises(errors.DomainError) as refused:
            guard_store.replace_definition(late_writer, expected_row_version=2)
        assert refused.value.code == errors.REVISION_STALE
        assert refused.value.item_id == DEFINITION_ID
        assert row_path(guard_store).read_bytes() == before
        stored = guard_store.read_definition(DEFINITION_ID)
        assert stored["row_version"] == 3
        assert stored["description"] == "the row as stored"

    def test_the_correct_version_replaces_so_the_stale_refusal_is_not_vacuous(
        self, guard_store: DefinitionStore
    ) -> None:
        before = row_path(guard_store).read_bytes()
        intended = make_definition(row_version=4, description="the sanctioned edit")
        guard_store.replace_definition(intended, expected_row_version=3)
        after = row_path(guard_store).read_bytes()
        assert after != before
        stored = guard_store.read_definition(DEFINITION_ID)
        assert stored["row_version"] == 4
        assert stored["description"] == "the sanctioned edit"

    def test_a_row_version_advances_and_a_repeat_of_the_stale_write_is_still_refused(
        self, guard_store: DefinitionStore
    ) -> None:
        guard_store.replace_definition(
            make_definition(row_version=4, latest_revision=1), expected_row_version=3
        )
        stored_after_valid_write = guard_store.read_definition(DEFINITION_ID)
        assert (stored_after_valid_write["row_version"],
                stored_after_valid_write["latest_revision"]) == (4, 1)
        before = row_path(guard_store).read_bytes()
        with pytest.raises(errors.DomainError) as refused:
            guard_store.replace_definition(
                make_definition(row_version=5, description="replay of a stale writer"),
                expected_row_version=3,
            )
        assert refused.value.code == errors.REVISION_STALE
        assert row_path(guard_store).read_bytes() == before
        assert guard_store.read_definition(DEFINITION_ID)["row_version"] == 4


class TestRevisionImmutabilityGuardDirectly:
    def test_a_stored_revision_number_is_refused_and_its_bytes_do_not_move(
        self, guard_store: DefinitionStore
    ) -> None:
        guard_store.write_revision(make_revision(1, "the originally published body"))
        stored = revision_file(guard_store, 1)
        before = stored.read_bytes()
        with pytest.raises(errors.DomainError) as refused:
            guard_store.write_revision(make_revision(1, "history rewritten in place"))
        assert refused.value.code == errors.REVISION_STALE
        assert refused.value.item_id == f"{DEFINITION_ID}@1"
        assert "never rewritten" in (refused.value.detail or "")
        assert stored.read_bytes() == before
        assert guard_store.revision_numbers(DEFINITION_ID) == [1]
        assert guard_store.get_revision(
            DEFINITION_ID, 1
        ).role_body == "the originally published body"

    def test_a_new_revision_number_writes_so_the_refusal_is_not_vacuous(
        self, guard_store: DefinitionStore
    ) -> None:
        guard_store.write_revision(make_revision(1, "first body"))
        guard_store.write_revision(make_revision(2, "second body"))
        assert revision_file(guard_store, 2).read_bytes() != revision_file(
            guard_store, 1
        ).read_bytes()
        assert guard_store.revision_numbers(DEFINITION_ID) == [1, 2]
        assert guard_store.get_revision(DEFINITION_ID, 2).role_body == "second body"

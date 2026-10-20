"""Mutual proof: the migration tool, the fixture and the live definition
module must agree on every digest, one function of record.

The old pin was byte-identity against
``ordessa_server_compat.assets.mcp``'s private digest function; that package
is deleted, so the successor pin is explicit agreement with
``backend.definition`` - the live digest of record for MCP definitions - at
all three layers: fixture bytes, ``scan_legacy`` output and the digests the
migration adopts into the target index.
"""
from __future__ import annotations

import json
from pathlib import Path

import backend.migration as migration
from backend import definition
from backend.definition import canonical_definition, definition_digest
from backend.definition_store import McpDefinitionStore
from backend.migration import LEGACY_SERVER_SCOPE, migrate, scan_legacy
from legacy_sample import (
    REMOTE_HTTPS,
    STDIO_ENV_REF,
    STDIO_PLAIN,
    STDIO_REV2,
    build_legacy_dataset,
)


def test_migration_digest_symbol_is_the_live_definition_digest():
    # not a private ported copy: the tool's digest function IS the live one
    assert migration.definition_digest is definition.definition_digest
    canonical = canonical_definition(STDIO_ENV_REF)
    assert migration.definition_digest(canonical) == definition_digest(canonical)
    # and the legacy env/header collapse still canonicalises to bare
    # credential-reference strings, the shape the old store digested
    assert canonical["transport"]["stdio"]["env"] == {"API_TOKEN": "cred-token-1"}


def test_fixture_files_are_the_legacy_canonical_rule_output(tmp_path):
    """The fixture does not invent bytes: for each typed legacy definition the
    live canonical rule produces exactly the file on disk, and the digest
    taken over it is the fixture's recorded digest."""
    dataset = build_legacy_dataset(tmp_path)
    samples = [
        (STDIO_PLAIN, "fs-local", 1), (STDIO_ENV_REF, "env-ref-srv", 1),
        (REMOTE_HTTPS, "remote-weather", 1), (STDIO_REV2, "fs-local", 2),
    ]
    for definition, asset_id, revision in samples:
        canonical = canonical_definition(definition)
        expected = json.dumps(canonical, sort_keys=True, separators=(",", ":")).encode("utf-8")
        on_disk = (dataset.assets_root / "mcp" / asset_id / str(revision) / "server.json")
        assert on_disk.read_bytes() == expected
        assert definition_digest(canonical) == dataset.facts[f"{asset_id}@{revision}"]["digest"]


def test_fixture_scan_and_adopted_digests_are_the_same_live_digest(tmp_path):
    dataset = build_legacy_dataset(tmp_path)
    scan = scan_legacy(dataset.db_path, dataset.assets_root)
    for asset in scan["assets"]:
        for entry in asset["revisions"]:
            if not entry["readable"]:
                continue
            # fixture digest (computed when the file was written) ...
            fixture_digest = dataset.facts[f"{asset['asset_id']}@{entry['revision']}"]["digest"]
            assert entry["file_digest"] == fixture_digest
            # ... is what the live module recomputes over the very same bytes.
            # (Stored legacy files carry the collapsed bare-string credential
            # shape, so the digest is taken over the stored canonical dict, as
            # read_revision/scan do; the typed-input rule is pinned above.)
            on_disk = json.loads(Path(entry["path"]).read_text(encoding="utf-8"))
            assert entry["file_digest"] == definition_digest(on_disk)
    # ... and is what the migration adopts under, file by file, in the target
    target = tmp_path / "target"
    migrate(dataset.db_path, dataset.assets_root, target)
    definitions = McpDefinitionStore(target)
    for asset in scan["assets"]:
        for entry in asset["revisions"]:
            if not entry["readable"]:
                continue
            revision_view = definitions.read_revision(
                server_scope=LEGACY_SERVER_SCOPE, definition_id=asset["asset_id"],
                revision=entry["revision"])
            assert revision_view.canonical_digest == entry["file_digest"]
            assert revision_view.canonical_digest == \
                dataset.facts[f"{asset['asset_id']}@{entry['revision']}"]["digest"]

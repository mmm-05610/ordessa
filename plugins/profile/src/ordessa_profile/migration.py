"""Legacy ``server_profiles`` import (read-only input, contracts/host-integration.md).

Reads a legacy v21-shaped SQLite (table ``server_profiles``) without writing
to it and re-creates the rows in the plugin store with identity, revision,
archive and version semantics preserved. Asset references (credential ids,
config-object digests, permission payloads, clone provenance) are *reported*,
never imported into the new tables — the new store carries facet values only,
and references travel through the report to the serial integration wave.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import repository as repo


@dataclass
class LegacyImportReport:
    imported: int = 0
    skipped: list[dict[str, Any]] = field(default_factory=list)
    retained_refs: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "imported": self.imported,
            "skipped": self.skipped,
            "retained_refs": self.retained_refs,
        }


def import_legacy(source_db_path: str | Path, *,
                  target) -> LegacyImportReport:
    report = LegacyImportReport()
    uri = f"file:{Path(source_db_path).resolve()}?mode=ro"
    source = sqlite3.connect(uri, uri=True)
    try:
        rows = source.execute(
            "SELECT id, version, name, harness_type, config_revision,"
            " archived_at, display_name, created_at, updated_at,"
            " config_object_digest, credential_id, permission_preset,"
            " origin_profile_id, cloned_at FROM server_profiles"
            " ORDER BY created_at, id"
        ).fetchall()
    finally:
        source.close()
    with target.db.transaction() as conn:
        for row in rows:
            (legacy_id, version, name, harness_type, config_revision,
             archived_at, display_name, created_at, updated_at,
             config_digest, credential_id, permission_preset,
             origin_profile_id, cloned_at) = row
            if repo.get_profile(conn, legacy_id) is not None:
                report.skipped.append(
                    {"profile_id": legacy_id, "reason": "already_present"})
                continue
            report.retained_refs.append({
                "profile_id": legacy_id,
                "config_object_digest": config_digest,
                "credential_reference_present": credential_id is not None,
                "permission_preset_present": permission_preset is not None,
                "origin_profile_id": origin_profile_id,
                "cloned_at": cloned_at,
            })
            timestamp = created_at or target.timestamp()
            repo.insert_profile(
                conn, profile_id=legacy_id,
                version=max(1, int(version or 1)),
                display_name=display_name or name or legacy_id,
                harness_id=harness_type,
                revision=max(1, int(config_revision or 1)),
                archived_at=archived_at,
                created_at=timestamp,
                updated_at=updated_at or timestamp,
            )
            repo.insert_revision(
                conn, profile_id=legacy_id,
                config_revision=max(1, int(config_revision or 1)),
                created_at=timestamp,
            )
            report.imported += 1
    return report

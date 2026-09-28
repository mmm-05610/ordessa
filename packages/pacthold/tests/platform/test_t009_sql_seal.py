"""specs/010 T009 SQL seal guard: the historical chain is byte-frozen.

The nine migrations ``001_init.sql`` … ``009_execution_finalization.sql`` were
sealed at the pre-migration baseline commit ``14cdb563e5`` into
``plugins/runtime-compat/src/pacthold_runtime_compat/migrations/`` with their
file names, numbering and bytes unchanged (plan.md Compatibility: 字节/编号保持;
data-model.md: 旧 SQL 摘要/编号/表名保持).  The digests below were computed
from ``git show 14cdb563e5:<old path>`` at T009 close-out and are the seal.

The kernel's own neutral schema lives in an independent file and must stay a
pure ``CREATE … IF NOT EXISTS`` end-state description (never ALTER/DML), so it
cannot rewrite an old database.  This file pins both sides and carries its own
tripwire proving a tampered copy would be caught.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
CORE_MIGRATIONS_DIR = REPO_ROOT / "packages" / "pacthold" / "src" / "pacthold" / "migrations"
COMPAT_MIGRATIONS_DIR = (
    REPO_ROOT / "plugins" / "runtime-compat" / "src" / "pacthold_runtime_compat" / "migrations"
)

#: sha256 of each sealed historical migration, taken from commit 14cdb563e5.
SEALLED_MIGRATION_SHA256 = {
    "001_init.sql": "556abd7252c0941d202c87c1b83327107c08f0c812e4839cdc7ca63c5da19c35",
    "002_rename_claude_md_ref.sql": "296727f8c9238f9bd90b25ed70ce85a9850b0052980f4311b67153e9ec56a171",
    "003_work_core.sql": "046286b3669ecfad5097ac5e4348c6823da8681dc6f23eac825ebb0e1476b534",
    "004_minimal_work_core.sql": "1202e06f678c3af55a2b5a05ad8e97d86301ecf04e309cf4950b1c577ba9cd15",
    "005_resource_contract_inputs.sql": "961a19845a60b69fb8c6a9ab915f74ceabb1e85d3f378d6a534b40edb94d6870",
    "006_resource_contract_inputs.sql": "0ac124d4bfcd74d3debd885c7221afea076204b964ed5a3c710ad7066f775b3f",
    "007_resource_observations.sql": "84fcdf3805497f2cce7b81fbf81879cd96631524fd04ae9af655c6342d611c29",
    "008_resource_observation_evidence_metadata.sql": "96f9e8007d30ad27b0441255b9780a02a86d04e7715bb18bd135fd371a512575",
    "009_execution_finalization.sql": "d66c4de7df8216d24028c2c4180ed6bf47ae18018f2853d197b7e2f80ca43e5b",
}

#: The kernel's neutral end-state schema (independent namespace).
CORE_SCHEMA_SHA256 = "8d0a6b399fdcf2e80f7f317a6e192661be6d9be69d2e758864fc4bc545e0ca3c"

#: Statement-leading forbidden verbs.  Anchored at line start so referential
#: syntax like ``ON DELETE CASCADE`` (mid-line) stays legal while any real
#: ALTER/DROP/DML statement would turn the guard red.
_NON_IDEMPOTENT = re.compile(
    r"(?im)^\s*(ALTER|DROP|UPDATE|DELETE|INSERT|REPLACE|CREATE\s+TRIGGER)\b"
)


def _strip_sql_comments(text: str) -> str:
    """Drop ``--`` line comments so the forbidden-statement scan reads only
    executable SQL (the file's own comments mention ALTER/DROP as warnings)."""
    lines = []
    for line in text.splitlines():
        index = line.find("--")
        lines.append(line[:index] if index >= 0 else line)
    return "\n".join(lines)


def verify_seal(directory: Path, expected: dict[str, str]) -> list[str]:
    """Return a line per tampered/missing/extra migration file ([] == sealed)."""
    problems: list[str] = []
    if not directory.is_dir():
        return [f"migration directory missing: {directory}"]
    present = {p.name for p in directory.glob("*.sql")}
    for name in sorted(set(present - set(expected))):
        problems.append(f"{name}: unexpected extra migration file")
    for name, digest in sorted(expected.items()):
        path = directory / name
        if not path.is_file():
            problems.append(f"{name}: sealed migration missing")
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != digest:
            problems.append(f"{name}: digest {actual} != sealed {digest}")
    return problems


def test_sealed_historical_chain_is_byte_identical():
    problems = verify_seal(COMPAT_MIGRATIONS_DIR, SEALLED_MIGRATION_SHA256)
    assert problems == [], "sealed historical migrations drifted:\n" + "\n".join(problems)


def test_sealed_chain_keeps_file_names_and_numbering():
    names = sorted(SEALLED_MIGRATION_SHA256)
    assert names == [
        "001_init.sql",
        "002_rename_claude_md_ref.sql",
        "003_work_core.sql",
        "004_minimal_work_core.sql",
        "005_resource_contract_inputs.sql",
        "006_resource_contract_inputs.sql",
        "007_resource_observations.sql",
        "008_resource_observation_evidence_metadata.sql",
        "009_execution_finalization.sql",
    ], "historical numbering is part of the seal and may not be renumbered"
    on_disk = sorted(p.name for p in COMPAT_MIGRATIONS_DIR.glob("*.sql"))
    assert on_disk == names, "sealed directory must contain exactly the nine historical files"


def test_kernel_migrations_are_only_the_independent_neutral_schema():
    files = sorted(p.name for p in CORE_MIGRATIONS_DIR.glob("*.sql"))
    assert files == ["001_core_schema.sql"], (
        "the kernel namespace carries only its own neutral schema; historical "
        "SQL must not be re-added here (specs/010 T009)"
    )
    text = _strip_sql_comments(
        (CORE_MIGRATIONS_DIR / "001_core_schema.sql").read_text(encoding="utf-8")
    )
    assert hashlib.sha256(
        (CORE_MIGRATIONS_DIR / "001_core_schema.sql").read_bytes()
    ).hexdigest() == CORE_SCHEMA_SHA256
    assert not _NON_IDEMPOTENT.search(text), (
        "001_core_schema.sql must stay CREATE … IF NOT EXISTS only; any "
        "ALTER/DROP/DML would let the neutral copy rewrite an old database"
    )


def test_tripwire_tampered_sql_copy_is_flagged(tmp_path):
    """Guard self-test: one extra byte in a sealed file must turn this red."""
    for name, digest in SEALLED_MIGRATION_SHA256.items():
        (tmp_path / name).write_bytes((COMPAT_MIGRATIONS_DIR / name).read_bytes() + b"\n")
    problems = verify_seal(tmp_path, SEALLED_MIGRATION_SHA256)
    assert len(problems) == len(SEALLED_MIGRATION_SHA256), (
        "the digest check is vacuous: tampered copies were not flagged"
    )
    # and the honest copy verifies clean:
    assert verify_seal(COMPAT_MIGRATIONS_DIR, SEALLED_MIGRATION_SHA256) == []


def test_tripwire_missing_and_extra_files_are_flagged(tmp_path):
    import shutil

    shutil.copy(COMPAT_MIGRATIONS_DIR / "001_init.sql", tmp_path / "001_init.sql")
    (tmp_path / "002_rename_claude_md_ref.sql").write_bytes(
        (COMPAT_MIGRATIONS_DIR / "002_rename_claude_md_ref.sql").read_bytes()
    )
    (tmp_path / "010_extra.sql").write_text("SELECT 1;", encoding="utf-8")
    problems = verify_seal(tmp_path, SEALLED_MIGRATION_SHA256)
    kinds = " ".join(problems)
    assert "missing" in kinds and "unexpected extra" in kinds

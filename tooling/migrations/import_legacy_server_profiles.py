"""Retired importer for the former ProfileCore/ProfileDatabase owner.

The old importer wrote ProfileCore rows and is not a migration into the
current Pacthold ProfileCatalog. It must not open or alter a supplied source
database. Historical format documentation remains available in the migration
records; a future conversion requires a separately authorized implementation.
"""


class LegacyProfileImportRetired(RuntimeError):
    """The legacy importer has no current destination owner."""


def import_legacy(source_db_path, *, target=None):
    del source_db_path, target
    raise LegacyProfileImportRetired(
        "retired: legacy server_profiles import targeted ProfileCore; "
        "no current import destination is available")

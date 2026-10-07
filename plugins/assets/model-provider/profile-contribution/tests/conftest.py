# migrated from plugins/model-provider@9305563719d25e04076b9221a7284660bd8f8642 (tests/conftest.py, verbatim)
"""Local stack fixtures (same shape as the core package's suite): real
pacthold storage, fakes only at the credential/harness boundaries."""
from __future__ import annotations

import types

import pytest
# foundation@8844c475bc adaptation: the product Database facade relocated to
# plugins/runtime-compat (010 FR-011); pacthold.storage keeps ObjectStore only.
from pacthold.storage import ObjectStore
from pacthold_runtime_compat.storage import Database
from ordessa_server.idempotency import IdempotentRecords

from ordessa_model_provider.catalog import ModelCatalogService
from ordessa_model_provider.records import ProviderModelRecords


class FakeCredentials:
    def __init__(self, rows=()):
        self._rows = {row["id"]: dict(row) for row in rows}

    def get(self, credential_id, kind=None):
        if credential_id not in self._rows:
            from ordessa_server.errors import ServerError

            raise ServerError("CREDENTIAL_NOT_FOUND", "Credential was not found", status=404)
        return dict(self._rows[credential_id])


class FakeHarnesses:
    def __init__(self, descriptors=None):
        self._descriptors = descriptors or {}

    def __contains__(self, harness):
        return harness in self._descriptors

    def get(self, harness):
        return self._descriptors[harness]

    def registered(self):
        return tuple(sorted(self._descriptors))

    def wire_protocols(self, harness):
        return {}


@pytest.fixture()
def stack(tmp_path):
    root = tmp_path / "data"
    root.mkdir()
    database = Database(root / "db.sqlite3")
    database.initialize()
    return {
        "root": root,
        "database": database,
        "objects": ObjectStore(root),
        "idempotency": IdempotentRecords(database),
    }

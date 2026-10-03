# migrated from plugins/model-provider@9305563719d25e04076b9221a7284660bd8f8642 (tests/conftest.py, verbatim)
"""Shared fixtures: a real pacthold stack plus the plugin under test.

The stack is the same shape the legacy tests used (real Database +
IdempotentRecords + ObjectStore, fakes only at the credential/harness
boundaries), so migrated behavior is exercised against the storage it will
actually run on. The fake doubles live in ``ordessa_model_provider.testing``.
"""
from __future__ import annotations

import pytest
# foundation@8844c475bc adaptation: the product Database facade relocated to
# plugins/runtime-compat (010 FR-011); pacthold.storage keeps ObjectStore only.
from pacthold.storage import ObjectStore
from pacthold_runtime_compat.storage import Database
from ordessa_server.idempotency import IdempotentRecords

from ordessa_model_provider.catalog import ModelCatalogService
from ordessa_model_provider.plugin import ModelProviderPlugin
from ordessa_model_provider.records import ProviderModelRecords
from ordessa_model_provider.testing import FakeCredentials, FakeHarnesses, harness_descriptor


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


@pytest.fixture()
def credentials():
    return FakeCredentials(rows=[{
        "id": "cred-1", "kind": "api_key", "secret_locator": "loc://cred-1",
    }])


@pytest.fixture()
def harnesses():
    return FakeHarnesses(
        descriptors={"pi": harness_descriptor(), "codex": harness_descriptor()},
        protocols={"pi": {"openai-chat": ""}, "codex": {"openai-chat": "", "openai-responses": ""}},
    )


@pytest.fixture()
def catalog(stack, harnesses, credentials):
    return ModelCatalogService(
        ProviderModelRecords(stack["database"], stack["idempotency"]),
        stack["objects"],
        harnesses=harnesses, credentials=credentials,
    )


@pytest.fixture()
def plugin(harnesses):
    """The real plugin wired to the fixture stack's ports (as the host would)."""
    return ModelProviderPlugin(harnesses=harnesses)

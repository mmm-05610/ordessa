# migrated from plugins/model-provider@9305563719d25e04076b9221a7284660bd8f8642 (src/ordessa_model_provider/testing.py, verbatim)
"""Test-support doubles for the Model Provider domain.

Shaped exactly like the ports the core consumes, so suites here and in the
contribution packages exercise the real seams. Import from test code only -
nothing in the domain depends on this module.
"""
from __future__ import annotations

import types

from ordessa_server.errors import ServerError


class FakeCredentials:
    """In-memory credential *references*; never any secret content."""

    def __init__(self, rows=()):
        self._rows = {row["id"]: dict(row) for row in rows}

    def get(self, credential_id, kind=None):
        row = self._rows.get(credential_id)
        if row is None:
            raise ServerError("CREDENTIAL_NOT_FOUND", "Credential was not found", status=404)
        if kind is not None and row["kind"] != kind:
            raise ServerError(
                "CREDENTIAL_KIND_MISMATCH", "Credential kind does not match", status=422)
        return dict(row)


class FakeHarnesses:
    """A plain-mapping harness table, tolerated by the service like the legacy
    unit-test doubles were."""

    def __init__(self, descriptors=None, protocols=None):
        self._descriptors = descriptors or {}
        self._protocols = protocols or {}

    def __contains__(self, harness):
        return harness in self._descriptors

    def get(self, harness):
        return self._descriptors[harness]

    def registered(self):
        return tuple(sorted(self._descriptors))

    def wire_protocols(self, harness):
        return dict(self._protocols.get(harness, {}))


def harness_descriptor(credential_kind=None, model_control_id="model"):
    return types.SimpleNamespace(
        credential_kind=credential_kind, model_control_id=model_control_id,
    )


class SentinelSecretStore:
    """Returns one fixed sentinel so leak scans have a needle to find."""

    SENTINEL = "sekret-sentinel-1234"

    def read(self, locator):
        return self.SENTINEL.encode("utf-8")


class RecordingSecretStore(SentinelSecretStore):
    def __init__(self):
        self.reads = 0

    def read(self, locator):
        self.reads += 1
        return super().read(locator)


def wire_body(**over):
    """A wire-shaped create body (exactly the four model keys _models allows)."""
    body = {
        "displayName": "My API", "harness": "pi", "provider": "acme",
        "credentialId": None,
        "configuration": [{"controlId": "model", "value": {"providerId": "x", "modelId": "m1"}}],
        "models": [{"modelId": "m1", "displayName": "m1",
                    "availability": "available", "unavailableReason": None}],
    }
    body.update(over)
    return body


def seed_credential_row(database, credential_id="cred-1", kind="api_key",
                        locator="loc://cred-1"):
    """The records layer checks credential existence against the real table
    (a storage-level FK discipline, separate from the credentials port)."""
    with database.transaction() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO server_credentials(id,kind,secret_locator,created_at) "
            "VALUES (?,?,?,?)", (credential_id, kind, locator, "t"),
        )

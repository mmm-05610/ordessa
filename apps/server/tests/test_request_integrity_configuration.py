"""Source tests for the explicit request-integrity reference consumer.

The only key bytes below are synthetic test fixtures. No SecretService,
protected keyring, or real data root is accessed.
"""
from ordessa_units.errors import UnitComparisonUnavailable
import json
import os

import pytest

from ordessa_infrastructure.identifiers import RequestKey
from ordessa_infrastructure.security.secrets import SecretLocatorUnavailable
from ordessa_server.bootstrap.security.secret_service import SecretServiceUnavailable
from ordessa_server.bootstrap.storage.product_database import Database
from ordessa_server.composition.configuration import request_integrity as request_integrity_module
from ordessa_server.composition.configuration.request_integrity import (
    RequestIntegrityConfigurationUnavailable,
    load_request_integrity_port,
)
from ordessa_server.configuration.credentials import CredentialRecords
from ordessa_units.public import SqliteUnitStore


KIND = "ordessa-request-integrity"
CREDENTIAL_ID = "credential_" + "a" * 32
LOCATOR = "controlled-test-locator"


class _ControlledSecretStore:
    def __init__(self, value=b"t" * 32, failure=None):
        self.value = value
        self.failure = failure
        self.read_locators = []

    def read(self, locator):
        self.read_locators.append(locator)
        if self.failure is not None:
            raise self.failure
        return self.value


def _runtime_sources(tmp_path):
    root = (tmp_path / "server").resolve()
    root.mkdir()
    database = Database(root)
    database.initialize()
    records = CredentialRecords(database)
    unit_store = SqliteUnitStore(root / "state" / "core.sqlite", writer_token="test-writer")
    return root, records, unit_store


def _write_reference(root, credential_id=CREDENTIAL_ID):
    path = root / "state" / "request-integrity.json"
    path.write_text(json.dumps({"schemaVersion": 1, "credentialId": credential_id}), encoding="utf-8")
    path.chmod(0o600)
    return path


def test_missing_reference_disables_only_this_optional_port(tmp_path):
    root, records, unit_store = _runtime_sources(tmp_path)
    try:
        assert load_request_integrity_port(
            data_root=root, records=records, secret_store=None, unit_store=None,
        ) is None
    finally:
        unit_store.close()


def test_valid_reference_uses_original_tombstone_query_and_exact_key_id(tmp_path):
    root, records, unit_store = _runtime_sources(tmp_path)
    secret_store = _ControlledSecretStore()
    records.register(CREDENTIAL_ID, KIND, LOCATOR)
    _write_reference(root)
    try:
        port = load_request_integrity_port(
            data_root=root, records=records, secret_store=secret_store,
            unit_store=unit_store,
        )
        assert port.describe().key_id == CREDENTIAL_ID
        assert secret_store.read_locators == [LOCATOR]
        request = RequestKey("env-test", "principal-test", "request-test")
        mac = port.fingerprint(request, "binding", "content")
        port.rotate("next-key", b"n" * 32)
        unit_store.record_key_tombstone(CREDENTIAL_ID)
        with pytest.raises(UnitComparisonUnavailable):
            port.verify(CREDENTIAL_ID, mac, request, "binding", "content")
    finally:
        unit_store.close()


def test_wrong_kind_refuses_without_reading_secret_store(tmp_path):
    root, records, unit_store = _runtime_sources(tmp_path)
    secret_store = _ControlledSecretStore()
    records.register(CREDENTIAL_ID, "provider-api-key", LOCATOR)
    _write_reference(root)
    try:
        with pytest.raises(RequestIntegrityConfigurationUnavailable):
            load_request_integrity_port(
                data_root=root, records=records, secret_store=secret_store,
                unit_store=unit_store,
            )
        assert secret_store.read_locators == []
    finally:
        unit_store.close()


def test_tombstoned_active_key_refuses_before_secret_store_read(tmp_path):
    root, records, unit_store = _runtime_sources(tmp_path)
    secret_store = _ControlledSecretStore()
    records.register(CREDENTIAL_ID, KIND, LOCATOR)
    _write_reference(root)
    unit_store.record_key_tombstone(CREDENTIAL_ID)
    try:
        with pytest.raises(RequestIntegrityConfigurationUnavailable):
            load_request_integrity_port(
                data_root=root, records=records, secret_store=secret_store,
                unit_store=unit_store,
            )
        assert secret_store.read_locators == []
    finally:
        unit_store.close()


def test_wrong_key_length_refuses_without_returning_a_port(tmp_path):
    root, records, unit_store = _runtime_sources(tmp_path)
    secret_store = _ControlledSecretStore(b"x" * 31)
    records.register(CREDENTIAL_ID, KIND, LOCATOR)
    _write_reference(root)
    try:
        with pytest.raises(RequestIntegrityConfigurationUnavailable):
            load_request_integrity_port(
                data_root=root, records=records, secret_store=secret_store,
                unit_store=unit_store,
            )
    finally:
        unit_store.close()


@pytest.mark.parametrize("failure", [
    SecretServiceUnavailable("SECRET_SERVICE_LOCKED"),
    SecretLocatorUnavailable(LOCATOR),
    RuntimeError("private locator and provider details"),
])
def test_secret_store_failures_refuse_without_leaking_details(tmp_path, failure):
    root, records, unit_store = _runtime_sources(tmp_path)
    secret_store = _ControlledSecretStore(failure=failure)
    records.register(CREDENTIAL_ID, KIND, LOCATOR)
    _write_reference(root)
    try:
        with pytest.raises(RequestIntegrityConfigurationUnavailable) as error:
            load_request_integrity_port(
                data_root=root, records=records, secret_store=secret_store,
                unit_store=unit_store,
            )
        assert LOCATOR not in str(error.value)
        assert "private locator" not in str(error.value)
        assert secret_store.read_locators == [LOCATOR]
    finally:
        unit_store.close()


def test_unregistered_reference_refuses_before_secret_store_read(tmp_path):
    root, records, unit_store = _runtime_sources(tmp_path)
    secret_store = _ControlledSecretStore()
    _write_reference(root)
    try:
        with pytest.raises(RequestIntegrityConfigurationUnavailable):
            load_request_integrity_port(
                data_root=root, records=records, secret_store=secret_store,
                unit_store=unit_store,
            )
        assert secret_store.read_locators == []
    finally:
        unit_store.close()


@pytest.mark.parametrize("mode", [0o644, 0o640])
def test_insecure_reference_permissions_refuse_before_store_read(tmp_path, mode):
    root, records, unit_store = _runtime_sources(tmp_path)
    secret_store = _ControlledSecretStore()
    records.register(CREDENTIAL_ID, KIND, LOCATOR)
    path = _write_reference(root)
    path.chmod(mode)
    try:
        with pytest.raises(RequestIntegrityConfigurationUnavailable):
            load_request_integrity_port(
                data_root=root, records=records, secret_store=secret_store,
                unit_store=unit_store,
            )
        assert secret_store.read_locators == []
    finally:
        unit_store.close()


def test_symlinked_reference_refuses_before_store_read(tmp_path):
    root, records, unit_store = _runtime_sources(tmp_path)
    secret_store = _ControlledSecretStore()
    records.register(CREDENTIAL_ID, KIND, LOCATOR)
    real = root / "state" / "reference-data"
    real.write_text(json.dumps({"schemaVersion": 1, "credentialId": CREDENTIAL_ID}), encoding="utf-8")
    real.chmod(0o600)
    (root / "state" / "request-integrity.json").symlink_to(real.name)
    try:
        with pytest.raises(RequestIntegrityConfigurationUnavailable):
            load_request_integrity_port(
                data_root=root, records=records, secret_store=secret_store,
                unit_store=unit_store,
            )
        assert secret_store.read_locators == []
    finally:
        unit_store.close()


def test_reference_replacement_during_read_is_rejected(tmp_path, monkeypatch):
    root, records, unit_store = _runtime_sources(tmp_path)
    secret_store = _ControlledSecretStore()
    records.register(CREDENTIAL_ID, KIND, LOCATOR)
    path = _write_reference(root)
    original_read = request_integrity_module.os.read
    replaced = False

    def replace_after_read(fd, size):
        nonlocal replaced
        data = original_read(fd, size)
        if not replaced and data:
            replacement = path.with_suffix(".replacement")
            replacement.write_text(json.dumps({"schemaVersion": 1, "credentialId": CREDENTIAL_ID}),
                                   encoding="utf-8")
            replacement.chmod(0o600)
            os.replace(replacement, path)
            replaced = True
        return data

    monkeypatch.setattr(request_integrity_module.os, "read", replace_after_read)
    try:
        with pytest.raises(RequestIntegrityConfigurationUnavailable):
            load_request_integrity_port(
                data_root=root, records=records, secret_store=secret_store,
                unit_store=unit_store,
            )
        assert secret_store.read_locators == []
    finally:
        unit_store.close()


@pytest.mark.parametrize("body", [
    '{"schemaVersion":1,"credentialId":"' + CREDENTIAL_ID
    + '","credentialId":"' + CREDENTIAL_ID + '"}',
    '{"schemaVersion":1,"credentialId":"' + CREDENTIAL_ID + '","key":"ignored"}',
])
def test_duplicate_or_extra_configuration_fields_refuse(tmp_path, body):
    root, records, unit_store = _runtime_sources(tmp_path)
    secret_store = _ControlledSecretStore()
    path = root / "state" / "request-integrity.json"
    path.write_text(body, encoding="utf-8")
    path.chmod(0o600)
    try:
        with pytest.raises(RequestIntegrityConfigurationUnavailable):
            load_request_integrity_port(
                data_root=root, records=records, secret_store=secret_store,
                unit_store=unit_store,
            )
        assert secret_store.read_locators == []
    finally:
        unit_store.close()


def test_record_database_from_another_root_refuses(tmp_path):
    root = (tmp_path / "target").resolve()
    root.mkdir()
    other = (tmp_path / "other").resolve()
    other.mkdir()
    database = Database(other)
    database.initialize()
    records = CredentialRecords(database)
    with pytest.raises(RequestIntegrityConfigurationUnavailable):
        load_request_integrity_port(
            data_root=root, records=records, secret_store=_ControlledSecretStore(),
            unit_store=None,
        )

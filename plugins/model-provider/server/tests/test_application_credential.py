from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from ordessa_model_provider.catalog import ModelCatalogService
from ordessa_server.errors import ServerError


def catalog():
    value = ModelCatalogService(Mock(), Mock(), harnesses=Mock(), credentials=Mock(), secret_store=Mock())
    value.harnesses.get.return_value = SimpleNamespace(credential_kind='api_key')
    value.credentials.get.return_value = {'secret_locator': 'private-location'}
    value.secret_store.read.return_value = b'synthetic-key'
    return value


def test_backend_application_helper_resolves_only_validated_ref():
    value = catalog()
    assert value.application_credential('ref://key', harness_id='codex') == 'synthetic-key'
    value.credentials.get.assert_called_once_with('key', kind='api_key')
    assert value.application_credential(None, harness_id='codex') is None


@pytest.mark.parametrize('problem', ['store', 'ref', 'missing', 'empty', 'newline'])
def test_credential_failure_never_becomes_anonymous_or_leaks_error(problem):
    value = catalog()
    ref = 'ref://key'
    if problem == 'store': value.secret_store = None
    if problem == 'ref': ref = 'raw-secret'
    if problem == 'missing': value.secret_store.read.side_effect = ValueError('synthetic-secret-location')
    if problem == 'empty': value.secret_store.read.return_value = b''
    if problem == 'newline': value.secret_store.read.return_value = b'synthetic\nkey'
    with pytest.raises(ServerError) as error:
        value.application_credential(ref, harness_id='codex')
    assert error.value.code == 'CREDENTIAL_UNRESOLVED'
    assert 'synthetic' not in str(error.value)

from ordessa_infrastructure.security.secrets import MAX_SECRET_BYTES, SecretLocatorUnavailable, SecretStore


def test_original_secret_bound_and_unavailable_code_locator_message():
    assert MAX_SECRET_BYTES == 1024 * 1024
    error = SecretLocatorUnavailable('credential_synthetic.dpapi')
    assert error.code == 'CREDENTIAL_NOT_AVAILABLE'
    assert error.locator == 'credential_synthetic.dpapi'
    assert 'not available on this machine' in str(error)
    assert 'never imported here' in str(error)
    assert not hasattr(error, 'secret')


def test_protocol_retains_file_read_delete_without_concrete_backend():
    assert callable(SecretStore.import_file)
    assert callable(SecretStore.read)
    assert callable(SecretStore.delete)

"""Product credential injection; no system keyring or existing keys accessed."""
from fastapi.testclient import TestClient

from ordessa_server_product.composition import create_composition


class UnavailableStore:
    def import_file(self, source, kind):
        class StoreLocked(RuntimeError):
            code = 'SECRET_STORE_LOCKED'
        raise StoreLocked('private backend details must never cross wire')


def test_product_injects_one_store_and_import_refuses_without_record(monkeypatch, tmp_path):
    from ordessa_server_product import platform_secrets
    from ordessa_server.transport.http import create_app
    store = UnavailableStore()
    monkeypatch.setattr(platform_secrets, 'product_secret_store', lambda root: store)
    runtime = create_composition().default_runtime(tmp_path / 'data')
    try:
        assert runtime.secret_store is store
        assert runtime.plugin_host.provided_port('model_provider.catalog').secret_store is store
        with TestClient(create_app(runtime), base_url='http://127.0.0.1') as client:
            source = tmp_path / 'synthetic-key'
            source.write_text('synthetic-not-a-real-credential')
            response = client.post('/api/v1/credentials',
                headers={'Authorization': f'Bearer {runtime.token}',
                         'Idempotency-Key': 'keyring-refusal-0001'},
                json={'kind': 'api-key', 'source_path': str(source),
                      'confirm_source_path': str(source)})
            assert response.status_code == 503
            assert response.json()['error']['code'] == 'SECRET_STORE_LOCKED'
            assert 'private backend' not in response.text
            assert 'synthetic-not' not in response.text
            assert runtime.plugin_host.provided_port('product.service').list_credentials() == []
    finally:
        runtime.stop()

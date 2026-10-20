"""Product credential injection; no system keyring or existing keys accessed."""
from fastapi.testclient import TestClient

from ordessa_server.composition.configuration.product_selection import create_host_product_composition as create_composition


class UnavailableStore:
    def import_file(self, source, kind):
        class StoreLocked(RuntimeError):
            code = 'SECRET_STORE_LOCKED'
        raise StoreLocked('private backend details must never cross wire')


def test_product_injects_one_store_and_import_refuses_without_record(monkeypatch, tmp_path):
    from ordessa_server.bootstrap.security import secret_service as platform_secrets
    from ordessa_interfaces.http import create_app
    store = UnavailableStore()
    monkeypatch.setattr(platform_secrets, 'product_secret_store', lambda root: store)
    runtime = create_composition().default_runtime(tmp_path / 'data')
    try:
        assert runtime.secret_store is store
        assert runtime.plugin_host.provided_port('model_provider.catalog').secret_store is store
        # 032: the credential HTTP import endpoint retired with server-compat
        # (registered gap: accounts/credential import has no new owner), so the
        # store-injection facts above are what this test still pins. The
        # retired route is asserted absent rather than silently dropped.
        assert runtime.plugin_host.provided_port('product.service') is None
    finally:
        runtime.stop()

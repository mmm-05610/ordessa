"""Old three-family C2 batch must not bypass independent provider admission."""
import pytest
from ordessa_environment_api import GuaranteeUnavailableError
from ordessa_harness.configuration.model.plugin import ModelProviderAdaptersPlugin


def test_old_model_batch_refuses_without_context_or_effects(tmp_path, monkeypatch):
    monkeypatch.setattr('subprocess.Popen', lambda *a, **k: pytest.fail('no native effect'))
    with pytest.raises(GuaranteeUnavailableError, match='independent provider'):
        ModelProviderAdaptersPlugin().build(None)
    assert list(tmp_path.iterdir()) == []


def test_old_model_metadata_keeps_persisted_identity():
    descriptor = ModelProviderAdaptersPlugin().descriptor()
    assert descriptor.id == 'ordessa.model-provider.adapters'


def test_retired_model_import_does_not_load_three_old_registrations(monkeypatch):
    import builtins
    import importlib
    from ordessa_harness.configuration.model import plugin
    original = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name.endswith('registration'):
            pytest.fail('retired batch imported a brand registration: ' + name)
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', guarded)
    importlib.reload(plugin)
    with pytest.raises(GuaranteeUnavailableError):
        plugin.ModelProviderAdaptersPlugin().build(None)


def test_host_activation_does_not_publish_retired_model_batch(tmp_path):
    from ordessa_server.bootstrap import build_runtime
    runtime = build_runtime(tmp_path / 'isolated-product')
    try:
        before = tuple(runtime.plugin_host.contributions('harness.configuration-adapters'))
        with pytest.raises(GuaranteeUnavailableError, match='independent provider'):
            runtime.plugin_host.activate(ModelProviderAdaptersPlugin())
        assert tuple(runtime.plugin_host.contributions('harness.configuration-adapters')) == before
    finally:
        runtime.stop()

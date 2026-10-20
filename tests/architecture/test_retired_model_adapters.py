"""Retired aggregate has no reachable shell; independent C2 capability remains."""
import importlib
from pathlib import Path
import pytest

HISTORICAL_MODEL_PROVIDER_ID = 'ordessa.model-provider.adapters'
RETIRED_MODULE = 'ordessa_server_product.harness_adapters.configuration.model.plugin'


def test_old_model_batch_refuses_without_context_or_effects(tmp_path, monkeypatch):
    from ordessa_server.composition.c2_providers import configuration_provider_plugin
    monkeypatch.setattr('subprocess.Popen', lambda *a, **k: pytest.fail('no native effect'))
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(RETIRED_MODULE)
    with pytest.raises(TypeError):
        configuration_provider_plugin()
    assert list(tmp_path.iterdir()) == []


def test_old_model_metadata_keeps_persisted_identity():
    # Historical identity is a migration fact, never an active plugin shell.
    assert HISTORICAL_MODEL_PROVIDER_ID == 'ordessa.model-provider.adapters'
    root = Path(__file__).resolve().parents[2]
    assert not (root / 'products/server/src/ordessa_server_product/harness_adapters/configuration/model/plugin.py').exists()


def test_retired_model_import_does_not_load_three_old_registrations(monkeypatch):
    import builtins
    from ordessa_server.composition import c2_providers
    original = builtins.__import__
    def guarded(name, *args, **kwargs):
        if name.endswith('registration'):
            pytest.fail('unselected brand registration import: ' + name)
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', guarded)
    importlib.reload(c2_providers)
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(RETIRED_MODULE)


def test_host_activation_does_not_publish_retired_model_batch(tmp_path, monkeypatch):
    from ordessa_server.composition.runtime import build_runtime
    from ordessa_server.composition.c2_providers import configuration_provider_plugin
    from ordessa_harness_codex.registration import configuration_adapters
    monkeypatch.setattr('subprocess.Popen', lambda *a, **k: pytest.fail('no native effect'))
    runtime = build_runtime(tmp_path / 'isolated-product')
    try:
        before = tuple(runtime.plugin_host.contributions('harness.configuration-adapters'))
        with pytest.raises(ModuleNotFoundError):
            importlib.import_module(RETIRED_MODULE)
        assert tuple(runtime.plugin_host.contributions('harness.configuration-adapters')) == before
        selected = configuration_provider_plugin(configuration_adapters=configuration_adapters)
        assert selected.descriptor().id == 'ordessa.model-provider.codex'
        assert selected.descriptor().id != HISTORICAL_MODEL_PROVIDER_ID
        runtime.plugin_host.activate(selected)
        views = tuple(runtime.plugin_host.contributions('harness.configuration-adapters'))
        assert len(views) == len(before) + 1
        assert views[-1].payload.descriptor.harness_id == 'codex'
        assert all(view.payload.descriptor.harness_id == 'codex' for view in views[len(before):])
    finally:
        runtime.stop()

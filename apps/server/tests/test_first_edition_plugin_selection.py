"""Current edition refuses unrelated legacy plugins and extra brand selection."""
from ordessa_server_product.composition import ProductCompositionUnavailable
import sys,importlib.abc
import pytest
from ordessa_server.composition.configuration.product_selection import create_host_product_composition

LEGACY_ROOTS=frozenset({'ordessa_skills','ordessa_workspace','ordessa_model_provider',
    'ordessa_harness_codex','ordessa_harness_claude_code','ordessa_harness_opencode',
    'ordessa_harness_hermes','ordessa_harness_dsh','ordessa_harness_kilo','ordessa_harness_grok_build',
    'ordessa_harness_qwen'})


def test_default_product_has_no_legacy_imports_or_implicit_unit_authority(tmp_path,monkeypatch):
    from ordessa_server.composition.runtime import build_runtime
    attempts=[]
    class RejectLegacy(importlib.abc.MetaPathFinder):
        def find_spec(self,fullname,path=None,target=None):
            if fullname.split('.')[0] in LEGACY_ROOTS or fullname=='pacthold' or fullname.startswith('pacthold.'):
                attempts.append(fullname)
                raise AssertionError('retired edition dependency: '+fullname)
    monkeypatch.setattr(sys,'meta_path',[RejectLegacy(),*sys.meta_path])
    product=create_host_product_composition()
    assert product.default_plugins()==()
    assert product.server_contribution_points()==()
    assert tuple(item.harness_type for item in product.harness_registry.all())==('pi',)
    runtime=build_runtime(tmp_path/'root')
    runtime.start()
    assert runtime.plugin_host.active_ids()==()
    assert runtime.unit_runtime.context.owner_ports is None
    runtime.stop()
    runtime.start()
    runtime.stop()
    assert attempts==[]


def test_legacy_composition_and_model_catalog_are_explicitly_unsupported():
    product=create_host_product_composition()
    with pytest.raises(ProductCompositionUnavailable,match='unsupported in this edition'):
        product.compatibility_plugins()
    with pytest.raises(ProductCompositionUnavailable,match='unsupported in this edition'):
        product.bind_model_configuration_catalog(object())
    with pytest.raises(ProductCompositionUnavailable,match='unsupported in this edition'):
        product.default_plugins(secret_store=object())

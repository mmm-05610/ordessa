"""032: the native runtime assembly is retired; every route refuses
before any assembly, process, data or channel state.

No native process, model, installed artifact, credential or user service used.
Old model compiler/receipt tests remain separately owned and unchanged.
"""
from ordessa_server_product.composition import ProductCompositionUnavailable
from pathlib import Path

import pytest
from ordessa_server.composition.configuration.product_selection import create_host_product_composition as create_composition


@pytest.mark.parametrize('family', ['pi', 'codex', 'claude-code', 'claude'])
@pytest.mark.parametrize('route', ['primary', 'profile', 'additional'])
def test_retired_native_family_refuses_before_assembly_or_data(tmp_path, monkeypatch, family, route):
    composition = create_composition()
    def forbidden(*args, **kwargs):
        pytest.fail('retired native family reached legacy assembly')
    monkeypatch.setattr(composition, '_assemble_legacy_chain', forbidden)
    monkeypatch.setattr('subprocess.Popen', forbidden)
    options = dict(plugin_root=tmp_path / 'absent-plugin-root', harness_id='goose',
                   adapter_command='/absent/adapter')
    if route == 'primary': options['harness_id'] = family
    elif route == 'profile': options['native_profile_harnesses'] = (family,)
    else: options['additional_adapters'] = ({'harnessId': family, 'command': '/absent/adapter', 'args': []},)
    data = tmp_path / 'data'
    with pytest.raises(ProductCompositionUnavailable, match='native runtime assembly retired'):
        composition.native_runtime(data, **options)
    assert not data.exists() and not options['plugin_root'].exists()
    assert composition._native_channels_selected is False
    assert list(tmp_path.iterdir()) == []


def test_implicit_pi_profile_bridge_cannot_bypass_retirement(tmp_path, monkeypatch):
    composition = create_composition()
    monkeypatch.setattr(composition, '_assemble_legacy_chain', lambda: pytest.fail('legacy assembly'))
    with pytest.raises(ProductCompositionUnavailable, match='native runtime assembly retired'):
        composition.native_runtime(tmp_path / 'data', plugin_root=tmp_path / 'plugins',
            harness_id='goose', adapter_command='/absent/adapter', pi_profile_bridge=True)
    assert list(tmp_path.iterdir()) == []
    assert composition._native_channels_selected is False


@pytest.mark.parametrize('family', ['copilot', 'gemini-cli', 'goose', 'kimi', 'opencode', 'hermes', 'dsh', 'kilo', 'qwen', 'vibe'])
def test_unmigrated_family_also_refuses_after_the_assembly_retirement(tmp_path, monkeypatch, family):
    """032: the pre-retirement boundary (migrated families refused, unmigrated
    families still reaching the original assembly) is gone with the assembly
    itself — every family now refuses before any legacy chain, process or
    data write, not just the migrated ones."""
    composition = create_composition()
    class AssemblyReached(Exception): pass
    def reached(): raise AssemblyReached()
    monkeypatch.setattr(composition, '_assemble_legacy_chain', reached)
    with pytest.raises(ProductCompositionUnavailable, match='native runtime assembly retired'):
        composition.native_runtime(tmp_path / 'data', plugin_root=tmp_path / 'plugins',
            harness_id=family, adapter_command='/absent/adapter')
    assert not (tmp_path / 'data').exists()


@pytest.mark.parametrize('family', ['pi', 'codex', 'claude-code'])
def test_retirement_precedes_old_model_and_runtime_imports(tmp_path, monkeypatch, family):
    import builtins
    composition = create_composition()
    original_import = builtins.__import__
    imports = []
    def guarded(name, *args, **kwargs):
        if name.startswith(('ordessa_server_compat', 'ordessa_server.composition.configuration.model', 'ordessa_model_provider')):
            imports.append(name)
            pytest.fail('retired selection imported old runtime: ' + name)
        return original_import(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', guarded)
    with pytest.raises(ProductCompositionUnavailable):
        composition.native_runtime(tmp_path / 'data', plugin_root=tmp_path / 'plugins',
            harness_id=family, adapter_command='/absent/adapter')
    assert imports == [] and list(tmp_path.iterdir()) == []


def test_default_product_selects_acp_declarations_but_no_old_four_family_factory():
    """The product's real selected plugin tuple cannot publish old C1 providers.

    Captured launch/production declarations remain independently callable.
    This selection check does not claim a new Agent Unit provider is installed.
    """
    composition = create_composition()
    selected = tuple(plugin.descriptor().id for plugin in composition.default_plugins())
    assert selected == ()
    assert composition.server_contribution_points() == ()
    assert tuple(item.harness_type for item in composition.harness_registry.all()) == ('pi',)
    assert "harness-profile-store" not in selected
    assert not {"opencode", "hermes", "dsh", "kilo"}.intersection(selected)

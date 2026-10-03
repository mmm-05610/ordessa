import json
from types import SimpleNamespace

from pacthold.cli import main
from pacthold.cli.commands import plugins as plugin_commands
from pacthold.extensions import PluginDescriptor, PluginRegistration
from pacthold.extensions.loader import PluginLoadRecord, PluginLoadReport
from pacthold.work_core import ExtensionRegistry, ProviderDescriptor


class _Execution:
    def descriptor(self):
        return ProviderDescriptor("cli-execution", "CLI execution", "1")

    def input_limits(self):
        return {}

    def capabilities(self):
        return {"start": "supported"}

    def start(self, request):
        raise AssertionError("CLI diagnostics must not start providers")

    def observe(self, native_ref):
        raise AssertionError("CLI diagnostics must not observe providers")


def _fake_report(version="1", distribution_version=None):
    descriptor = PluginDescriptor("cli", "CLI", version, docs_url="https://example.test")
    record = PluginLoadRecord(
        "cli", "READY", descriptor,
        PluginRegistration(execution_providers=(_Execution(),)),
        distribution_name="cli-dist",
        distribution_version=distribution_version,
    )
    return ExtensionRegistry(), PluginLoadReport((record,))


def test_plugin_cli_json_shape_and_success(monkeypatch, capsys):
    monkeypatch.setattr(plugin_commands, "_load_report", _fake_report)
    assert main(["plugins", "inspect", "cli", "--json"]) == 0
    row = json.loads(capsys.readouterr().out)
    assert {"descriptor", "distribution_name", "distribution_version", "contracts",
            "resource_providers", "execution_providers", "diagnostics"} <= set(row)
    assert "secret" not in json.dumps(row).lower()
    assert main(["plugins", "doctor", "--json"]) == 0
    assert isinstance(json.loads(capsys.readouterr().out), list)


def test_plugin_cli_unknown_plugin_returns_two(monkeypatch, capsys):
    monkeypatch.setattr(plugin_commands, "_load_report", _fake_report)
    assert main(["plugins", "inspect", "missing"]) == 2
    assert "unknown plugin" in capsys.readouterr().err


def test_plugin_cli_warning_does_not_fail(monkeypatch):
    monkeypatch.setattr(plugin_commands, "_load_report", lambda: _fake_report("1", "2"))
    assert main(["plugins", "doctor", "cli"]) == 0

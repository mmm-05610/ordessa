from pacthold.extensions import PLUGIN_API_VERSION, PluginContext
import pytest
from ordessa_environment_api import GuaranteeUnavailableError
from ordessa_harness_codex.contracts import CodexContinuationV1
from ordessa_server_product.harness_adapters.plugin import create_plugin


def test_retired_codex_metadata_has_no_runtime_or_discovery_writes(
    tmp_path,
):
    context = PluginContext("1.9.0", tmp_path, tmp_path / "plugins" / "codex")

    plugin = create_plugin()
    descriptor = plugin.descriptor()
    assert descriptor.id == "codex"
    assert descriptor.api_version == PLUGIN_API_VERSION
    # AU003 retires the whole compat registration, including its control and
    # selector. The independent provider's positive route is tested through
    # CoreRegistry in test_codex_assembly.py, not this historical facade.
    with pytest.raises(GuaranteeUnavailableError, match="independent provider"):
        plugin.build(context)
    assert not context.plugin_data_dir.exists()
    assert not (context.agent_box_home / "profiles").exists()
    assert list(tmp_path.iterdir()) == []


def test_codex_continuation_contract_is_plugin_owned():
    assert CodexContinuationV1.contract_id == "agent-box.codex-continuation@1"
    assert CodexContinuationV1("thread-1").thread_id == "thread-1"

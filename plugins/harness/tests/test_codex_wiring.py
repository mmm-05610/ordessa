from pacthold.extensions import PluginContext
import pytest
from ordessa_environment_api import GuaranteeUnavailableError
from ordessa_harness.plugin import HarnessesPlugin
from ordessa_harness.codex.continuation import CodexContinuationResourceProvider
from pacthold.work_core import RefType


def test_unified_facade_refuses_runtime_without_registering_credentials(tmp_path):
    plugin = HarnessesPlugin()
    assert plugin.descriptor().id == "harnesses"
    with pytest.raises(GuaranteeUnavailableError, match="independent provider"):
        plugin.build(PluginContext("1", tmp_path, tmp_path / "harnesses"))
    assert list(tmp_path.iterdir()) == []

def test_continuation_resource_provider_accepts_only_governed_native_sources():
    provider = CodexContinuationResourceProvider()
    ref = provider.make_ref("thread-1", "codex-app-server")
    assert ref.type is RefType.SESSION
    assert provider.resolve("agent-box.codex-continuation@1", ref).thread_id == "thread-1"

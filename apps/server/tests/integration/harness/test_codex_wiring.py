import importlib.util
from ordessa_harness_codex.continuation import CodexContinuationResourceProvider
from pacthold.work_core import RefType


def test_retired_product_harness_plugin_entrypoint_is_absent(tmp_path):
    assert importlib.util.find_spec("ordessa_server_product.harness_adapters.plugin") is None
    assert list(tmp_path.iterdir()) == []


def test_continuation_resource_provider_accepts_only_governed_native_sources():
    provider = CodexContinuationResourceProvider()
    ref = provider.make_ref("thread-1", "codex-app-server")
    assert ref.type is RefType.SESSION
    assert provider.resolve("agent-box.codex-continuation@1", ref).thread_id == "thread-1"

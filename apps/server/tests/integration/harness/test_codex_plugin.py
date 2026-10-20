import importlib.util
from ordessa_harness_codex.contracts import CodexContinuationV1


def test_retired_product_factory_cannot_construct_profile_writer(tmp_path):
    assert importlib.util.find_spec("ordessa_server_product.harness_adapters.entrypoints") is None
    assert not (tmp_path / "profiles").exists()


def test_codex_continuation_contract_is_plugin_owned():
    assert CodexContinuationV1.contract_id == "agent-box.codex-continuation@1"
    assert CodexContinuationV1("thread-1").thread_id == "thread-1"

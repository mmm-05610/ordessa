"""One Harness distribution owns brands; common code stays neutral."""
import ast
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[2]
CORE = ROOT / "packages/execution/agents/src/ordessa_execution_agents/harness"
HARNESS_GROUP = ROOT / "plugins" / "harness"


def test_the_root_super_package_session_retired_and_brands_are_own_distributions():
    """032: the one root `ordessa-harness` distribution retired. Every brand is
    its own package with no automatic entry-point registration; the retired
    root shell (pyproject/setup/src) must stay absent."""
    assert not (HARNESS_GROUP / "pyproject.toml").exists()
    assert not (HARNESS_GROUP / "setup.py").exists()
    assert not (HARNESS_GROUP / "src" / "ordessa_harness").exists()
    for brand, module in {"dsh": "dsh", "kilo": "kilo", "qwen": "qwen", "opencode": "opencode",
                          "hermes": "hermes", "codex": "codex", "pi": "pi",
                          "claude-code": "claude-code"}.items():
        metadata = tomllib.loads((HARNESS_GROUP / brand / "pyproject.toml").read_text())
        assert metadata["project"]["name"] == f"ordessa-harness-{module}"
        assert "entry-points" not in metadata["project"], (
            f"{brand} must not resurrect an automatic registration entry point")


def test_canonical_implementation_does_not_import_compatibility_names():
    """The retired alias namespaces (`agent_box_harnesses`, `agent_box_harness_*`)
    stay retired: no module of the canonical package may import them."""
    retired = ("agent_box_harnesses", "agent_box_harness", "agent_box_harness.dsh",
               "agent_box_harness.qwen", "agent_box_harness.kilo")
    assert CORE.is_dir()
    assert any(CORE.rglob("*.py"))
    for path in CORE.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = ([node.module or ""] if isinstance(node, ast.ImportFrom) else
                     [alias.name for alias in node.names] if isinstance(node, ast.Import) else [])
            assert not any(name.startswith(retired) for name in names), path


def test_common_code_has_no_brand_dispatch_table():
    brands = {"codex", "claude", "opencode", "hermes", "dsh", "qwen", "kilo", "pi"}
    for directory in ("configuration", "providers/declarations", "transport"):
        assert (CORE / directory).is_dir()
        assert any((CORE / directory).rglob("*.py"))
        for path in (CORE / directory).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node, ast.Dict):
                    assert not any(key.value in brands for key in node.keys
                                   if isinstance(key, ast.Constant) and isinstance(key.value, str)), path


def test_common_code_does_not_implement_host_file_or_terminal_capabilities():
    forbidden = ("readTextFile", "writeTextFile", "createTerminal", "read_text_file",
                 "write_text_file", "terminal/create", "fs/read_text_file", "fs/write_text_file")
    for directory in ("configuration", "providers/declarations", "transport"):
        assert (CORE / directory).is_dir()
        assert any((CORE / directory).rglob("*.py"))
        for path in (CORE / directory).rglob("*.py"):
            assert not any(name in path.read_text() for name in forbidden), path


def test_registry_and_runtime_are_owned_here():
    """032: the declaration and neutral runtime assets stay with the group; each
    brand's knowledge lives in its own package; the registry loader and the host
    binding live in the product assembly."""
    assert (ROOT / "apps/server/src/ordessa_server/composition/selected_harness_catalog.py").is_file()
    binding = (ROOT / "apps/server/deployment/default-product/src" / "ordessa_server_product"
               / "harness_adapters")
    assert (CORE / "providers/declarations/loader.py").is_file()
    assert (ROOT / 'apps/server/src/ordessa_server/composition/native_channels/access_entry.mjs').is_file()
    assert (CORE / "transport/vendor/harness_remote/SOURCE.json").is_file()
    for brand in ("codex", "claude-code", "opencode", "hermes", "dsh", "qwen", "kilo", "pi"):
        module = "ordessa_harness_" + brand.replace("-", "_")
        assert (HARNESS_GROUP / brand / "src" / module / "native.py").is_file()

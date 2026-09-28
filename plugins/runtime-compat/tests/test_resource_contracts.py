from pathlib import Path
import ast

import pacthold
import pytest
from pacthold_runtime_compat.resource_contracts import CONTRACT_TYPES
from pacthold_runtime_compat.resource_contracts.agent_box_profile_v1 import AgentBoxProfileV1
from pacthold_runtime_compat.resource_contracts.prompt_fragment_v1 import PromptFragmentV1
from pacthold_runtime_compat.resource_contracts.workspace_v1 import WorkspaceV1


def test_initial_contract_registry_is_versioned_and_immutable():
    assert set(CONTRACT_TYPES) == {
        "agent-box.workspace@1",
        "agent-box.prompt-fragment@1",
        "agent-box.profile@1",
        "agent-box.credential@1",
        "agent-box.skill@1",
    }
    assert WorkspaceV1(Path("/tmp/workspace"), "sha256:workspace").contract_id == "agent-box.workspace@1"
    assert PromptFragmentV1("requirements", "do the work", "sha256:prompt").digest
    assert AgentBoxProfileV1("default", "example-agent", "sha256:profile").agent_type == "example-agent"

    with pytest.raises((AttributeError, TypeError)):
        WorkspaceV1(Path("/tmp/workspace"), "sha256:workspace").path = Path("/tmp/other")


@pytest.mark.parametrize(
    "value",
    [
        lambda: WorkspaceV1(Path("relative"), "sha256:x"),
        lambda: PromptFragmentV1("", "content", "sha256:x"),
        lambda: AgentBoxProfileV1("name", "", "sha256:x"),
    ],
)
def test_contract_fields_are_validated(value):
    with pytest.raises(ValueError):
        value()


def test_contract_package_has_no_core_or_provider_dependency():
    # Import graph check is intentionally source-level and limited to the
    # package's own modules; contract values remain provider-neutral.
    # specs/010 T009: the package lives in the compatibility assembly now;
    # the scan follows the installed package location instead of cwd.
    import pacthold_runtime_compat.resource_contracts as contract_package
    root = Path(contract_package.__file__).resolve().parent
    for path in root.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "pacthold.work_core" not in text
        assert "pacthold.work" not in text
        assert "providers" not in text


def test_provider_neutral_core_modules_do_not_import_provider_implementations():
    modules = (
        "models.py",
        "projection.py",
        "events.py",
        "errors.py",
        "registry.py",
        "repository.py",
        "services.py",
    )
    forbidden = ("git", "codex", "langgraph", "acp", "mcp", "bwrap")
    root = Path(pacthold.__file__).resolve().parent / "work_core"
    for filename in modules:
        tree = ast.parse((root / filename).read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = [item.name.lower() for item in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported = [(node.module or "").lower()]
            else:
                continue
            assert not any(token in name for name in imported for token in forbidden)


def test_work_core_source_contains_no_codex_product_implementation():
    root = Path(pacthold.__file__).resolve().parent / "work_core"
    for path in root.rglob("*.py"):
        assert "codex" not in path.read_text(encoding="utf-8").lower(), path

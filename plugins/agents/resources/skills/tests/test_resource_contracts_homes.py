from pathlib import Path
import ast

import pytest
from ordessa_skills.resource_contracts import AgentSkillV1
from ordessa_execution_agents.profiles import AgentBoxProfileV1
from ordessa_execution_agents.harness.definitions.credentials import CredentialRefV1
from ordessa_units.definitions.material_delivery import PromptFragmentV1
from ordessa_units.definitions.material_delivery import WorkspaceV1

CONTRACT_TYPES = {
    WorkspaceV1.contract_id: WorkspaceV1,
    PromptFragmentV1.contract_id: PromptFragmentV1,
    AgentBoxProfileV1.contract_id: AgentBoxProfileV1,
    CredentialRefV1.contract_id: CredentialRefV1,
    AgentSkillV1.contract_id: AgentSkillV1,
}


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


def test_contract_owners_have_no_retired_core_or_provider_dependency():
    # Import graph check is intentionally source-level and limited to the
    # package's own modules; contract values remain provider-neutral.
    # The contracts live at their actual owners; inspect installed modules.
    import ordessa_skills.resource_contracts as skill_contract
    import ordessa_execution_agents.profiles as profile_contract
    import ordessa_execution_agents.harness.definitions.credentials as credential_contract
    import ordessa_units.definitions.material_delivery as prompt_contract
    import ordessa_units.definitions.material_delivery as workspace_contract
    for module in (skill_contract, profile_contract, credential_contract,
                   prompt_contract, workspace_contract):
        text = Path(module.__file__).read_text(encoding="utf-8")
        assert "pacthold.work_core" not in text
        assert "pacthold.work" not in text
        imports = [node.module or "" for node in ast.walk(ast.parse(text))
                   if isinstance(node, ast.ImportFrom)]
        imports += [item.name for node in ast.walk(ast.parse(text))
                    if isinstance(node, ast.Import) for item in node.names]
        assert not any(name.startswith(("ordessa_harness_", "ordessa_server")) for name in imports)


def test_unit_owner_does_not_import_provider_implementations():
    import ordessa_units
    forbidden = ("ordessa_harness_", "ordessa_skills", "ordessa_prompts",
                 "ordessa_environments_local", "ordessa_environments_openshell",
                 "ordessa_server", "pacthold.work_core")
    root = Path(ordessa_units.__file__).resolve().parent
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported = [item.name.lower() for item in node.names]
            elif isinstance(node, ast.ImportFrom):
                imported = [(node.module or "").lower()]
            else:
                continue
            assert not any(name.startswith(token) for name in imported for token in forbidden), path


def test_unit_owner_contains_no_codex_product_implementation():
    import ordessa_units
    root = Path(ordessa_units.__file__).resolve().parent
    for path in root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        # Native record codecs retain their existing Codex format identifiers;
        # executable brand provider implementations belong to the plugin.
        assert "ordessa_harness_codex" not in source, path
        assert "class CodexRuntimeProvider" not in source, path

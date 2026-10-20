"""Agents is a mechanism package: the environment owner is composed by units."""
import ast
from pathlib import Path

import ordessa_execution_agents


ROOT = Path(ordessa_execution_agents.__file__).parent
ENVIRONMENT_OWNER = "ordessa_environments"


def environment_imports(source):
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and not node.level:
            names = [node.module or ""]
        else:
            continue
        for name in names:
            root = name.split(".")[0]
            if root == ENVIRONMENT_OWNER or root.startswith(ENVIRONMENT_OWNER + "_"):
                found.append(name)
    return found


def test_agents_source_never_imports_the_environment_owner():
    assert list(ROOT.rglob("*.py"))
    offenders = {
        str(path): environment_imports(path.read_text())
        for path in ROOT.rglob("*.py")
    }
    assert not {path: names for path, names in offenders.items() if names}


def test_guard_detects_environment_and_environment_provider_imports():
    assert environment_imports("from ordessa_environments import ProcessHandle")
    assert environment_imports("import ordessa_environments.definitions")
    assert environment_imports("from ordessa_environments_local import provider")
    assert not environment_imports(
        "from ordessa_infrastructure.identifiers import RequestKey"
    )
    assert not environment_imports("from .transport import ProcessChannel")

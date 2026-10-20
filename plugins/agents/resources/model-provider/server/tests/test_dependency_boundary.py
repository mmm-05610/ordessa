# migrated from plugins/model-provider@9305563719d25e04076b9221a7284660bd8f8642 (tests/test_dependency_boundary.py, verbatim)
"""FR-ARCH-3: the dependency direction, enforced on the source tree.

The core must not import Profile, Chat, the legacy compatibility core or host
business modules - only the host's generic vocabulary and its own package.
The counterexample this suite pins: any new import line naming a forbidden
target fails here, so the boundary cannot rot silently while features land.
"""
from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "ordessa_model_provider"

# Generic vocabulary now belongs to public SDK/Interfaces and Infrastructure.
# Host and retired compatibility imports are refused, including their roots.
ALLOWED_ROOTS = {
    "__future__", "hashlib", "json", "typing", "dataclasses", "ipaddress",
    "socket", "time", "types", "urllib", "ordessa_model_provider",
    "contextlib", "pathlib", "re", "sqlite3", "unicodedata", "collections",
    "server_plugin_api", "ordessa_execution_agents", "ordessa_interfaces",
    "ordessa_infrastructure",
}
PUBLIC_DEPENDENCIES = {
    "ordessa_execution_agents": ("ordessa_execution_agents.harness.definitions",),
    "ordessa_interfaces": (
        "ordessa_interfaces.system_access.contracts.idempotency",
        "ordessa_interfaces.system_access.contracts.storage",
    ),
    "ordessa_infrastructure": ("ordessa_infrastructure.identifiers",),
}


def _allowed(module):
    root = module.split(".")[0]
    if root not in ALLOWED_ROOTS:
        return False
    if root in PUBLIC_DEPENDENCIES:
        return any(module == leaf or module.startswith(leaf + ".")
                   for leaf in PUBLIC_DEPENDENCIES[root])
    return True


def _imports(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            found.append(node.module)
    return found


def test_core_imports_stay_inside_the_allowed_boundary():
    violations = []
    for path in sorted(SRC.glob("*.py")):
        for module in _imports(path):
            if not _allowed(module):
                violations.append(f"{path.name}: imports {module}")
    assert violations == []


def test_ordessa_server_imports_are_the_documented_generic_leaves():
    violations = []
    for path in sorted(SRC.glob("*.py")):
        for module in _imports(path):
            if module.split(".")[0] in {"ordessa_server", "ordessa_server_compat"}:
                violations.append(f"{path.name}: imports host module {module}")
    assert violations == []


def test_no_profile_or_chat_name_is_reachable_from_the_core():
    """A textual sweep alongside the AST walk: profile/chat belong to the
    contribution adapters, which depend on the core - never the reverse."""
    forbidden = ("profile", "chat")
    hits = []
    for path in sorted(SRC.glob("*.py")):
        for module in _imports(path):
            lowered = module.lower()
            if any(word in lowered for word in forbidden) and not lowered.startswith("ordessa_model_provider"):
                hits.append(f"{path.name}: imports {module}")
    assert hits == []


def test_boundary_refuses_planted_host_legacy_and_private_contract_imports(tmp_path):
    offender = tmp_path / "offender.py"
    offender.write_text(
        "import ordessa_server\n"
        "from ordessa_server_compat.wire_validators import validate\n"
        "from ordessa_execution_api.private import authority\n"
        "from ordessa_interfaces.system_access.access_control import service\n"
    )
    imports = _imports(offender)
    assert len(imports) == 4
    assert all(not _allowed(module) for module in imports)
    assert _allowed("ordessa_execution_agents.harness.definitions")
    assert not _allowed("ordessa_execution_api.harness")
    assert _allowed("ordessa_interfaces.system_access.contracts.storage")

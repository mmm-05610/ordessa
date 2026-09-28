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

#: The allowed roots. `ordessa_server` is the host's generic vocabulary
#: (errors/records/ids/idempotency/wire helpers) - business modules of the
#: host would violate the same rule, so anything beyond the listed leaves
#: fails too.
#: foundation@8844c475bc adaptation: the host's own handlers docstring
#: (T014-S2c) directs plugins to `server_plugin_api.wire_shape` for the shared
#: param-shape helpers and to `ordessa_server_compat.wire_validators` for the
#: domain-shape validators — the validator module is shared vocabulary, not
#: the legacy business line, so the blanket compat ban gains this one leaf.
#: 014 PB-3 adaptation (dispatch-ordered): `harness_binding.py` binds the
#: HarnessConfigPort to the real C4 `ConfigurationApplicationService`, so the
#: public harness-api contract DTOs join `server_plugin_api` as allowed
#: published-contract vocabulary (direction server→harness-api; the reverse
#: import never exists).
ALLOWED_ROOTS = {
    "__future__", "hashlib", "json", "typing", "dataclasses", "ipaddress",
    "socket", "time", "types", "urllib", "ordessa_model_provider",
    "pacthold", "server_plugin_api", "ordessa_server", "ordessa_server_compat",
    "ordessa_harness_api",
}
ALLOWED_ORDENSSA_SERVER_LEAVES = {
    "errors", "records", "ids", "idempotency", "storage_port",
    "wire.errors", "wire.handlers", "wire.envelope", "wire.projection",
}
ALLOWED_ORDENSSA_SERVER_COMPAT_LEAVES = {"wire_validators"}


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
            root = module.split(".")[0]
            if root not in ALLOWED_ROOTS:
                violations.append(f"{path.name}: imports {module}")
            elif root == "ordessa_server_compat":
                tail = module.removeprefix("ordessa_server_compat.")
                if tail not in ALLOWED_ORDENSSA_SERVER_COMPAT_LEAVES:
                    violations.append(f"{path.name}: imports legacy {module}")
    assert violations == []


def test_ordessa_server_imports_are_the_documented_generic_leaves():
    violations = []
    for path in sorted(SRC.glob("*.py")):
        for module in _imports(path):
            if module.startswith("ordessa_server."):
                tail = module.removeprefix("ordessa_server.")
                if tail not in ALLOWED_ORDENSSA_SERVER_LEAVES:
                    violations.append(f"{path.name}: imports host business module {module}")
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

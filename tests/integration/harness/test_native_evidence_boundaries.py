"""PE2-5 boundary: native evidence has SDK contracts and one Agents read projection.

Scans the plugin's own source trees (not just the new modules) so the whole
native-evidence surface, API DTOs included, is covered by the import rule.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_ROOT = REPO_ROOT / "plugins" / "harness"


def _import_names(path: Path) -> set[str]:
    """Every absolute dotted module name the file imports."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module)
    return names


def _import_roots(path: Path) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    return roots


# Actual production owners, all witnessed before scanning.
KIT_SRC = REPO_ROOT / "packages/execution/agents/src/ordessa_execution_agents/harness"
RECORDS_SRC = REPO_ROOT / "packages/execution/units/src/ordessa_units/records"
BINDING_SRC = REPO_ROOT / "apps/server/src/ordessa_server/composition/configuration"
SDK_SRC = KIT_SRC / "definitions"


def _plugin_py_files():
    for root in (KIT_SRC, RECORDS_SRC, BINDING_SRC):
        files = sorted(root.rglob("*.py"))
        assert files, f"actual native configuration source absent: {root}"
        yield from files


def test_plugin_sources_never_import_the_permissions_implementation():
    for file in _plugin_py_files():
        roots = _import_roots(file)
        assert "ordessa_permissions" not in roots, file
        assert "permissions" not in roots, file


def test_api_dto_modules_stay_host_and_implementation_free():
    """The contract edge is stdlib plus its own package tree; the kernel's
    other internals and any host/plugin implementation stay out."""
    allowed = {"__future__", "collections", "dataclasses", "enum", "json", "math",
               "os", "pathlib", "re", "stat", "hashlib", "typing", "types"}
    # These exact shared references remain pending their real owner transfer.
    # They do not permit the old Harness API, host, or implementation imports.
    shared_references = {
        "ordessa_execution_agents.harness.definitions.activation",
        "ordessa_infrastructure.encoding.immutable_json",
    }
    files = sorted(SDK_SRC.rglob("*.py"))
    assert files and SDK_SRC.joinpath("native_evidence.py").is_file()
    for file in files:
        roots = _import_roots(file)
        assert "pacthold.harness_kit" not in roots, file
        names = _import_names(file)
        assert all(name.split(".")[0] in allowed
                   or name == "ordessa_execution_agents.harness.definitions"
                   or name.startswith("ordessa_execution_agents.harness.definitions.")
                   or name in shared_references for name in names), (file, sorted(names))


def _native_evidence_imports_allowed(names):
    allowed = {"__future__", "dataclasses", "datetime", "hashlib", "json", "re",
               "typing"}
    return all(name.split(".")[0] in allowed
               or name == "ordessa_execution_agents.harness.definitions"
               or name.startswith("ordessa_execution_agents.harness.definitions.")
               or name == "ordessa_units.records"
               or name.startswith("ordessa_units.records.")
               for name in names)


def test_execution_import_permission_is_limited_to_records(tmp_path):
    source = tmp_path / "planted.py"
    for module, permitted in (
        ("ordessa_units.records", True),
        ("ordessa_units.records.operation_journal", True),
        ("ordessa_execution_agents.public", False),
        ("ordessa_execution_agents.units.lifecycle.service", False),
        ("ordessa_units.records_alias", False),
        ("ordessa_execution_agents.harness.definitions", True),
        ("ordessa_execution_agents.harness.definitions.native_evidence", True),
        ("ordessa_execution_agents.harness.definitions_alias", False),
        ("ordessa_execution_api.harness", False),
        ("ordessa_execution_api.harness_alias", False),
        ("ordessa_execution_api.environment", False),
        ("ordessa_server.composition", False),
        ("ordessa_harness_codex", False),
        ("ordessa_server_product", False),
        ("pacthold.core", False),
    ):
        source.write_text("import " + module + "\n", encoding="utf-8")
        assert _native_evidence_imports_allowed(_import_names(source)) is permitted


def test_native_evidence_modules_import_only_within_the_harness_boundary():
    files = [
        RECORDS_SRC / "native_evidence.py",
        SDK_SRC / "native_evidence.py",
    ]
    assert all(file.is_file() for file in files), files
    for file in files:
        roots = _import_roots(file)
        assert _native_evidence_imports_allowed(_import_names(file)), file
        assert not {"ordessa_server", "ordessa_permissions", "server_plugin_api"} & roots, file


def test_native_evidence_has_one_reader_and_no_production_stand_in():
    assert not (REPO_ROOT / "products/server/src/ordessa_server_product/harness_adapters/application/native_evidence.py").exists()
    assert not (KIT_SRC / "evidence").exists()
    readers, stand_ins, suppliers = [], [], []
    project_roots = [path for layer in ("packages", "plugins", "apps", "products")
                     for path in (REPO_ROOT / layer).rglob("pyproject.toml")
                     if not {"build", "node_modules", ".venv-nightly"}.intersection(path.parts)]
    assert project_roots
    for metadata in project_roots:
        for source in (metadata.parent / "src").rglob("*.py"):
            for node in ast.parse(source.read_text(encoding="utf-8")).body:
                if isinstance(node, ast.ClassDef) and node.name == "NativeEvidenceService":
                    readers.append(source)
                if isinstance(node, ast.ClassDef) and node.name == "ControlledNativeStandIn":
                    stand_ins.append(source)
                if isinstance(node, ast.FunctionDef) and node.name == "supply_brand_evidence":
                    suppliers.append(source)
    assert readers == [RECORDS_SRC / "native_evidence.py"]
    assert stand_ins == [] and suppliers == []

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tooling.checks.dependency_boundaries import ScanError, main, scan_root


def _project(root: Path, layer: str, directory: str, name: str, package: str,
             *, dependencies: tuple[str, ...] = ()) -> Path:
    project = root / layer / directory
    source_root = project / "src"
    package_dir = source_root.joinpath(*package.split("."))
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "__init__.py").write_text("", encoding="utf-8")
    dependency_lines = ",\n    ".join(json.dumps(item) for item in dependencies)
    (project / "pyproject.toml").write_text(
        "[project]\n"
        f"name = {json.dumps(name)}\n"
        "version = '0.1.0'\n"
        f"dependencies = [{dependency_lines}]\n\n"
        "[tool.setuptools.packages.find]\n"
        "where = ['src']\n",
        encoding="utf-8",
    )
    return package_dir


def _fixture_root(tmp_path: Path) -> tuple[Path, Path, Path]:
    package = _project(tmp_path, "packages", "core", "core-dist", "public_core")
    plugin = _project(tmp_path, "plugins", "provider", "provider-dist", "concrete_provider")
    app = _project(tmp_path, "apps", "host", "host-dist", "host_app")
    _project(tmp_path, "apps", "server/deployment/default-product", "product-dist", "product_assembly")
    return package, plugin, app


def test_allowed_package_plugin_and_app_directions_are_clean(tmp_path: Path) -> None:
    package, plugin, app = _fixture_root(tmp_path)
    (plugin / "provider.py").write_text("from public_core import api\n", encoding="utf-8")
    (app / "main.py").write_text("from concrete_provider import provider\n", encoding="utf-8")

    findings, errors = scan_root(tmp_path)

    assert errors == []
    assert findings == []


def test_absolute_import_edges_report_package_and_plugin_provenance(tmp_path: Path) -> None:
    package, plugin, _app = _fixture_root(tmp_path)
    (package / "consumer.py").write_text("import host_app\n", encoding="utf-8")
    (plugin / "consumer.py").write_text("from host_app import service\n", encoding="utf-8")

    findings, errors = scan_root(tmp_path)

    assert errors == []
    assert {(item.rule, item.source_layer, item.target_layer) for item in findings} == {
        ("packages_and_plugins_must_not_import_apps", "packages", "apps"),
        ("packages_and_plugins_must_not_import_apps", "plugins", "apps"),
    }
    assert all(item.source_file and item.source_project and item.target_project and item.line > 0 for item in findings)


def test_importlib_dynamic_and_builtin_import_are_scanned(tmp_path: Path) -> None:
    package, _plugin, _app = _fixture_root(tmp_path)
    (package / "dynamic.py").write_text(
        "import importlib as il\n"
        "il.import_module('host_app')\n"
        "__import__('host_app')\n",
        encoding="utf-8",
    )

    findings, errors = scan_root(tmp_path)

    assert errors == []
    assert [item.mechanism for item in findings] == ["importlib.import_module", "__import__"]


def test_relative_dynamic_import_resolves_shared_namespace_from_metadata(tmp_path: Path) -> None:
    _project(tmp_path, "apps", "server/deployment/default-product", "product-dist", "product_assembly")
    package = _project(tmp_path, "packages", "core", "core-dist", "ordessa.public")
    _plugin = _project(tmp_path, "plugins", "provider", "provider-dist", "ordessa.provider")
    _app = _project(tmp_path, "apps", "host", "host-dist", "ordessa.apps")
    (package / "dynamic.py").write_text(
        "from importlib import import_module\n"
        "import_module('..apps', package=__package__)\n",
        encoding="utf-8",
    )

    findings, errors = scan_root(tmp_path)

    assert errors == []
    assert len(findings) == 1
    assert findings[0].mechanism == "importlib.import_module"
    assert findings[0].imported_module == "ordessa.apps"
    assert findings[0].target_project == "host-dist"


def test_metadata_dependencies_are_checked_by_distribution_identity(tmp_path: Path) -> None:
    _package = _project(tmp_path, "packages", "core", "core-dist", "public_core", dependencies=("host-dist>=0.1", "provider.dist"))
    _plugin = _project(tmp_path, "plugins", "provider", "provider-dist", "concrete_provider", dependencies=("host_dist",))
    _app = _project(tmp_path, "apps", "host", "host-dist", "host_app")
    _project(tmp_path, "apps", "server/deployment/default-product", "product-dist", "product_assembly")

    findings, errors = scan_root(tmp_path)

    assert errors == []
    assert {(item.mechanism, item.source_layer, item.target_layer) for item in findings} == {
        ("metadata-dependency", "packages", "apps"),
        ("metadata-dependency", "packages", "plugins"),
        ("metadata-dependency", "plugins", "apps"),
    }


def test_missing_scan_root_fails_closed(tmp_path: Path) -> None:
    _fixture_root(tmp_path)
    (tmp_path / "plugins").rename(tmp_path / "plugins-removed")

    with pytest.raises(ScanError, match="required scan root is missing"):
        scan_root(tmp_path)


def test_bad_ast_makes_cli_exit_nonzero_with_error_provenance(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    package, _plugin, _app = _fixture_root(tmp_path)
    (package / "broken.py").write_text("if this is not valid Python:\n", encoding="utf-8")

    exit_code = main(["--root", str(tmp_path)])
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 2
    assert report["ok"] is False
    assert len(report["errors"]) == 1
    assert "broken.py" in report["errors"][0]
    assert "SyntaxError" in report["errors"][0]


def test_broken_package_source_root_fails_closed(tmp_path: Path) -> None:
    _fixture_root(tmp_path)
    app_project = tmp_path / "apps/host/pyproject.toml"
    app_project.write_text(
        "[project]\nname='host-dist'\nversion='0.1.0'\n"
        "[tool.setuptools.packages.find]\nwhere=['missing-src']\n",
        encoding="utf-8",
    )

    with pytest.raises(ScanError, match="package source root is missing"):
        scan_root(tmp_path)


def test_cli_emits_json_and_nonzero_for_violation(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    package, _plugin, _app = _fixture_root(tmp_path)
    (package / "consumer.py").write_text("import host_app\n", encoding="utf-8")

    exit_code = main(["--root", str(tmp_path)])
    report = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert report["ok"] is False
    assert report["violations"][0]["source_file"].endswith("consumer.py")


def test_product_composition_is_a_host_boundary(tmp_path: Path) -> None:
    package, plugin, _app = _fixture_root(tmp_path)
    (package / "consumer.py").write_text("import product_assembly\n")
    (plugin / "consumer.py").write_text("from product_assembly import composition\n")
    findings, errors = scan_root(tmp_path)
    assert errors == []
    assert len(findings) == 2
    assert all(item.target_layer == "apps" and item.target_project == "product-dist"
               for item in findings)
    assert all(item.rule == "packages_and_plugins_must_not_import_apps" for item in findings)


def test_retired_products_directory_may_be_absent_or_source_free(tmp_path: Path) -> None:
    _fixture_root(tmp_path)
    assert scan_root(tmp_path) == ([], [])
    residue = tmp_path / "products/agent-tools/deployment/__pycache__"
    residue.mkdir(parents=True)
    (residue / "composition.cpython-312.pyc").write_bytes(b"historical bytecode")
    assert scan_root(tmp_path) == ([], [])


@pytest.mark.parametrize("removed", ["directory", "metadata"])
def test_deleted_product_mapping_cannot_hide_host_imports(tmp_path: Path, removed: str) -> None:
    package, _plugin, _app = _fixture_root(tmp_path)
    (package / "consumer.py").write_text("import product_assembly\n", encoding="utf-8")
    product = tmp_path / "apps/server/deployment/default-product"
    if removed == "directory":
        product.rename(tmp_path / "apps/server/deployment/default-product-removed")
    else:
        (product / "pyproject.toml").rename(product / "pyproject.removed")
    with pytest.raises(ScanError, match="required default-product metadata is missing or linked"):
        scan_root(tmp_path)


@pytest.mark.parametrize("stale_name", [
    "agent-tools/deployment/composition.py",
    "agent-tools/deployment/composition.pyi",
    "agent-tools/pyproject.toml",
])
def test_retired_products_source_or_metadata_fails_closed(tmp_path: Path, stale_name: str) -> None:
    _fixture_root(tmp_path)
    stale = tmp_path / "products" / stale_name
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_text("not necessarily valid source or TOML", encoding="utf-8")
    with pytest.raises(ScanError, match="retired products Python source or metadata remains"):
        scan_root(tmp_path)


def test_retired_products_symlink_cannot_hide_python_source(tmp_path: Path) -> None:
    _fixture_root(tmp_path)
    retired = tmp_path / "products"
    retired.mkdir()
    (retired / "old-source").symlink_to(tmp_path / "apps", target_is_directory=True)
    with pytest.raises(ScanError, match="retired products root contains a symlink"):
        scan_root(tmp_path)


def test_nested_default_product_bad_metadata_fails_closed(tmp_path: Path) -> None:
    _fixture_root(tmp_path)
    metadata = tmp_path / "apps/server/deployment/default-product/pyproject.toml"
    metadata.write_text("[project\n", encoding="utf-8")
    with pytest.raises(ScanError, match="cannot read package metadata"):
        scan_root(tmp_path)


def test_boundary_policy_missing_or_invalid_fails_closed(tmp_path: Path) -> None:
    missing = tmp_path / "missing-policy.json"
    with pytest.raises(ScanError, match="cannot read boundary policy"):
        scan_root(tmp_path, config_path=missing)

    invalid = tmp_path / "invalid-policy.json"
    invalid.write_text('{"schema_version": 7}', encoding="utf-8")
    with pytest.raises(ScanError, match="unsupported boundary policy schema"):
        scan_root(tmp_path, config_path=invalid)


@pytest.mark.parametrize(("name", "policy", "message"), [
    ("boolean-version", {
        "schema_version": True,
        "denied_edges": [{"rule": "example", "from": ["packages/**"], "to": ["apps/**"]}],
        "retired_paths": ["packages/old"],
        "retired_python_modules": [],
        "retired_distributions": [],
    }, "unsupported boundary policy schema"),
    ("empty-rules", {
        "schema_version": 1,
        "denied_edges": [],
        "retired_paths": ["packages/old"],
        "retired_python_modules": [],
        "retired_distributions": [],
    }, "invalid denied_edges"),
    ("unknown-field", {
        "schema_version": 1,
        "denied_edges": [{"rule": "example", "from": ["packages/**"], "to": ["apps/**"]}],
        "retired_paths": ["packages/old"],
        "retired_python_modules": [],
        "retired_distributions": [],
        "unexpected": True,
    }, "fields do not match schema_version 1"),
])
def test_boundary_policy_rejects_boolean_schema_empty_rules_and_unknown_fields(
    tmp_path: Path, name: str, policy: dict[str, object], message: str,
) -> None:
    config = tmp_path / f"{name}.json"
    config.write_text(json.dumps(policy), encoding="utf-8")

    with pytest.raises(ScanError, match=message):
        scan_root(tmp_path, config_path=config)


@pytest.mark.parametrize("module", ["pacthold", "ordessa_execution_api"])
def test_retired_python_module_import_is_reported_without_an_active_owner(tmp_path: Path, module: str) -> None:
    package, _plugin, _app = _fixture_root(tmp_path)
    (package / "retired.py").write_text(f"from {module} import retired_contract\n", encoding="utf-8")

    findings, errors = scan_root(tmp_path)

    assert findings == []
    assert any("retired Python module import remains" in item and module in item for item in errors)


def test_retired_import_is_detected_in_type_checking_and_literal_dynamic_forms(tmp_path: Path) -> None:
    package, _plugin, _app = _fixture_root(tmp_path)
    (package / "retired.py").write_text(
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    import pacthold.harness_kit\n"
        "import importlib\n"
        "importlib.import_module('ordessa_execution_api.harness')\n",
        encoding="utf-8",
    )

    _findings, errors = scan_root(tmp_path)

    assert any("TYPE_CHECKING" not in item and "pacthold.harness_kit" in item for item in errors)
    assert any("ordessa_execution_api.harness" in item for item in errors)


def test_retired_distribution_dependency_and_project_identity_fail_closed(tmp_path: Path) -> None:
    package, _plugin, _app = _fixture_root(tmp_path)
    metadata = tmp_path / "packages/core/pyproject.toml"
    metadata.write_text(
        "[project]\nname='core-dist'\nversion='0.1.0'\ndependencies=['ordessa-execution-api>=0.1']\n"
        "[tool.setuptools.packages.find]\nwhere=['src']\n",
        encoding="utf-8",
    )

    _findings, errors = scan_root(tmp_path)
    assert any("retired Python distribution dependency remains" in item and "ordessa-execution-api" in item
               for item in errors)

    metadata.write_text(
        "[project]\nname='ordessa-execution-api'\nversion='0.1.0'\n"
        "[tool.setuptools.packages.find]\nwhere=['src']\n",
        encoding="utf-8",
    )
    with pytest.raises(ScanError, match="retired Python distribution remains"):
        scan_root(tmp_path)


@pytest.mark.parametrize("retired_path", [
    "packages/execution/kernel",
    "packages/interfaces/execution/c1-api",
])
def test_retired_path_cannot_retain_python_source_or_metadata(tmp_path: Path, retired_path: str) -> None:
    _fixture_root(tmp_path)
    stale = tmp_path / retired_path / "pyproject.toml"
    stale.parent.mkdir(parents=True)
    stale.write_text("not required to parse retired metadata", encoding="utf-8")

    with pytest.raises(ScanError, match="retired Python source or metadata remains"):
        scan_root(tmp_path)


def test_retired_python_workspace_entry_fails_even_when_path_is_absent(tmp_path: Path) -> None:
    _fixture_root(tmp_path)
    (tmp_path / "python-workspace.json").write_text(
        json.dumps({"schema_version": 1, "projects": [{"path": "packages/interfaces/execution/c1-api"}]}),
        encoding="utf-8",
    )

    with pytest.raises(ScanError, match="retired Python workspace entry remains"):
        scan_root(tmp_path)


def test_configured_internal_edges_include_type_relative_and_from_member_imports(tmp_path: Path) -> None:
    _plugin = _project(tmp_path, "plugins", "provider", "provider-dist", "concrete_provider")
    _app = _project(tmp_path, "apps", "host", "host-dist", "host_app")
    _project(tmp_path, "apps", "server/deployment/default-product", "product-dist", "product_assembly")
    engineering = _project(tmp_path, "packages", "engineering", "engineering-dist", "ordessa_engineering")
    (engineering / "domain").mkdir()
    (engineering / "domain/__init__.py").write_text("", encoding="utf-8")
    (engineering / "methods").mkdir()
    (engineering / "methods/__init__.py").write_text("", encoding="utf-8")
    (engineering / "application").mkdir()
    (engineering / "application/__init__.py").write_text("", encoding="utf-8")
    namespace_domain = engineering.parent / "ordessa_namespace/domain"
    namespace_domain.mkdir(parents=True)
    (namespace_domain / "__init__.py").write_text("", encoding="utf-8")
    (engineering / "domain/model.py").write_text(
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from ordessa_engineering import application\n"
        "from .. import methods\n",
        encoding="utf-8",
    )
    (engineering / "methods/compile.py").write_text(
        "from ..domain import model\n"
        "from ordessa_namespace import domain\n"
        "import importlib\n"
        "importlib.import_module('ordessa_engineering.domain.model')\n",
        encoding="utf-8",
    )

    findings, errors = scan_root(tmp_path)

    assert errors == []
    assert {item.rule for item in findings} >= {
        "engineering_foundations_must_not_import_upper_owners",
        "domain_must_not_import_methods",
        "methods_must_not_import_domain",
    }
    assert any(item.mechanism == "from-member" and item.target_layer == "packages" for item in findings)
    assert any(item.mechanism == "from-member" and item.imported_module == "ordessa_namespace.domain"
               for item in findings)
    assert any(item.mechanism == "importlib.import_module" for item in findings)


def test_stub_type_checking_imports_are_scanned(tmp_path: Path) -> None:
    _plugin = _project(tmp_path, "plugins", "provider", "provider-dist", "concrete_provider")
    _app = _project(tmp_path, "apps", "host", "host-dist", "host_app")
    _project(tmp_path, "apps", "server/deployment/default-product", "product-dist", "product_assembly")
    engineering = _project(tmp_path, "packages", "engineering", "engineering-dist", "ordessa_engineering")
    (engineering / "domain").mkdir()
    (engineering / "domain/__init__.py").write_text("", encoding="utf-8")
    (engineering / "methods").mkdir()
    (engineering / "methods/__init__.py").write_text("", encoding="utf-8")
    (engineering / "domain/model.pyi").write_text(
        "from typing import TYPE_CHECKING\n"
        "if TYPE_CHECKING:\n"
        "    from ordessa_engineering import methods\n",
        encoding="utf-8",
    )

    findings, errors = scan_root(tmp_path)

    assert errors == []
    assert any(item.rule == "domain_must_not_import_methods"
               and item.source_file.endswith("domain/model.pyi") for item in findings)


def test_configured_internal_metadata_edges_use_project_metadata_paths(tmp_path: Path) -> None:
    infrastructure = _project(tmp_path, "packages", "infrastructure", "infrastructure-dist",
                               "ordessa_infrastructure", dependencies=("engineering-dist",))
    engineering = _project(tmp_path, "packages", "engineering", "engineering-dist", "ordessa_engineering")
    _plugin = _project(tmp_path, "plugins", "provider", "provider-dist", "concrete_provider")
    _app = _project(tmp_path, "apps", "host", "host-dist", "host_app")
    _project(tmp_path, "apps", "server/deployment/default-product", "product-dist", "product_assembly")
    (infrastructure / "mechanism.py").write_text("VALUE = 1\n", encoding="utf-8")
    (engineering / "domain.py").write_text("VALUE = 1\n", encoding="utf-8")

    findings, errors = scan_root(tmp_path)

    assert errors == []
    assert any(item.rule == "infrastructure_must_not_import_business"
               and item.mechanism == "metadata-dependency"
               and item.source_file == "packages/infrastructure/pyproject.toml"
               and item.target_project == "engineering-dist" for item in findings)


def test_configured_execution_decision_owners_remain_independent(tmp_path: Path) -> None:
    agents = _project(tmp_path, "packages", "execution/agents", "agents-dist", "ordessa_agents")
    decision = _project(tmp_path, "packages", "execution/decision", "decision-dist", "ordessa_execution_decision")
    _plugin = _project(tmp_path, "plugins", "provider", "provider-dist", "concrete_provider")
    _app = _project(tmp_path, "apps", "host", "host-dist", "host_app")
    _project(tmp_path, "apps", "server/deployment/default-product", "product-dist", "product_assembly")
    (agents / "imports.py").write_text("import ordessa_execution_decision\n", encoding="utf-8")
    (decision / "imports.py").write_text("import ordessa_agents\n", encoding="utf-8")

    findings, errors = scan_root(tmp_path)

    assert errors == []
    assert {item.rule for item in findings} >= {
        "decision_is_independent_of_other_execution_owners",
        "execution_owners_must_not_import_decision",
    }

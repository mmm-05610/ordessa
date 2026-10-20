"""Approved owner directions apply to runtime and annotation imports alike."""
import ast
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


SOURCE = Path(__file__).parents[2] / "src" / "ordessa_engineering"


def _selected_cold_environment():
    import ordessa_engineering
    root = Path(ordessa_engineering.__file__).resolve().parent.parent
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(root) + os.pathsep + environment.get("PYTHONPATH", "")
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return root, environment


def imports(source):
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            yield from (item.name for item in node.names)
        elif isinstance(node, ast.ImportFrom):
            yield node.module or ""


def forbidden(name, owner):
    external = ("pacthold", "ordessa_server", "ordessa_units", "ordessa_execution",
                "ordessa_interfaces", "ordessa_harness")
    if name.startswith(external):
        return True
    if owner == "domain":
        return name.startswith("ordessa_engineering.methods") or "application" in name.split(".") or "adapters" in name.split(".") or "methods" in name.split(".")
    if owner == "methods":
        return any(segment in name.split(".") for segment in ("domain", "application", "adapters"))
    return "adapters" in name.split(".")


@pytest.mark.parametrize("owner", ("domain", "methods", "application"))
def test_approved_lower_owners_have_no_forbidden_imports(owner):
    violations = [(str(path.relative_to(SOURCE)), name)
                  for path in (SOURCE / owner).rglob("*.py")
                  for name in imports(path.read_text()) if forbidden(name, owner)]
    assert violations == []


@pytest.mark.parametrize("owner,source", (
    ("application", "from typing import TYPE_CHECKING\nif TYPE_CHECKING:\n from ordessa_units.api import UnitManager"),
    ("application", "from ordessa_engineering.adapters.persistence.sqlite import unit_of_work"),
    ("domain", "from ..methods import compile_method"),
    ("methods", "from ..domain.artifacts import models"),
))
def test_boundary_checker_detects_injected_counterexamples(owner, source):
    assert any(forbidden(name, owner) for name in imports(source))


def test_public_api_and_assembly_cold_import_without_execution_or_adapters():
    code = '''
import importlib.abc, sys
class BlockForbidden(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(("pacthold", "ordessa_units", "ordessa_execution", "ordessa_server", "ordessa_interfaces", "ordessa_engineering.adapters")):
            raise AssertionError("forbidden cold import: " + fullname)
sys.meta_path.insert(0, BlockForbidden())
from ordessa_engineering.application.api import EngineeringService
from ordessa_engineering.application.assembly import EngineeringPorts, build_engineering_service
assert EngineeringService.__module__ == "ordessa_engineering.application.api.service"
capabilities=EngineeringService.operation_capabilities().capabilities
assert len(capabilities) == 25
assert {"engineering.packages.freeze", "engineering.work.bind_inputs",
        "engineering.reviews.assign_reviewer", "engineering.reviews.revoke_reviewer",
        "engineering.runs.cancel", "engineering.proposals.associate_review"} <= {item.capability_id for item in capabilities}
assert {item.capability_id: item.interface_version for item in capabilities}["engineering.proposals.create"] == "2"
assert {item.capability_id: item.interface_version for item in capabilities}["engineering.packages.freeze"] == "2"
'''
    _root, environment = _selected_cold_environment()
    result = subprocess.run([sys.executable, "-c", code], text=True, capture_output=True,
                            env=environment, timeout=30)
    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize("entry", (
    "ordessa_engineering.application.api",
    "ordessa_engineering.application.orchestration.method_bridge",
    "ordessa_engineering.application.usecases.reviews.admission",
    "ordessa_engineering.application.orchestration.unit_review",
))
def test_original_public_contracts_allow_independent_cold_entry(entry):
    root, environment = _selected_cold_environment()
    code = '''
import importlib, json, sys
importlib.import_module(sys.argv[1])
from ordessa_engineering.application import api
from ordessa_engineering.application.contracts.unit_review import UnitReviewBinding
from ordessa_engineering.application.orchestration.unit_review import UnitReviewBinding as consumer_binding
import ordessa_engineering
assert api.UnitReviewBinding is UnitReviewBinding is consumer_binding
print(json.dumps({"origin": ordessa_engineering.__file__}))
'''
    result = subprocess.run([sys.executable, "-c", code, entry], env=environment,
                            text=True, capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert Path(json.loads(result.stdout)["origin"]).resolve().is_relative_to(root)

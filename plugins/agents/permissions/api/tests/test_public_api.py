"""T01 red/green: the published surface of the API package."""
from __future__ import annotations

import importlib
import pathlib

import pytest

import ordessa_permissions_api as api

PACKAGE_ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_NAMES = ("codes", "rules", "ceilings", "intents", "brand", "request_facts",
                "decisions", "snapshots", "synthesis", "wire_family", "ports",
                "authority")


def test_every_declared_module_is_importable_and_declares_its_own_exports() -> None:
    for name in MODULE_NAMES:
        module = importlib.import_module(f"ordessa_permissions_api.{name}")
        assert getattr(module, "__all__", None), name


def test_the_package_re_exports_exactly_the_union_of_its_modules() -> None:
    published: set[str] = set()
    for name in MODULE_NAMES:
        module = importlib.import_module(f"ordessa_permissions_api.{name}")
        published |= set(module.__all__)
    assert set(api.__all__) == published


def test_every_exported_name_is_resolvable_and_has_no_private_leaks() -> None:
    for name in api.__all__:
        assert hasattr(api, name), name
        assert not name.startswith("_"), name


def test_the_export_list_is_free_of_duplicates() -> None:
    assert len(api.__all__) == len(set(api.__all__))


def test_the_package_ships_a_readme_that_states_the_supported_unknown_split() -> None:
    readme = (PACKAGE_ROOT / "README.md").read_text(encoding="utf-8")
    assert "unsupported" in readme and "unknown" in readme
    assert "last-match" in readme


def test_the_packaging_metadata_names_the_published_dist_and_import() -> None:
    pyproject = (PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'name = "ordessa-permissions-api"' in pyproject
    assert 'version = "0.1.0"' in pyproject
    assert "where = [\"src\"]" in pyproject
    assert (PACKAGE_ROOT / "src" / "ordessa_permissions_api" / "py.typed").exists()


def test_no_production_service_or_storage_type_leaks_into_the_api() -> None:
    forbidden = {"ApprovalRecords", "Database", "ServerError", "SandboxV1", "Session",
                 "AuthorizationService", "PolicyRepository"}
    assert forbidden.isdisjoint(set(api.__all__))


@pytest.mark.parametrize("name", ["synthesize", "evaluate_authorization"])
def test_the_two_public_entry_points_are_callables(name: str) -> None:
    assert callable(getattr(api, name))

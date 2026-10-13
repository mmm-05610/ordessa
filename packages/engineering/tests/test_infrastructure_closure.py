"""Source-integrity closure for the Infrastructure dependency of Engineering.

Exercise the real working registry and its transitive Infrastructure imports.
Resealed fixture manifests are used only for explicit corruption cases.
"""
from __future__ import annotations

import copy
import ast
import json
from importlib.util import resolve_name
from pathlib import Path

import pytest

from ordessa_engineering.adapters.registry import loading as rs
from ordessa_engineering.adapters.registry import source_integrity as si
from ordessa_engineering.domain.artifacts.library_material_codec import content_digest
from ordessa_engineering.domain.common.outcomes.library_failures import EngineeringError

_MANIFEST = Path(rs.__file__).parent / "resources" / "operation_registry.v1.json"

#: The real transitive Infrastructure import closure of the hashed Engineering
#: sources: the root, the three ``encoding`` modules and the five ``filesystem``
#: modules, plus the database primitive consumed by the SQLite adapters.
_EXPECTED_INFRA_KEYS = {
    "ordessa_infrastructure:__init__.py",
    "ordessa_infrastructure:database/__init__.py",
    "ordessa_infrastructure:database/options.py",
    "ordessa_infrastructure:database/sqlite.py",
    "ordessa_infrastructure:encoding/__init__.py",
    "ordessa_infrastructure:encoding/canonical_json.py",
    "ordessa_infrastructure:encoding/digests.py",
    "ordessa_infrastructure:filesystem/__init__.py",
    "ordessa_infrastructure:filesystem/directories.py",
    "ordessa_infrastructure:filesystem/errors.py",
    "ordessa_infrastructure:filesystem/files.py",
    "ordessa_infrastructure:filesystem/publication.py",
}


def _reseal(registry: dict) -> dict:
    registry["implementation_digest"] = content_digest(registry["implementation"])
    unsigned = {key: value for key, value in registry.items() if key != "registry_digest"}
    registry["registry_digest"] = content_digest(unsigned)
    return registry


def _fixture_manifest() -> dict:
    return json.loads(_MANIFEST.read_text(encoding="utf-8"))


def test_hashed_infra_set_is_the_real_closure():
    facts = si.implementation_facts()
    infra_keys = {k for k in facts["engineering"] if k.startswith("ordessa_infrastructure:")}
    assert infra_keys == _EXPECTED_INFRA_KEYS
    assert "ordessa_infrastructure:database/sqlite.py" in infra_keys


def test_working_manifest_covers_the_infrastructure_closure():
    stored = json.loads(_MANIFEST.read_text(encoding="utf-8"))["implementation"]["engineering"]
    for key in _EXPECTED_INFRA_KEYS:
        assert key in stored, f"closure key missing from working manifest: {key}"


def test_working_manifest_loads_without_neutralising_drift():
    loaded = rs.load_registry()
    assert loaded["registry_id"] == "ordessa-engineering.operations"


def test_tampered_new_infra_dependency_is_rejected_then_restored(monkeypatch):
    fixture = _fixture_manifest()

    tampered = copy.deepcopy(fixture)
    tampered["implementation"]["engineering"]["ordessa_infrastructure:filesystem/files.py"] = (
        "sha256:" + "0" * 64
    )
    _reseal(tampered)
    monkeypatch.setattr(rs, "_manifest", lambda: copy.deepcopy(tampered))
    with pytest.raises(EngineeringError, match="operation_registry_source_drift"):
        rs.load_registry()

    restored = copy.deepcopy(fixture)
    monkeypatch.setattr(rs, "_manifest", lambda: copy.deepcopy(restored))
    assert rs.load_registry()["registry_id"] == "ordessa-engineering.operations"


def test_source_pins_cover_every_engineering_python_file():
    root = Path(si.__file__).parents[2]
    actual = {p.relative_to(root).as_posix() for p in root.rglob("*.py")}
    assert len(si.ENGINEERING_FILES) == len(set(si.ENGINEERING_FILES))
    assert set(si.ENGINEERING_FILES) == actual


def test_source_pins_follow_actual_transitive_infrastructure_imports():
    import ordessa_infrastructure
    root = Path(ordessa_infrastructure.__file__).parent
    modules = {"ordessa_infrastructure" + ("." + ".".join(
        p.relative_to(root).with_suffix("").parts[:-1] if p.name == "__init__.py"
        else p.relative_to(root).with_suffix("").parts) if p != root / "__init__.py" else ""): p
        for p in root.rglob("*.py")}

    def imports(path, package):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                yield from (a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                base = resolve_name("." * node.level + (node.module or ""), package) if node.level else (node.module or "")
                yield base
                yield from (base + "." + a.name for a in node.names)

    engineering = Path(si.__file__).parents[2]
    pending = [name for p in engineering.rglob("*.py")
               for name in imports(p, "ordessa_engineering." + ".".join(p.relative_to(engineering).parts[:-1]))
               if name in modules]
    visited = set()
    while pending:
        name = pending.pop()
        if name in visited:
            continue
        visited.add(name)
        path = modules[name]
        package = name if path.name == "__init__.py" else name.rsplit(".", 1)[0]
        pending.extend(n for n in imports(path, package) if n in modules)
        pending.extend(".".join(name.split(".")[:i]) for i in range(1, len(name.split("."))))
    actual = {"ordessa_infrastructure:" + modules[n].relative_to(root).as_posix() for n in visited}
    assert actual == _EXPECTED_INFRA_KEYS


@pytest.mark.parametrize("relative", ("database/__init__.py", "database/options.py", "database/sqlite.py"))
def test_database_source_drift_is_rejected_by_real_loader(monkeypatch, relative):
    import ordessa_infrastructure
    target = Path(ordessa_infrastructure.__file__).parent / relative
    original = si._sha256
    monkeypatch.setattr(si, "_sha256", lambda path: "sha256:" + "0" * 64 if path == target else original(path))
    with pytest.raises(EngineeringError, match="operation_registry_source_drift"):
        rs.load_registry()


@pytest.mark.parametrize("relative", ("database/__init__.py", "database/options.py", "database/sqlite.py"))
def test_resealed_manifest_cannot_omit_database_dependency(monkeypatch, relative):
    fixture = _fixture_manifest()
    del fixture["implementation"]["engineering"]["ordessa_infrastructure:" + relative]
    _reseal(fixture)
    monkeypatch.setattr(rs, "_manifest", lambda: fixture)
    with pytest.raises(EngineeringError, match="operation_registry_source_drift"):
        rs.load_registry()

"""Structural guards for the adapter slice.

1. ONE capability table: research-and-reuse.md §能力注册表 retires the
   legacy `harness_delivery/capabilities.py` (empty) and forbids a second
   static brand table; `capabilities.py` is the only place in the Skills
   domain that maps brand ids to capability cells. (`__init__.py`'s id →
   module dispatch map lists filenames, not capability cells, and is
   therefore not the "second table" the rule forbids.) It also forbids a
   second INTENT vocabulary: the interim Skills-side intent dataclasses
   are deleted with the harness-api checkpoint, and no module here may
   re-define one (pin 4 below).
2. The adapters never import the harness or the host (AGENTS.md rule 3) —
   pinned here again for this area, in addition to the package-wide
   `test_dependency_direction.py`. The published standalone contract
   package `ordessa_harness_api` is the allowed Harness-facing import.
3. Registration rides the published `harness.configuration-adapters`
   contribution point through `ContributionBatch` — it is proven in
   `test_harness_api_registration.py` against the real harness handler;
   this file keeps the negative pins: no fabricated registration helper,
   no side-effect primitives, no author-declared owner in a payload.
4. One vocabulary: nothing in the area may define a dataclass named like
   an intent type (the deleted interim names) — the published DTOs are
   imported, never mirrored.
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
PKG = ROOT / "plugins" / "assets" / "skills" / "src" / "ordessa_skills"
AREA_DIRS = (PKG / "harness_adapters", PKG / "native_discovery")
BRAND_IDS = {"pi", "codex", "claude-code"}
REGISTRY_FILE = "capabilities.py"

#: The published intent vocabulary must not be re-declared domain-side.
FORBIDDEN_INTENT_MIRRORS = {"IntentSet", "MountRevision", "MountContent",
                            "RemoveOwnedContent", "SetField", "ResetField",
                            "BindSecret", "InvokeAction", "ContentRef",
                            "IntentSource", "TargetHandle", "LoadControl",
                            "ReloadSession", "RestartAndResume"}


def _area_files():
    for area in AREA_DIRS:
        for path in sorted(area.rglob("*.py")):
            yield path


def test_the_capability_registry_is_the_only_brand_table():
    offenders = []
    for path in _area_files():
        if path.name == REGISTRY_FILE:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            keys = {k.value for k in node.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)}
            if len(keys & BRAND_IDS) >= 2:
                offenders.append(f"{path.name}:{node.lineno}")
    assert offenders == [], offenders


def test_the_retired_legacy_capabilities_module_is_not_resurrected():
    # Prose may name the retired module (this file does); no IMPORT may.
    for path in _area_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module or ""]
            else:
                continue
            for name in names:
                assert "harness_delivery" not in name, (path, name)


def test_no_adapter_module_imports_harness_or_host_internals():
    forbidden = {"ordessa_harness", "ordessa_server", "ordessa_server_compat",
                 "ordessa_workspace", "ordessa_assets"}
    for path in _area_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            for name in names:
                assert name.split(".")[0] not in forbidden, (path, name)


def test_the_area_imports_the_published_contract_not_a_private_copy():
    """`ordessa_harness_api` may be imported; nothing in the area may
    re-declare the published intent classes (the deleted interim
    vocabulary must not come back as a shadow)."""
    for path in _area_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        declared = {node.name for node in ast.walk(tree)
                    if isinstance(node, ast.ClassDef)}
        mirrors = declared & FORBIDDEN_INTENT_MIRRORS
        assert not mirrors, f"{path.name} re-declares published types: {mirrors}"


def test_no_registration_fabrication_and_no_side_effect_primitives():
    for path in _area_files():
        source = path.read_text(encoding="utf-8")
        assert "register_adapter(" not in source, path  # the point is the seam
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    assert a.name.split(".")[0] not in {
                        "subprocess", "socket", "http", "urllib", "pty",
                        "multiprocessing", "asyncio"}, (path, a.name)
            elif isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in {
                    "subprocess", "socket", "http", "urllib", "pty",
                    "multiprocessing", "asyncio"}, (path, node.module)


def test_contributions_never_declare_an_author_owner():
    """The handler refuses author-declared owners; our payload objects must
    structurally never carry one (attribute scan, not prose)."""
    from ordessa_skills.harness_adapters.contribution import (
        configuration_adapters,
    )
    for adapter in configuration_adapters():
        assert not hasattr(adapter, "owner")
        assert not hasattr(adapter.descriptor, "owner")


def test_every_supported_cell_cites_an_existing_repo_location():
    # Beyond the capabilities constructor: at least one `path:line` in a
    # supported citation must resolve to a real repo file — a fabricated
    # evidence pointer fails here.
    pattern = re.compile(r"([\w./+-]+):(\d+)")
    from ordessa_skills.harness_adapters.capabilities import BRAND_STATEMENTS
    checked = 0
    for statement in BRAND_STATEMENTS.values():
        for fact in statement.facts.values():
            if fact.value != "supported":
                continue
            matches = pattern.findall(fact.evidence)
            assert matches, f"{statement.harness_id}/{fact.axis} cites nothing"
            assert any((ROOT / rel).is_file() for rel, _ in matches), fact.evidence
            checked += 1
    assert checked >= 6, "registry shrank below the controlled-brand floor"


def test_unregistered_brands_get_no_offered_surface_from_the_registry():
    from ordessa_skills.harness_adapters.capabilities import statement_for
    for brand in ("hermes", "opencode", "qwen-code", "kilo", "dsh"):
        statement = statement_for(brand)
        assert statement.synthesized is True
        assert statement.offered_axes() == ()

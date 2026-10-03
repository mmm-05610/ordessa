"""G01 legacy fidelity pins for the migrated Skills slice (T03 slice A).

Three locks (verification.md G01/G16):

1. Nothing in the new package or its tests imports the legacy
   `ordessa_assets` package — the migration is a copy-forward, not a shim.
2. The migrated parser/bounds/digest-relevant constants equal the exact
   values recorded in `specs/011-q1-skills/research/legacy-inventory.md`
   §A.3 — spelled out here as literals, not re-derived from the code under
   test.
3. One stored skill tree's file bytes survive install -> read untouched
   (bytes, digest spelling, layout identifier, no exec bit), and the new
   six-level evidence ladder cannot report `loaded` or `used` from a digest
   match alone (the G16 negative at this layer).
"""
from __future__ import annotations

import ast
import hashlib
import re
from pathlib import Path

import pytest

from pacthold_runtime_compat.resource_contracts.runtime_artifacts import (
    runtime_artifact_tree_digest,
)

from ordessa_skills.api import evidence
from ordessa_skills.api.errors import (
    AssetDomainError,
    BindingError,
    CatalogError,
    ImportError_,
    PreviewError,
    ProjectionError,
    SkillAssetError,
)
from ordessa_skills.api.evidence import (
    LADDER,
    LOADED,
    PROJECTED,
    SELECTED,
    STORED,
    UNCONFIRMED,
    UNKNOWN,
    USED,
    attest,
    highest,
)
from ordessa_skills.api.identity import (
    ASSET_ID,
    ASSET_KINDS,
    MAX_ASSET_BYTES,
    MAX_ASSET_ENTRIES,
    MAX_COMPATIBILITY_CHARS,
    MAX_DESCRIPTION_CHARS,
    MAX_FRONTMATTER_BYTES,
    SKILL_NAME,
    SkillRevisionFacts,
)
from ordessa_skills.api.ports import (
    ProfileRegistrationPort,
    SkillBindingFacet,
)
from ordessa_skills.formats.agent_skills import frontmatter as fm
from ordessa_skills.formats.agent_skills.validator import (
    MAX_PREVIEW_FILE_BYTES,
    assert_regular_within,
    validate_skill_directory,
)
from ordessa_skills.library.store import SkillRevisionStore

PKG_ROOT = Path(__file__).resolve().parents[1]

# ---------------------------------------------------------------------------
# 1. no legacy-package imports
# ---------------------------------------------------------------------------


def _imported_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                names.add(node.module)
    return names


def test_nothing_imports_the_legacy_ordessa_assets_package():
    sources = list((PKG_ROOT / "src").rglob("*.py")) + \
        list(Path(__file__).resolve().parent.rglob("*.py"))
    assert sources, "the fidelity sweep found no files to check"
    for path in sources:
        offenders = {name for name in _imported_names(path)
                     if name.split(".")[0] == "ordessa_assets"}
        assert not offenders, f"{path}: imports {offenders}"


# ---------------------------------------------------------------------------
# 2. §A.3 constant fidelity — literal values from legacy-inventory.md
# ---------------------------------------------------------------------------


def test_identity_constants_are_the_legacy_literals():
    assert ASSET_KINDS == ("skill", "mcp", "command", "plugin")
    assert ASSET_ID.pattern == r"[a-z0-9][a-z0-9._-]{0,63}\Z"
    assert SKILL_NAME.pattern == r"[a-z0-9]+(?:-[a-z0-9]+)*\Z"
    assert MAX_ASSET_ENTRIES == 512
    assert MAX_ASSET_BYTES == 32 * 1024 * 1024 == 33554432
    assert MAX_FRONTMATTER_BYTES == 64 * 1024 == 65536
    assert MAX_DESCRIPTION_CHARS == 1024
    assert MAX_COMPATIBILITY_CHARS == 500
    assert MAX_PREVIEW_FILE_BYTES == 256 * 1024 == 262144


def test_frontmatter_fence_regex_is_the_legacy_literal():
    assert fm._FRONTMATTER.pattern == r"\A---\r?\n(.*?)\r?\n---(\r?\n|\Z)"
    assert fm._FRONTMATTER.flags & re.S


def test_public_dict_uses_the_exact_camel_case_keys_in_order():
    facts = SkillRevisionFacts(asset_id="a", revision=1, tree_digest="sha256:x",
                               name="n", description="d")
    assert list(facts.public_dict()) == [
        "assetId", "revision", "treeDigest", "name", "description", "metadata",
        "retainedFields", "fileCount", "totalBytes", "scripts", "source"]


def test_error_class_family_and_code_strings_are_preserved():
    assert issubclass(SkillAssetError, AssetDomainError)
    for cls in (CatalogError, BindingError, ImportError_, ProjectionError,
                PreviewError):
        assert issubclass(cls, AssetDomainError)
    # The codes the migrated layers still raise (inventory §A.3/§B.2 spellings).
    refused = []
    cases = (
        "no fences",
        "---\nname: x\nname: y\ndescription: d\n---\n",
        "---\nname: BAD\ndescription: d\n---\n",
        "---\nname: ok\n---\n",
        "---\nname: ok\ndescription: " + "x" * 1025 + "\n---\n",
    )
    for text in cases:
        try:
            fm.parse_frontmatter(text)
        except SkillAssetError as exc:
            refused.append(exc.code)
    try:
        fm.parse_frontmatter("---\nname: ok\ndescription: d\n---\n",
                             directory_name="other")
    except SkillAssetError as exc:
        refused.append(exc.code)
    assert refused == [
        "SKILL_FRONTMATTER_MISSING", "SKILL_FRONTMATTER_INVALID",
        "SKILL_NAME_INVALID", "SKILL_DESCRIPTION_MISSING",
        "SKILL_DESCRIPTION_INVALID", "SKILL_NAME_MISMATCH"]


def test_ports_surface_matches_the_legacy_methods():
    assert {m for m in ("bindings_view", "effect_view")
            if hasattr(SkillBindingFacet, m)} == {"bindings_view", "effect_view"}
    assert hasattr(ProfileRegistrationPort, "publish_skill_binding_facet")
    # The interim `HarnessCapability`/`HarnessDeliveryPort` Protocols were
    # deleted with the harness-api checkpoint (two capability vocabularies
    # is what the design forbids); the fidelity they pinned — a Harness
    # surface that can be asked what it supports, asked to place content,
    # and observed for load evidence — now lives on the PUBLISHED types,
    # checked here so the legacy semantics did not silently vanish:
    import inspect
    from ordessa_harness_api import (
        ConfigurationAdapter, ConfigurationCapabilities, ConfigurationService,
    )
    adapter_methods = {name for name, _
                       in inspect.getmembers(ConfigurationAdapter,
                                             predicate=callable)
                       if not name.startswith("_")}
    assert {"assess", "compile", "verify"} <= adapter_methods
    assert {"inspect", "plan", "apply", "query", "reconcile"} <= {
        name for name, _ in inspect.getmembers(ConfigurationService,
                                               predicate=callable)
        if not name.startswith("_")}
    assert hasattr(ConfigurationCapabilities, "capabilities") or \
        {"capabilities", "target"} <= {f.name for f in
                                       __import__("dataclasses").fields(
                                           ConfigurationCapabilities)}


# ---------------------------------------------------------------------------
# 3. stored bytes survive install -> read untouched (G01 positive)
# ---------------------------------------------------------------------------


def test_stored_skill_tree_bytes_survive_install_and_read(tmp_path):
    source = tmp_path / "skill-src"
    (source / "scripts").mkdir(parents=True)
    (source / "references").mkdir()
    payloads = {
        "SKILL.md": "---\nname: demo-skill\ndescription: A demo.\n---\nünïcode body\n".encode(),
        "scripts/run.sh": b"#!/bin/sh\nexit 42\n",
        "references/deep.md": bytes(range(256)),
    }
    for relative, data in payloads.items():
        (source / relative).write_bytes(data)
    (source / "scripts" / "run.sh").chmod(0o755)

    store = SkillRevisionStore(tmp_path / "assets")
    facts = store.install(source, asset_id="demo-skill", revision=1)
    stored = store.revision_dir("demo-skill", 1)
    # preserved disk identifier: <root>/skill/<assetId>/<revision>
    assert stored == tmp_path / "assets" / "skill" / "demo-skill" / "1"
    for relative, data in payloads.items():
        assert assert_regular_within(stored, relative).read_bytes() == data
    # the tree digest keeps the legacy v1 algorithm and `sha256:` spelling
    digest = facts["tree_digest"]
    assert digest == store.revision_digest(asset_id="demo-skill", revision=1)
    assert re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
    assert digest == runtime_artifact_tree_digest(stored)
    # content-addressed read-back of the script byte-for-byte
    assert hashlib.sha256(
        (stored / "scripts" / "run.sh").read_bytes()).hexdigest() == \
        hashlib.sha256(payloads["scripts/run.sh"]).hexdigest()
    # validation over the stored tree yields the same manifest it guarded
    validated = validate_skill_directory(stored, directory_name="demo-skill")
    assert [e.relative for e in validated.entries] == sorted(payloads)
    assert facts["files"] == 3 and facts["scripts"] == ("scripts/run.sh",)


def test_the_escape_guard_still_type_checks_its_target(tmp_path):
    # Legacy fidelity (752f148b1b validator.py:84 `_ = os.fspath(target)`):
    # the guard resolves the target and requires it to be PathLike; a root
    # whose `/` yields a non-PathLike object must raise TypeError there,
    # not hand the odd object back to the caller.
    class _NonPathLikeTarget:
        def is_symlink(self) -> bool:
            return False

        def is_file(self) -> bool:
            return True

    class _FakeRoot:
        def __truediv__(self, other):
            return _NonPathLikeTarget()

    with pytest.raises(TypeError):
        assert_regular_within(_FakeRoot(), "SKILL.md")

    # A real revision path still resolves through the same guard.
    good = tmp_path / "rev"
    good.mkdir()
    (good / "SKILL.md").write_text("x", encoding="utf-8")
    assert assert_regular_within(good, "SKILL.md") == good / "SKILL.md"


# ---------------------------------------------------------------------------
# G16 negative: a digest match alone never reads loaded/used
# ---------------------------------------------------------------------------


def test_evidence_ladder_keeps_six_distinct_levels():
    levels = (STORED, SELECTED, PROJECTED, LOADED, USED, UNKNOWN)
    assert len(set(levels)) == 6, "the legacy USED=UNKNOWN alias is retired"
    assert USED != UNKNOWN
    assert LADDER == (USED, LOADED, PROJECTED, SELECTED, STORED)
    assert evidence.LEVELS == LADDER + (UNKNOWN,)
    assert UNCONFIRMED == "unconfirmed"


def test_digest_match_alone_never_attests_loaded_or_used(tmp_path):
    # A projection whose digest verifies is `projection_digest` evidence —
    # the strongest level it can attest is PROJECTED (contracts.md: 配置投影
    # 的 digest 匹配只能证明 projected).
    digest_only = {"content_digest", "assignment_decision", "projection_digest"}
    assert attest(PROJECTED, proofs=digest_only) == PROJECTED
    assert attest(LOADED, proofs=digest_only) == UNKNOWN
    assert attest(USED, proofs=digest_only) == UNKNOWN
    assert highest(attest(LOADED, proofs=digest_only),
                   attest(USED, proofs=digest_only),
                   PROJECTED) == PROJECTED
    # Only an independent observation / explicit invocation event promotes.
    assert attest(LOADED, proofs=digest_only | {"load_observation"}) == LOADED
    assert highest(LOADED, PROJECTED,
                   attest(USED, proofs=digest_only)) == LOADED
    assert attest(USED, proofs={"invocation_event"}) == USED
    assert attest(USED, proofs=digest_only | {"load_observation"}) == UNKNOWN

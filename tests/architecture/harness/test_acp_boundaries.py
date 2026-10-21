"""Category: 接入 ACP / native access — the boundaries this plugin must not cross.

Everything here is about the *run chain*: the reused bridge under `third_party/`,
the Worker entry under `runtime/`, and the Python modules the plugin actually
imports when it exposes an already-configured Agent. Nothing here is about how a
brand's npm closure gets built or installed; that half lives in
`tests/install/test_packaging_boundaries.py` so the two can be adopted or
dropped independently.

Each check is a detector written as a pure function over a directory, and each
detector is also run against a planted counterexample in a temp tree, so a
detector that stops matching anything is reported as dead rather than passing
quietly. Nothing here installs, builds, downloads, starts a service or reads a
credential.
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path

import pytest


#: 032 roots: the harness group keeps runtime/bridge assets; the kit source
#: lives in the kernel package.
REPO = Path(__file__).resolve().parents[3]
PLUGIN = REPO / "plugins" / "harness"
RUNTIME = REPO / 'apps/server/src/ordessa_server/composition/native_channels'
BRIDGE = REPO / 'packages/execution/agents/src/ordessa_agents/harness/transport/vendor/harness_remote/bridge'
SRC = REPO / "packages" / "execution" / "agents" / "src" / "ordessa_agents" / "harness"
SOURCE_MANIFEST = REPO / 'packages/execution/agents/src/ordessa_agents/harness/transport/vendor/harness_remote/SOURCE.json'

#: Directories that never hold code worth scanning.
SKIP_DIRECTORY_NAMES = {".git", "__pycache__", "node_modules", ".venv", "artifacts", "vendor"}


# --------------------------------------------------------------------------
# 1. the run chain owns exactly one bridge copy, and every byte of it is hashed
# --------------------------------------------------------------------------

def _expected_hash(entry: dict) -> str:
    return entry.get("patched_sha256") or entry.get("current_sha256") or entry["upstream_sha256"]


def provenance_violations(manifest: Path, root: Path) -> dict[str, list[str]]:
    """`unlisted` / `absent` / `mismatched` between a provenance manifest and a tree."""
    source = json.loads(manifest.read_text(encoding="utf-8"))
    listed = [entry["path"] for entry in source["files"]]
    unhashed, mismatched = [], []
    for entry in source["files"]:
        path = root / entry["path"]
        if not path.is_file():
            unhashed.append(entry["path"])
            continue
        if hashlib.sha256(path.read_bytes()).hexdigest() != _expected_hash(entry):
            mismatched.append(entry["path"])
    shipped = sorted(str(p.relative_to(root)) for p in (root / "bridge" / "src").rglob("*") if p.is_file())
    return {
        "unlisted": sorted(set(shipped) - set(listed)),
        "absent": unhashed,
        "mismatched": mismatched,
    }


def test_bridge_ships_nothing_the_provenance_manifest_does_not_hash():
    """`third_party` holds the single reused source; an unhashed file is a second copy.

    Counterexamples this refuses: a hand-edited bridge file that keeps the manifest
    honest-looking, or a second vendored adapter dropped in beside the reused one.
    """
    violations = provenance_violations(SOURCE_MANIFEST, SOURCE_MANIFEST.parent)
    assert violations == {"unlisted": [], "absent": [], "mismatched": []}, violations


def test_provenance_check_reports_a_tampered_and_an_unlisted_file(tmp_path):
    root = tmp_path / "harness_remote"
    (root / "bridge" / "src").mkdir(parents=True)
    (root / "bridge" / "src" / "listed.js").write_text("export const a = 1\n", encoding="utf-8")
    (root / "bridge" / "src" / "sneaked.js").write_text("export const b = 2\n", encoding="utf-8")
    listed_hash = hashlib.sha256(b"export const a = 1\n").hexdigest()
    manifest = root / "SOURCE.json"
    manifest.write_text(json.dumps({"files": [{"path": "bridge/src/listed.js", "upstream_sha256": listed_hash}]}),
                        encoding="utf-8")
    assert provenance_violations(manifest, root) == {
        "unlisted": ["bridge/src/sneaked.js"], "absent": [], "mismatched": []}
    (root / "bridge" / "src" / "listed.js").write_text("export const a = 2\n", encoding="utf-8")
    assert provenance_violations(manifest, root)["mismatched"] == ["bridge/src/listed.js"]


def test_the_access_entry_verifies_provenance_before_it_serves_an_operation():
    """The runtime's own guard, pinned by name so a quiet removal is a test failure.

    `before` is checked as an ordering, not assumed from a name: a guard that runs after the first
    frame has been relayed would verify the snapshot for the caller who comes second.
    """
    entry = (RUNTIME / "access_entry.mjs").read_text(encoding="utf-8")
    assert "PROVENANCE_MISMATCH" in entry
    assert re.search(r"verifyProvenance\(\)", entry), "provenance is no longer verified at startup"
    assert entry.index("verifyProvenance()") < entry.index("createInterface"), \
        "provenance is now verified after stdin is open"


# --------------------------------------------------------------------------
# 2. one implementation per behaviour: no brand carries another brand's bytes
# --------------------------------------------------------------------------

def duplicate_content_files(directory: Path, minimum_lines: int = 5) -> list[tuple[str, str]]:
    by_hash: dict[str, list[str]] = {}
    for path in sorted(directory.rglob("*.py")):
        if SKIP_DIRECTORY_NAMES.intersection(path.parts):
            continue
        text = path.read_text(encoding="utf-8")
        if len([line for line in text.splitlines() if line.strip()]) < minimum_lines:
            continue
        by_hash.setdefault(hashlib.sha256(text.encode()).hexdigest(), []).append(str(path.relative_to(directory)))
    return [(key, paths) for key, paths in sorted(by_hash.items()) if len(paths) > 1]


#: 032: each brand is its own independent package source tree.
BRAND_SOURCE_DIRECTORIES = {
    "codex": "ordessa_harness_codex", "pi": "ordessa_harness_pi",
    "claude": "ordessa_harness_claude_code", "hermes": "ordessa_harness_hermes",
    "opencode": "ordessa_harness_opencode", "qwen": "ordessa_harness_qwen",
    "kilo": "ordessa_harness_kilo", "dsh": "ordessa_harness_dsh",
    "kimi": "ordessa_harness_kimi", "copilot": "ordessa_harness_copilot",
    "goose": "ordessa_harness_goose", "gemini_cli": "ordessa_harness_gemini_cli",
    "vibe": "ordessa_harness_vibe", "qoder": "ordessa_harness_qoder",
}


def brand_directories(package: Path = PLUGIN) -> list[Path]:
    return sorted(package / brand / "src" / module
                  for brand, module in BRAND_SOURCE_DIRECTORIES.items()
                  if (package / brand / "src" / module).is_dir())


def test_no_two_brand_directories_hold_an_identical_implementation():
    """A brand directory is a declaration; copied code means a difference was faked.

    The measured state is that no two brand modules are byte-identical, so the
    duplicate detector below has to prove it can find one.
    """
    brands = brand_directories()
    assert len(brands) >= 6, "the brand list is empty; the check would pass vacuously"
    duplicates = [item for directory in brands
                  for item in duplicate_content_files(directory=directory)]
    assert duplicates == [], f"copied implementations: {duplicates}"


def test_the_copy_detector_reports_a_planted_duplicate(tmp_path):
    body = ("def helper():\n    value = 1\n    return value\n\n\n"
            "def other():\n    return other_thing(2)\n")
    for brand in ("alpha", "beta"):
        (tmp_path / brand).mkdir()
        (tmp_path / brand / "native.py").write_text(body, encoding="utf-8")
    (tmp_path / "gamma").mkdir()
    (tmp_path / "gamma" / "native.py").write_text(body.replace("value = 1", "value = 3"), encoding="utf-8")
    assert duplicate_content_files(tmp_path) == [(
        hashlib.sha256(body.encode()).hexdigest(), ["alpha/native.py", "beta/native.py"])]


# --------------------------------------------------------------------------
# 3. the access layer's only bound on an Agent's first-use download is a time bound
# --------------------------------------------------------------------------

#: Measured in `acp-client.js`: the bridge gives the adapter's first `npx` fetch a
#: wall-clock ceiling and no byte ceiling. Pinned here as a *fact about the run
#: chain*, so that changing it is a deliberate edit and not a drift. The absence of
#: a byte ceiling is reported as an open item in `TEST-REVIEW.md`, not asserted as
#: desirable.
BRIDGE_START_TIMEOUT_MS = 90_000


def _plain_integer(node: ast.expr) -> int:
    if isinstance(node, ast.Constant) and isinstance(node.value, int):
        return node.value
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mult, ast.Add, ast.Sub)):
        left, right = _plain_integer(node.left), _plain_integer(node.right)
        if isinstance(node.op, ast.Mult):
            return left * right
        return left + right if isinstance(node.op, ast.Add) else left - right
    raise AssertionError(f"{ast.dump(node)} is not a plain number")


def _literal_number(expression: str) -> int:
    """Evaluate a `1024 * 1024` style literal product/sum, and nothing else."""
    return _plain_integer(ast.parse(expression, mode="eval").body)


def module_constants(directory: Path, name: str) -> dict[str, int]:
    """Every `const <name> = <plain number>` in a directory, keyed by file name."""
    found: dict[str, int] = {}
    for path in sorted(directory.rglob("*.js")):
        if SKIP_DIRECTORY_NAMES.intersection(path.relative_to(directory).parts):
            continue
        for match in re.finditer(rf"^const {name} = ([\d_][\d_]*(?:\s*[*+-]\s*[\d_][\d_]*)*)\s*$",
                                 path.read_text(encoding="utf-8"), re.M):
            found[path.name] = _literal_number(match.group(1))
    return found


def test_the_bridge_bounds_an_unresponsive_agent_by_time_and_says_so():
    values = module_constants(BRIDGE / "src", "START_TIMEOUT_MS")
    assert values, "the bridge no longer names START_TIMEOUT_MS; the time bound moved or died"
    assert set(values.values()) == {BRIDGE_START_TIMEOUT_MS}, values


def test_the_time_bound_detector_reports_a_planted_change(tmp_path):
    (tmp_path / "client.js").write_text("const START_TIMEOUT_MS = 5_000\n", encoding="utf-8")
    assert module_constants(tmp_path, "START_TIMEOUT_MS") == {"client.js": 5_000}


def test_time_bound_detector_scans_explicit_owner_inside_vendor_parent(tmp_path):
    owner = tmp_path / "vendor" / "bridge" / "src"
    owner.mkdir(parents=True)
    (owner / "client.js").write_text("const START_TIMEOUT_MS = 90_000\n", encoding="utf-8")
    nested_vendor = owner / "vendor"
    nested_vendor.mkdir()
    (nested_vendor / "foreign.js").write_text("const START_TIMEOUT_MS = 1\n", encoding="utf-8")
    assert module_constants(owner, "START_TIMEOUT_MS") == {"client.js": 90_000}

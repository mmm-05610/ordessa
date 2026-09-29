"""The brand-boundary gate, kept on the core side of the line.

C-08 §6 case 6 and the contracts README §6 both require a counterexample
that a host mentioning a Harness brand is judged a violation. In 013 that
Harness availability types moved to P-A's `contracts` package, so the gate
belongs with whoever still owns the rule rather than with the plugin line:
this file lives in the Server's own tree and scans the HOST trees, which
are read-only to this package — exactly the right shape for a test that
must fail when somebody else writes a forbidden name.

Two properties make the gate trustworthy rather than decorative:

* it scans TEXT, because that is where the violation lives — a brand name
  in a comment or a string is knowledge the host has, run or not;
* its allowlist is a REGISTERED DEBT, each entry naming the task that
  removes it, and a test asserts every entry still names a real file. A
  new brand name anywhere else still fails.
"""
from __future__ import annotations

from pathlib import Path
import re
from typing import Iterable

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]

#: The brand names the boundary names. They appear HERE on purpose: this is
#: the detector, and a detector that cannot name what it looks for is not a
#: detector. The scan skips this file and every other test file.
BRAND_NAMES = ("codex", "claude", "opencode", "hermes", "qoder", "qwen", "kilo")

#: The short fragments the pre-existing stage4 audit already matches. Kept
#: because that gate runs over `apps/server/src` and this one runs over the
#: host trees; between them they cover both sides of the product.
BRAND_FRAGMENTS = ("dsh", "pi-cli")

#: Host source that still carries a brand name today, with the task that owns
#: the removal. Keyed by repo-relative path.
REGISTERED_HOST_DEBT: "dict[str, str]" = {
    "apps/desktop/electron/main.ts": "P-A PA-11 — smoke driver splits into apps/desktop/scripts",
    "apps/desktop/scripts/test-agent-shell.mjs": "P-A PA-11 — headless smoke, not shipped",
    "apps/desktop/scripts/test-native-two-turn.mjs": "P-A PA-11 — headless smoke, not shipped",
    "apps/desktop/scripts/test-native-paired-no-send.mjs": "P-A PA-11 — headless smoke, not shipped",
}

#: The host trees. `scripts/**` and test files are excluded because they are
#: development drivers rather than shipped host code; the debt list above
#: records the ones that still carry a name.
HOST_TREES = ("apps/desktop", "packages/workbench", "packages/desktop-platform")
HOST_SUFFIXES = (".ts", ".tsx", ".mjs", ".js", ".cjs")
#: Build output is not source: it is regenerated from the source this gate
#: already scans, and scanning it would report a violation twice.
EXCLUDED_PARTS = ("/tests/", "/node_modules/", "/scripts/", "/dist/", "/build/", "/out/")


def host_source_files() -> "list[tuple[str, Path]]":
    """(repo-relative name, path) for every host source file in scope."""
    files: "list[tuple[str, Path]]" = []
    for tree in HOST_TREES:
        base = REPO_ROOT / tree
        if not base.is_dir():
            continue
        for candidate in base.rglob("*"):
            if not candidate.is_file() or candidate.suffix not in HOST_SUFFIXES:
                continue
            rendered = candidate.relative_to(REPO_ROOT).as_posix()
            if any(part in f"/{rendered}" for part in EXCLUDED_PARTS):
                continue
            files.append((rendered, candidate))
    return files


def scan(entries: "Iterable[tuple[str, Path]]") -> "dict[str, list[str]]":
    offences: "dict[str, list[str]]" = {}
    for rendered, candidate in entries:
        if rendered in REGISTERED_HOST_DEBT:
            continue
        text = candidate.read_text(encoding="utf-8", errors="replace").lower()
        hits = sorted(
            name for name in (*BRAND_NAMES, *BRAND_FRAGMENTS)
            if re.search(rf"\b{re.escape(name)}\b", text)
        )
        if hits:
            offences[rendered] = hits
    return offences


def test_no_host_source_names_a_harness_brand_outside_the_registered_debt():
    offences = scan(host_source_files())
    assert offences == {}, (
        "host source names a Harness brand; the host consumes observed facts, "
        f"it does not know brands: {offences}"
    )


def test_the_gate_actually_detects_a_planted_brand(tmp_path):
    """A detector that cannot fail is not a detector.

    A synthetic file carrying a brand name is put through the SAME scan
    function the real gate uses. If the planted name is not caught, the
    green this file reports every day is one it did not earn.
    """
    planted = tmp_path / "panel.ts"
    planted.write_text("export const label = 'Open with Codex'\n", encoding="utf-8")
    assert scan([("apps/desktop/renderer/panel.ts", planted)]) == {
        "apps/desktop/renderer/panel.ts": ["codex"],
    }


def test_the_gate_detects_a_planted_brand_in_a_comment_too(tmp_path):
    """A brand in a comment is still knowledge the host has, so the scan is
    on TEXT rather than on string literals."""
    planted = tmp_path / "note.ts"
    planted.write_text("// TODO: wire up the hermes adapter\n", encoding="utf-8")
    assert scan([("apps/desktop/renderer/note.ts", planted)]) == {
        "apps/desktop/renderer/note.ts": ["hermes"],
    }


def test_the_registered_debt_names_a_real_file_and_a_real_owner():
    """The allowlist is a record, not a licence: an entry must name the task
    that removes it and point at a file that exists, so the debt cannot
    quietly become permanent or be used to excuse a file that is not there."""
    for path_text, owner in REGISTERED_HOST_DEBT.items():
        assert owner.strip(), f"{path_text} has no registered owner"
        assert (REPO_ROOT / path_text).is_file(), f"{path_text} is registered but absent"


def test_no_core_source_of_this_package_names_a_brand():
    """The same rule over the code this package added."""
    roots = (
        REPO_ROOT / "apps/server/src/ordessa_server/bootstrap",
        REPO_ROOT / "apps/server/src/ordessa_server/observability",
        REPO_ROOT / "packages/desktop-platform/server-bridge/src",
    )
    offences: "dict[str, list[str]]" = {}
    for base in roots:
        for candidate in base.rglob("*"):
            if candidate.suffix not in (".py", ".ts", ".json"):
                continue
            text = candidate.read_text(encoding="utf-8", errors="replace").lower()
            hits = sorted(
                name for name in BRAND_NAMES
                if re.search(rf"\b{re.escape(name)}\b", text)
            )
            if hits:
                offences[candidate.relative_to(REPO_ROOT).as_posix()] = hits
    assert offences == {}, f"core source names a Harness brand: {offences}"


def test_the_shared_layout_and_the_contract_agree_on_the_five_data_root_codes():
    """The codes are a contract between the two languages; this is the cheap
    half of that check, from the side that owns the file."""
    import json

    from ordessa_server.bootstrap.data_root import DATA_ROOT_ERROR_CODES, LAYOUT

    assert DATA_ROOT_ERROR_CODES == tuple(LAYOUT["dataRootErrors"])
    shared = json.loads(
        (REPO_ROOT / "apps/server/src/ordessa_server/bootstrap/data_root_layout.json")
        .read_text(encoding="utf-8")
    )
    assert list(shared["dataRootErrors"]) == list(DATA_ROOT_ERROR_CODES)

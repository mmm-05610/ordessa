"""T03/T03b red/green: import-boundary gate for the adapters package.

`pacthold`/host boundary rules (AGENTS.md): the adapters may import the
standard library, the consumed domain contract `ordessa_permissions_api`,
the public plugin surface `server_plugin_api`, the Harness *public contract
package* `ordessa_harness_api` (the same dependency set the platform's own
external-adapter exemplar declares) and themselves - nothing else. In
particular no `ordessa_server`, no harness implementation internals
(`ordessa_harness` proper, as distinct from the `_api` contract), no compat
engine and no sandbox-domain name crosses this line, and the runtime
authorization gate (G1) is not pretended to exist here.
"""
from __future__ import annotations

import ast
import pathlib
import re
import sys

SRC_ROOT = pathlib.Path(__file__).resolve().parents[1] / "src" / "ordessa_permissions_adapters"
#: bare module names that must never appear in src text; `ordessa_harness`
#: is checked separately so the public `ordessa_harness_api` contract import
#: is not caught by substring matching.
FORBIDDEN_TEXT = (
    "ordessa_server", "ordessa_server_compat", "pacthold",
    "sandboxv1", "SandboxV1", "ordessa_sandbox",
)
HARNESS_INTERNALS = re.compile(r"ordessa_harness(?!_api)\b")
STDLIB_OK = set(sys.stdlib_module_names)
ALLOWED = STDLIB_OK | {"__future__", "ordessa_permissions_api", "server_plugin_api",
                       "ordessa_harness_api", "ordessa_permissions_adapters"}


def _sources() -> list[pathlib.Path]:
    return sorted(SRC_ROOT.glob("**/*.py"), key=str)


def _roots(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0 and node.module:
                found.add(node.module.split(".")[0])
    return found


def test_sources_exist() -> None:
    assert _sources(), "no modules under src/"


def test_imports_stay_inside_the_allowed_roots() -> None:
    for path in _sources():
        for root in _roots(ast.parse(path.read_text(encoding="utf-8"), filename=str(path))):
            assert root in ALLOWED, f"{path.name} imports {root!r}"


def test_no_host_or_sandbox_domain_name_appears_in_source() -> None:
    for path in _sources():
        text = path.read_text(encoding="utf-8")
        for forbidden in FORBIDDEN_TEXT:
            assert forbidden not in text, f"{path.name} mentions {forbidden!r}"
        # the harness *implementation* package may not be named; the public
        # `ordessa_harness_api` contract is allowed and must not trip this.
        assert HARNESS_INTERNALS.search(text) is None, path.name


def test_the_package_does_not_claim_an_authorization_gate() -> None:
    # The runtime authorization seam is a different contract owned by the
    # backend line and blocked on G1; this package must not name it as its
    # own surface anywhere in src.
    for path in _sources():
        text = path.read_text(encoding="utf-8")
        assert "permissions.authorizer" not in text, path.name

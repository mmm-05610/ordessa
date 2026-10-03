"""Public contract gates for external sample #3 (terminal-view).

The sample's claim is that the public plugin contracts admit a
terminal/document view with zero Agent/Chat/Profile involvement, reached
only through `ordessa_server.bootstrap.build_runtime` with an explicit
`server_plugins` selection. These gates pin that claim from the outside:

- the build seam composes exactly the sample and its discovery face is
  exactly three methods plus `server.hello`, owned by
  `ordessa.sample-terminal`;
- the declared dependency/import surface is the public plugin API plus the
  standard library, with a word-list gate for private/domain/prompt
  modules and for Electron/React frontend imports;
- the honest gap: the read-only face declares `writable=false` and
  `reliableSubmission=unsupported`; index/revisions/preview are a declared
  absence, not a silently missing feature.
"""
from __future__ import annotations

import ast
import sys
import tomllib
from pathlib import Path

from ordessa_server.bootstrap import build_runtime

from ordessa_sample_terminal import (
    CAPABILITIES,
    METHOD_CAPABILITIES,
    METHOD_OPEN,
    METHOD_READ,
    PLUGIN_ID,
    SampleTerminalPlugin,
)

PLUGIN_PACKAGE_DIR = Path(__file__).resolve().parents[1] / "src" / "ordessa_sample_terminal"
PYPROJECT_PATH = Path(__file__).resolve().parents[1] / "pyproject.toml"
BUSINESS_METHODS = (METHOD_OPEN, METHOD_READ, METHOD_CAPABILITIES)
HELLO_PARAMS = {"clientVersions": ["wire/1"], "clientPresentationSupports": []}

# Private/domain modules an independent external sample must never reach
# for. The prompt-family words are part of the same word list: importing the
# host's prompt library is exactly as forbidden as importing the harness.
FORBIDDEN_IMPORT_WORDS = frozenset({
    "ordessa_harness", "ordessa_profile", "ordessa_server",
    "ordessa_environment_api", "ordessa_prompts", "prompts", "prompt",
    "pacthold", "pacthold_runtime_compat",
    "desktop_platform", "electron", "react", "react_dom",
})
PROMPT_WORDLIST = frozenset({"ordessa_prompts", "prompts", "prompt"})
FRONTEND_SUFFIXES = frozenset({".js", ".jsx", ".ts", ".tsx", ".css", ".html", ".vue", ".svelte"})


def _build(tmp_path: Path):
    return build_runtime(tmp_path / "data", server_plugins=(SampleTerminalPlugin(),))


def _hello(runtime) -> dict:
    return runtime.wire.dispatch("server.hello", HELLO_PARAMS)


def _imports(path: Path):
    """Yield every imported top-level module name in one Python file."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, path
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # intra-package relative import: not a platform reach
                continue
            if node.module:
                yield node.module, path


# -- public seam and discovery ------------------------------------------------

def test_build_runtime_public_seam_composes_exactly_the_sample(tmp_path):
    runtime = _build(tmp_path)
    assert runtime.started is False
    runtime.start()
    try:
        assert runtime.started is True
        assert tuple(runtime.plugin_host.active_ids()) == (PLUGIN_ID,)
        assert set(runtime.plugin_host.methods.method_ids()) == {
            "server.hello", *BUSINESS_METHODS}
    finally:
        runtime.stop()
    assert runtime.started is False


def test_wire_discovery_face_is_exactly_three_supported_methods_owned_by_the_sample(tmp_path):
    assert PLUGIN_ID == "ordessa.sample-terminal"
    runtime = _build(tmp_path)
    runtime.start()
    try:
        caps = {item["id"]: item for item in _hello(runtime)["capabilities"]}
        assert set(caps) == {"server.hello", *BUSINESS_METHODS}
        for method in BUSINESS_METHODS:
            assert caps[method]["supported"] is True
            descriptor = runtime.plugin_host.methods.lookup(method)
            assert descriptor is not None
            assert descriptor.owner == PLUGIN_ID == "ordessa.sample-terminal"
    finally:
        runtime.stop()


def test_sample_declares_no_agent_chat_or_profile_dependency():
    descriptor = SampleTerminalPlugin().descriptor()
    assert descriptor.id == PLUGIN_ID
    assert descriptor.requires == ()
    assert CAPABILITIES["requires"] == {"agent": False, "chat": False, "profile": False}


# -- AST gates: private imports, prompt word list, Electron/React -------------

def test_ast_gate_every_import_is_stdlib_or_the_public_plugin_api():
    plugin_api = {"server_plugin_api"}
    for name, path in _imports_under(PLUGIN_PACKAGE_DIR):
        top = name.split(".")[0]
        assert top in sys.stdlib_module_names or top in plugin_api, (
            f"{path} imports {name!r}: the sample may only use the stdlib and "
            "the public server_plugin_api contract")


def test_ast_gate_private_domain_and_prompt_word_list_is_blocked():
    assert PROMPT_WORDLIST <= FORBIDDEN_IMPORT_WORDS
    for name, path in _imports_under(PLUGIN_PACKAGE_DIR):
        top = name.split(".")[0]
        assert top not in FORBIDDEN_IMPORT_WORDS, (
            f"{path} imports {name!r}: forbidden by the private/prompt word list")
        # dynamic import back doors are the same violation
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id == "__import__":
                    raise AssertionError(f"{path} uses __import__")
                if isinstance(func, ast.Attribute) and func.attr == "import_module":
                    raise AssertionError(f"{path} uses import_module")


def test_no_electron_or_react_artifacts_in_the_plugin_surface():
    for name, path in _imports_under(PLUGIN_PACKAGE_DIR):
        top = name.split(".")[0]
        assert not top.startswith(("electron", "react")), f"{path} imports {name!r}"
    for path in PLUGIN_PACKAGE_DIR.rglob("*"):
        if path.is_file():
            assert path.suffix.lower() not in FRONTEND_SUFFIXES, (
                f"frontend artifact in the python plugin surface: {path}")


def test_distribution_declares_only_the_public_plugin_api_dependency():
    declared = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    assert declared["project"]["dependencies"] == ["ordessa-server-plugin-api>=0.1.0,<1"]


# -- honest gap: declared absence of index/revisions/preview ------------------

def test_read_only_face_declares_typed_unsupported_and_no_write_contract():
    assert CAPABILITIES["writable"] is False
    assert CAPABILITIES["reliableSubmission"] == "unsupported"
    reason = CAPABILITIES["reliableSubmissionReason"]
    assert "read-only" in reason
    assert "refused" in reason and "typed-unsupported" in reason
    assert "never silently downgraded" in reason


def test_index_revisions_and_preview_are_a_declared_absence_not_a_fake_success(tmp_path):
    # The capability document promises no index/revisions/preview face at all.
    for undeclared in ("index", "revisions", "preview", "write", "edit"):
        assert undeclared not in CAPABILITIES, (
            f"{undeclared!r} appears in capabilities without a declared contract")
    runtime = _build(tmp_path)
    runtime.start()
    try:
        read = runtime.wire.dispatch(METHOD_READ, {"id": "doc-1"})
        assert set(read) == {"document", "contentSha256", "readOnly"}
        for undeclared in ("index", "revisions", "preview"):
            assert undeclared not in read
    finally:
        runtime.stop()


def _imports_under(package_dir: Path):
    for path in sorted(package_dir.rglob("*.py")):
        yield from _imports(path)

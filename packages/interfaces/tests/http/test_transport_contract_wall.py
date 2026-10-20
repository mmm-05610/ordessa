"""Keep HTTP transport independent of Server and system-access implementations.

The source scan guards imports that are visible statically.  The subprocess
check then imports the *installed* ``ordessa-interfaces`` distribution while
blocking those runtime modules, so a hidden eager dependency cannot pass just
because the AST check missed a dynamic import.

Runtime requirements remain those declared by the existing distribution in
``packages/interfaces/pyproject.toml`` for both editable/source and wheel
installs: FastAPI, ``ordessa-server-plugin-api``,
``ordessa-infrastructure``, ``jsonschema`` and ``referencing``.  This test does
not install or build either form; it verifies the currently selected install.
"""
from __future__ import annotations

import ast
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


_REPO_ROOT = Path(__file__).resolve().parents[4]
_HTTP_SOURCE = (
    _REPO_ROOT / "packages/interfaces/transport/server/src/ordessa_interfaces/http"
)
_FORBIDDEN_PREFIXES = (
    "ordessa_server",
    "ordessa_engineering",
    "ordessa_units",
    "ordessa_execution_agents.units",
)
_SYSTEM_ACCESS_ROOT = "ordessa_interfaces.system_access"


def _imported_modules(tree: ast.AST, *, package: str = "ordessa_interfaces.http") -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if node.level:
                package_parts = package.split(".")[: len(package.split(".")) - node.level + 1]
                base = ".".join((*package_parts, *module.split(".")))
            else:
                base = module
            if base:
                names.append(base)
                names.extend(f"{base}.{alias.name}" for alias in node.names)
    return names


def _forbidden_imports(source: str, *, filename: str = "<fixture>") -> list[str]:
    """Return forbidden absolute imports; shared ``system_access.contracts`` is allowed."""
    tree = ast.parse(source, filename=filename)
    violations: list[str] = []
    for name in _imported_modules(tree):
        if name == _SYSTEM_ACCESS_ROOT or name.startswith(_SYSTEM_ACCESS_ROOT + "."):
            if name == _SYSTEM_ACCESS_ROOT + ".contracts" or name.startswith(
                _SYSTEM_ACCESS_ROOT + ".contracts."
            ):
                continue
            violations.append(name)
            continue
        if any(name == prefix or name.startswith(prefix + ".") for prefix in _FORBIDDEN_PREFIXES):
            violations.append(name)
    return violations


def test_http_transport_source_imports_only_shared_contracts_from_system_access():
    assert _HTTP_SOURCE.is_dir(), f"expected current HTTP source root: {_HTTP_SOURCE}"
    violations = []
    for path in sorted(_HTTP_SOURCE.rglob("*.py")):
        violations.extend(
            f"{path.relative_to(_REPO_ROOT)}: {name}"
            for name in _forbidden_imports(path.read_text(encoding="utf-8"), filename=str(path))
        )
    assert violations == []


def test_ast_wall_rejects_an_injected_implementation_import_but_allows_contracts():
    bad_fixture = (
        "from ordessa_interfaces.system_access.access_control import InstanceAccessAuthority\n"
    )
    assert "ordessa_interfaces.system_access.access_control" in _forbidden_imports(bad_fixture)
    allowed_fixture = (
        "from ordessa_interfaces.system_access.contracts.transport import AccessError, WIRE_VERSION\n"
    )
    assert _forbidden_imports(allowed_fixture) == []


def test_create_app_imports_from_the_current_install_with_host_and_domain_modules_blocked():
    # Resolve the import normally: do not prepend this checkout's source roots
    # to sys.path, which would make an uninstalled tree look like a wheel.
    http_module = importlib.import_module("ordessa_interfaces.http")
    origin = Path(http_module.__file__).resolve()
    editable_origin = _HTTP_SOURCE / "__init__.py"
    distribution = importlib.metadata.distribution("ordessa-interfaces")
    installed_origin = Path(
        distribution.locate_file("ordessa_interfaces/http/__init__.py")
    ).resolve()
    assert origin in {editable_origin.resolve(), installed_origin}, origin

    script = r'''
import builtins
import json
import sys
from pathlib import Path

blocked = (
    "ordessa_server",
    "ordessa_engineering",
    "ordessa_units",
    "ordessa_execution_agents.units",
)
original_import = builtins.__import__
def guarded_import(name, *args, **kwargs):
    candidates = [name]
    candidates.extend(name + "." + item for item in (kwargs.get("fromlist") or ()))
    # ``from x import y`` passes fromlist positionally to __import__.
    if len(args) > 2 and args[2]:
        candidates.extend(name + "." + item for item in args[2])
    for candidate in candidates:
        system_access_impl = (
            candidate == "ordessa_interfaces.system_access"
            or candidate.startswith("ordessa_interfaces.system_access.")
            and not (candidate == "ordessa_interfaces.system_access.contracts"
                     or candidate.startswith("ordessa_interfaces.system_access.contracts."))
        )
        if system_access_impl or any(
            candidate == prefix or candidate.startswith(prefix + ".") for prefix in blocked
        ):
            raise AssertionError("blocked implementation import: " + candidate)
    return original_import(name, *args, **kwargs)
builtins.__import__ = guarded_import

from ordessa_interfaces.http import create_app
import ordessa_interfaces.http as http_module
assert callable(create_app)
print(json.dumps({"origin": str(Path(http_module.__file__).resolve())}))
'''
    env = os.environ.copy()
    # Ensure the subprocess uses the same interpreter/environment as pytest,
    # without adding package source directories or relying on the test process's
    # imported module cache.
    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=_REPO_ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    child_origin = Path(json.loads(result.stdout.strip().splitlines()[-1])["origin"]).resolve()
    assert child_origin == origin


def test_moved_cursor_codec_keeps_the_historical_wire_format_and_rejects_tampering():
    from ordessa_interfaces.system_access.subscriptions.cursors import CursorCodec
    from server_plugin_api.wire_errors import WireError

    codec = CursorCodec(b"fixture-secret")
    cursor = codec.encode("session-1", 42)
    # The pre-move format is HMAC-SHA256(SHA256(secret), UTF-8(payload)),
    # truncated to 12 bytes, then unpadded URL-safe base64.
    assert cursor == "w1:session-1:42:eAq54N1YEwURM19I"
    assert codec.decode(cursor, expected_session="session-1") == ("session-1", 42)

    tampered = cursor.replace(":42:", ":43:")
    with pytest.raises(WireError):
        codec.decode(tampered)
    with pytest.raises(WireError):
        codec.decode(cursor, expected_session="another-session")

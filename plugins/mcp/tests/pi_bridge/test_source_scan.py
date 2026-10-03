"""Mechanical scan of the managed extension source (design hard clause).

docs/design/mcp/contracts.md §3: the Pi extension is only a managed entry
point - it may not connect to an MCP server itself, may not hold
credentials, and must not speak to any address but the Server's loopback
control channel. These are properties of the *shipped source*, so they
are checked as text, not as trust: any construction that could break them
makes this scan red.
"""
from __future__ import annotations

import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
PI_ADAPTER = HERE.parent.parent / "adapters" / "pi"
EXTENSION = PI_ADAPTER / "ordessa-mcp-bridge.ts"

SOURCE = EXTENSION.read_text(encoding="utf-8")


def _code() -> str:
    """The source without block comments (prose may describe what is banned)."""
    return re.sub(r"/\*.*?\*/", "", SOURCE, flags=re.S)


def test_extension_source_exists_and_is_packaged():
    assert EXTENSION.is_file()
    package = (PI_ADAPTER / "package.json")
    manifest = package.read_text(encoding="utf-8")
    assert '"ordessa-mcp-bridge.ts"' in manifest
    assert (PI_ADAPTER / "scripts" / "pack.mjs").is_file(), \
        "an executable extension needs its own version/digest packaging step"


def test_only_node_net_and_type_only_pi_imports():
    imports = re.findall(r'^import[^\n]*from "([^"]+)"', _code(), flags=re.M)
    assert sorted(imports) == ["@earendil-works/pi-coding-agent", "node:net",
                               "node:process"], imports
    # the pi import is type-only (erased at load); no runtime product imports
    assert re.search(r'import type \{ ExtensionAPI \}', SOURCE)


def test_no_mcp_client_no_http_no_fetch_no_dns():
    forbidden = [
        r"\bfetch\s*\(", r"node:http", r"node:https", r"node:dns",
        r"XMLHttpRequest", r"@modelcontextprotocol", r"pi-mcp-adapter",
        r"StreamableHTTP", r"SSEClient", r"from\s+\"[^\"]*mcp[^\"]*\"",
        r"\bnew\s+Client\b",
    ]
    for pattern in forbidden:
        assert re.search(pattern, _code(), flags=re.I) is None, \
            f"the extension must not be able to reach a target server: {pattern}"


def test_connect_host_is_the_loopback_literal_only():
    assert re.search(r'const LOOPBACK_HOST = "127\.0\.0\.1";', SOURCE)
    connects = [c.strip() for c in re.findall(r"net\.connect\(\{([^}]*)\}", _code())]
    assert connects == ["host: LOOPBACK_HOST, port: this.port"], connects
    hosts = re.findall(r'host\s*:\s*([^,}\n]+)', _code())
    assert set(hosts) == {"LOOPBACK_HOST"}, hosts
    # no address literal anywhere except loopback; no env-supplied host read
    addresses = set(re.findall(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', _code()))
    assert addresses in ({"127.0.0.1"}, set()), addresses
    assert "ORDESSA_PI_BRIDGE_HOST" not in _code(), \
        "the host env entry is launcher documentation only - the extension " \
        "never reads a host it could be tricked with"


def test_environment_surface_is_port_and_token_only():
    env_reads = sorted(set(re.findall(r'process\.env\.(\w+)|requiredEnv\("(\w+)"\)', _code())))
    flat = {a or b for a, b in env_reads}
    assert flat == {"ORDESSA_PI_BRIDGE_PORT", "ORDESSA_PI_BRIDGE_TOKEN"}, flat


def test_no_credential_shaped_identifiers():
    for pattern in (r"secretRef", r"apiKey", r"credential", r"password", r"tokenFile"):
        assert re.search(pattern, _code(), flags=re.I) is None, \
            f"the extension process is never handed credentials: {pattern}"


def test_python_peer_binds_loopback_only():
    peer = (HERE.parent.parent / "backend" / "managed" / "pi_bridge.py")
    text = peer.read_text(encoding="utf-8")
    binds = re.findall(r"\.bind\(\(([^,)]+),", text)
    assert binds == ["self._host"], binds
    assert 'LOOPBACK_HOST = "127.0.0.1"' in text
    assert "if host != LOOPBACK_HOST" in text, \
        "a non-loopback listen address must be a typed refusal"

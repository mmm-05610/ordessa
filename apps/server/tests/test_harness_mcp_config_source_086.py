"""Order 086 stage 1: pin, first-hand, which file a real Harness reads its MCP
server list from - because 65 synthesized the bridge entry into the family's
declared `mcp_target`, and that path may not be a path the Harness reads, or
may be a path the deployment already owns as a read-only projection.

The probe is deliberately not the bridge: a static MCP server that answers
`tools/list` from memory isolates one question (did the client read this file)
from everything 65 already proved (that the bridge speaks MCP and delegates).
The answer is read out of the *model request* the CLI sends: a tool that only
this file can introduce either appears in its `tools` array or it does not.

Zero model calls: the endpoint is a loopback fake that logs the request bodies
and answers with a fixed text block.

    AGENTBOX_086_PIN_REPORT=/tmp/086-pin.json pytest -q tests/server \
        -k mcp_config_source
"""
from __future__ import annotations

import http.server
import json
import os
import pathlib
import shutil
import subprocess
import threading

import pytest

REPO = pathlib.Path(__file__).resolve().parents[3]
PROBE_SERVER = REPO / "tests" / "server" / "fixtures" / "mcp-config-probe-server.mjs"
PROBE_TOOL = "probe_tool_086"
PROBE_SERVER_NAME = "agentbox-probe"
FAKE_TOKEN = "086-probe-not-a-secret"

CLAUDE = shutil.which("claude")
NODE = shutil.which("node")


class Endpoint(http.server.BaseHTTPRequestHandler):
    """One loopback Anthropic Messages endpoint; it records what it is asked."""

    protocol_version = "HTTP/1.1"
    seen: list[dict] = []

    def log_message(self, *_args) -> None:
        pass

    def do_POST(self) -> None:  # noqa: N802 (http.server API)
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        try:
            body = json.loads(raw.decode("utf-8"))
        except ValueError:
            body = {}
        Endpoint.seen.append({
            "path": self.path,
            "authorized": self.headers.get("x-api-key") == FAKE_TOKEN
            or self.headers.get("authorization") == f"Bearer {FAKE_TOKEN}",
            "tools": sorted(tool.get("name") for tool in body.get("tools") or []
                            if isinstance(tool, dict)),
        })
        answer = "probe"
        events = [
            {"type": "message_start", "message": {
                "id": "msg_086_probe", "type": "message", "role": "assistant",
                "content": [], "model": body.get("model", "probe-model"),
                "usage": {"input_tokens": 1, "output_tokens": 1}}},
            {"type": "content_block_start", "index": 0,
             "content_block": {"type": "text", "text": ""}},
            {"type": "content_block_delta", "index": 0,
             "delta": {"type": "text_delta", "text": answer}},
            {"type": "content_block_stop", "index": 0},
            {"type": "message_delta", "delta": {"stop_reason": "end_turn"},
             "usage": {"output_tokens": 1}},
            {"type": "message_stop"},
        ]
        payload = b"".join(
            f"event: {event['type']}\ndata: {json.dumps(event)}\n\n".encode()
            for event in events)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


@pytest.fixture()
def loopback():
    Endpoint.seen = []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Endpoint)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _entry() -> dict:
    return {
        "type": "stdio",
        "command": NODE,
        "args": [str(PROBE_SERVER)],
        "env": {},
    }


def _run_claude(base_url: str, *, config_dir: pathlib.Path, cwd: pathlib.Path) -> list[str]:
    environment = {
        key: value for key, value in os.environ.items()
        # An isolated HOME plus a cleared key: the measurement must not be
        # contaminated by (or written into) the developer's own configuration.
        if key not in {"ANTHROPIC_API_KEY", "HOME", "CLAUDE_CONFIG_DIR"}
    }
    config_dir.mkdir(parents=True, exist_ok=True)
    home = config_dir.parent / "home"
    home.mkdir(parents=True, exist_ok=True)
    environment.update({
        "HOME": str(home),
        "CLAUDE_CONFIG_DIR": str(config_dir),
        "ANTHROPIC_BASE_URL": base_url,
        "ANTHROPIC_AUTH_TOKEN": FAKE_TOKEN,
        "ANTHROPIC_API_KEY": "",
        "API_TIMEOUT_MS": "30000",
        "DISABLE_TELEMETRY": "1",
        "DISABLE_ERROR_REPORTING": "1",
        "DISABLE_AUTOUPDATER": "1",
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    })
    process = subprocess.run(
        [CLAUDE, "-p", "Reply with the single word ok.",
         "--model", "probe-model", "--output-format", "json"],
        cwd=str(cwd), env=environment, capture_output=True, text=True, timeout=180,
    )
    assert Endpoint.seen, (
        f"the CLI made no model request (exit {process.returncode}): "
        f"{process.stdout[-400:]}{process.stderr[-400:]}")
    return [name for item in Endpoint.seen for name in item["tools"]]


def _claude_cli_version() -> str:
    return subprocess.run([CLAUDE, "--version"], capture_output=True, text=True,
                          timeout=60).stdout.strip()


def _write_settings(root: pathlib.Path, document: dict) -> None:
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "settings.json").write_text(json.dumps(document), encoding="utf-8")


def _write_claude_json(root: pathlib.Path, document: dict) -> None:
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / ".claude.json").write_text(
        json.dumps({"theme": "dark", **document}), encoding="utf-8")


def _write_project_mcp_json(root: pathlib.Path, document: dict) -> None:
    (root / "project").mkdir(parents=True, exist_ok=True)
    (root / "project" / ".mcp.json").write_text(json.dumps(document), encoding="utf-8")


#: The three places a claude-code MCP server entry can be declared, written one
#: at a time so a positive result names its own source. `advertises` is the
#: measured answer (CLI 2.1.274, loopback fake endpoint, isolated HOME, one
#: model request per case): only the two files the CLI actually reads for MCP
#: servers put the tool into the request's `tools` array.
SOURCES = {
    "settings.json": _write_settings,
    ".claude.json": _write_claude_json,
    ".mcp.json": _write_project_mcp_json,
}
ADVERTISES = {"settings.json": False, ".claude.json": True, ".mcp.json": True}


@pytest.mark.skipif(CLAUDE is None or NODE is None, reason="claude CLI and node required")
@pytest.mark.parametrize("source", sorted(SOURCES))
def test_which_claude_config_source_advertises_an_mcp_tool(source, tmp_path, loopback):
    """The pinning measurement: `settings.json` is not a path the CLI reads.

    The Server writes the entry into the family's declared `mcp_target`, so a
    target the Harness never opens means a granted parent advertises nothing -
    and the `.claude.json` result is what moved 086's slot for claude-code.
    """
    document = {"mcpServers": {PROBE_SERVER_NAME: _entry()}}
    SOURCES[source](tmp_path, document)
    tools = _run_claude(
        loopback, config_dir=tmp_path / "config",
        cwd=tmp_path / ("project" if source == ".mcp.json" else "config"))
    names = [name for name in tools if PROBE_TOOL in name or PROBE_SERVER_NAME in name]
    _record(tmp_path, source, names)
    if ADVERTISES[source]:
        assert names == [f"mcp__{PROBE_SERVER_NAME}__{PROBE_TOOL}"], names
    else:
        assert names == [], (
            f"{source} unexpectedly advertises the probe tool: the read-path pin "
            "this order chose the bridge slot with is no longer first-hand")


def _record(tmp_path, source: str, names) -> None:
    report_path = os.environ.get("AGENTBOX_086_PIN_REPORT")
    if not report_path:
        return
    report = pathlib.Path(report_path)
    existing = json.loads(report.read_text(encoding="utf-8")) if report.is_file() else {}
    existing[source] = {
        "advertised": names,
        "requestCount": len(Endpoint.seen),
        "authorizedRequests": sum(1 for item in Endpoint.seen if item["authorized"]),
        "claudeVersion": _claude_cli_version(),
    }
    report.write_text(json.dumps(existing, indent=2, sort_keys=True), encoding="utf-8")


@pytest.mark.skipif(CLAUDE is None or NODE is None, reason="claude CLI and node required")
def test_the_probe_tool_does_not_appear_when_no_source_declares_it(tmp_path, loopback):
    """The counter-example: the advertisement is caused by the file, not by
    the environment, the fake endpoint or the CLI's own tools."""
    (tmp_path / "config").mkdir()
    tools = _run_claude(loopback, config_dir=tmp_path / "config", cwd=tmp_path / "config")
    names = [name for name in tools if PROBE_TOOL in name or PROBE_SERVER_NAME in name]
    _record(tmp_path, "control-none", names)
    assert names == [], names


def test_the_registry_slot_for_claude_code_is_a_file_the_cli_reads():
    """Divergence guard: the measured read path and the declared slot agree.

    If the registry moves back onto a projected or unread file, the bridge and
    the user's own MCP servers land where nobody looks and a granted parent
    advertises nothing - which is the bug this order found.
    """
    from ordessa_server_product.harness_adapters.registry import load_builtin_registry

    profile = load_builtin_registry().get("claude-code").profile
    assert profile.mcp_target == "/runtime/home/.claude/.claude.json"
    assert profile.mcp_key == "mcpServers"
    # The slot is inside the config home the production template pins, so the
    # CLI finds it, and it is not the read-only provider projection.
    from ordessa_harness_claude_code import production

    assert profile.mcp_target.startswith(production.CONFIG_HOME + "/")
    assert profile.mcp_target not in {
        item["target"] for item in production.projection_files()}

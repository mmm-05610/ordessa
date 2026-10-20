"""Cross-process proof of the remote-mode MCP loop, including a business call.

A real Ordessa Server runs in this project's venv; the MCP server runs in
an **isolated** venv holding only the official SDK closure (no
``ordessa_interfaces``); an MCP stdio client in that same isolated venv drives a
real tool call, which reaches the Server over HTTP. Gated on
``ORDESSA_MCP_PYTHON`` pointing at the isolated interpreter.
"""
import json
import os
import pathlib
import selectors
import subprocess
import sys
import time

import pytest

REPO = pathlib.Path(__file__).resolve().parents[5]
MCP_PYTHON = os.environ.get("ORDESSA_MCP_PYTHON")
HERE = pathlib.Path(__file__).resolve().parent

pytestmark = pytest.mark.skipif(
    not MCP_PYTHON, reason="ORDESSA_MCP_PYTHON (isolated MCP env) not set")


def _nested_json_values(value):
    """Walk MCP structured content and JSON text blocks without flattening the result."""
    if isinstance(value, dict):
        yield value
        for nested in value.values():
            yield from _nested_json_values(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _nested_json_values(nested)
    elif isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            return
        if isinstance(decoded, (dict, list)):
            yield from _nested_json_values(decoded)


def _stop_owned_process(process):
    if process is not None and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def test_remote_mcp_loop_returns_real_connectivity_and_business_results(tmp_path):
    root = tmp_path / "server-root"
    library = tmp_path / "engineering.sqlite"
    server_command = [
        sys.executable, "-m", "ordessa_server",
        "--data-root", str(root), "--port", "0",
        "--engineering-library", str(library),
        "--engineering-library-id", "mcp-library",
        "--engineering-realm", "mcp-realm",
        "--engineering-project", "mcp-project",
        "--engineering-create-library",
        "--engineering-machine-capability", "engineering.capabilities",
    ]
    server = subprocess.Popen(server_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              env=os.environ.copy())
    try:
        deadline = time.monotonic() + 30
        with selectors.DefaultSelector() as selector:
            selector.register(server.stdout, selectors.EVENT_READ)
            while not selector.select(0):
                if server.poll() is not None:
                    raise AssertionError(server.stderr.read().decode())
                if time.monotonic() > deadline:
                    raise AssertionError("Ordessa server readiness deadline exceeded")
                time.sleep(0.05)
            line = server.stdout.readline()
        assert line, "Ordessa server exited before its listening handshake"
        handshake = json.loads(line)
        assert handshake["pid"] == server.pid
        assert handshake["origin"].startswith("http://127.0.0.1:")
        endpoint = handshake["origin"]

        # The bearer remains in the disposable root's private token file and
        # the child environment only; it is never embedded in readiness data.
        from ordessa_server.bootstrap.data_root import token_file
        token = token_file(root).read_text().strip()
        assert token

        env = os.environ.copy()
        env["ORDESSA_MCP_ENDPOINT"] = endpoint
        env["ORDESSA_MCP_TOKEN"] = token
        probe = subprocess.run(
            [MCP_PYTHON, str(HERE / "mcp_client_probe.py"),
             str(REPO / "packages/interfaces/channels/mcp/src/ordessa_mcp_server/server.py")],
            env=env, capture_output=True, text=True, timeout=90)
        assert probe.returncode == 0, probe.stderr
        assert token not in probe.stdout + probe.stderr
        lines = [json.loads(line) for line in probe.stdout.splitlines()
                 if line.strip().startswith("{")]
        tools = next(item["tools"] for item in lines if "tools" in item)
        assert {"ordessa_capabilities", "ordessa_wire_call"} <= set(tools)
        connectivity = json.dumps(next(item["connectivity"] for item in lines if "connectivity" in item))
        assert "server.hello" in connectivity
        business_result = next(item["business"] for item in lines if "business" in item)
        capabilities = next((item for item in _nested_json_values(business_result)
                             if item.get("contract_version") == "engineering-wire/1"), None)
        assert capabilities is not None
        assert capabilities["scope"] == {"realm_id": "mcp-realm", "project_id": "mcp-project"}
        assert capabilities["supports"]["method_slot_bridge"] is True
        assert capabilities["supports"]["consent"] is False
        assert capabilities["supports"]["dispatch"] is False

        # Server-side refusal (distinct from the MCP local missing-token refusal):
        # a request with no Authorization is rejected by the Server itself.
        import urllib.error
        import urllib.request
        request = urllib.request.Request(
            f"{endpoint}/wire/v1/server.hello",
            data=json.dumps({"jsonrpc": "2.0", "id": "x", "method": "server.hello",
                             "params": {"clientVersions": ["wire/1"], "clientPresentationSupports": []}}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        with pytest.raises(urllib.error.HTTPError) as unauthorized:
            urllib.request.urlopen(request, timeout=10)
        assert unauthorized.value.code == 401

        # A wrong bearer token through the MCP adapter is refused by the Server.
        wrong_token = "wrong-token"
        env["ORDESSA_MCP_TOKEN"] = wrong_token
        wrong = subprocess.run(
            [MCP_PYTHON, str(HERE / "mcp_client_probe.py"),
             str(REPO / "packages/interfaces/channels/mcp/src/ordessa_mcp_server/server.py")],
            env=env, capture_output=True, text=True, timeout=90)
        assert wrong.returncode == 0, wrong.stderr
        wrong_lines = [json.loads(line) for line in wrong.stdout.splitlines()
                       if line.strip().startswith("{")]
        # The Server refused the wrong bearer token: both MCP calls come back as
        # errors, and the token never appears in the output.
        errors = []
        for item in wrong_lines:
            for key in ("connectivity", "business"):
                if key not in item:
                    continue
                errors.append(any(value.get("is_error", value.get("isError", False))
                                  for value in _nested_json_values(item[key])))
        assert errors and all(errors)
        assert wrong_token not in wrong.stdout + wrong.stderr
        assert token not in wrong.stdout + wrong.stderr
    finally:
        _stop_owned_process(server)
        if server.stdout is not None:
            server.stdout.close()
        if server.stderr is not None:
            server.stderr.close()

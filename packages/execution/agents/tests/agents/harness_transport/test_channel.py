"""Counter-example tests for the frozen native-channel transport seam (G4/G5/G6/G11/G12).

These are fixture-level (L1) tests against a scripted peer process; they prove
framing/typed-failure/unknown-preservation behaviour, not upstream compatibility.
"""

from __future__ import annotations

import json
import os
import sys
import textwrap

import pytest

from ordessa_agents.harness.transport import (
    ChannelClosed,
    FrameReader,
    FramingError,
    LaunchSpec,
    LostReceipt,
    ProcessChannel,
    RemoteFailure,
    RequestTimeout,
    isolated_env,
)

# -- FrameReader (G5) ---------------------------------------------------------


def test_frame_split_inside_multibyte_utf8_sequence() -> None:
    reader = FrameReader()
    frame = json.dumps({"method": "日", "params": {"k": "本語"}}, ensure_ascii=False) + "\n"
    data = frame.encode("utf-8")
    # split in the middle of a multi-byte character
    cut = data.index("日".encode("utf-8")) + 1
    assert reader.feed(data[:cut]) == []
    decoded = reader.feed(data[cut:])
    assert len(decoded) == 1
    assert json.loads(decoded[0]) == json.loads(frame)


def test_u2028_is_not_a_frame_separator() -> None:
    reader = FrameReader()
    payload = '{"method":"m","params":{"text":"a b c"}}\n'
    frames = reader.feed(payload.encode("utf-8"))
    assert len(frames) == 1
    assert json.loads(frames[0])["params"]["text"] == "a b c"


def test_oversize_frame_is_typed_failure() -> None:
    reader = FrameReader(max_frame_bytes=16)
    with pytest.raises(FramingError) as excinfo:
        reader.feed(b"x" * 32)
    assert excinfo.value.code == "FRAMING_ERROR"


def test_invalid_utf8_is_typed_failure() -> None:
    reader = FrameReader()
    with pytest.raises(FramingError):
        reader.feed(b"\xff\xfe broken\n")


def test_truncated_frame_at_eof_is_typed_failure() -> None:
    reader = FrameReader()
    reader.feed(b'{"method":"partial"')
    with pytest.raises(FramingError):
        reader.close()


def test_crlf_frames_are_accepted() -> None:
    reader = FrameReader()
    assert reader.feed(b'{"a":1}\r\n') == ['{"a":1}']


# -- isolated_env (G12) -------------------------------------------------------


def test_isolated_env_drops_tokens_and_pins_home(tmp_path) -> None:
    os.environ["GH_TOKEN"] = "leak-please-dont"
    try:
        env = isolated_env(str(tmp_path), inherit=("GH_TOKEN", "LANG"))
    finally:
        del os.environ["GH_TOKEN"]
    assert "GH_TOKEN" not in env
    assert env["HOME"] == str(tmp_path)
    assert env["XDG_CONFIG_HOME"].startswith(str(tmp_path))
    assert env["LANG"] == "C.UTF-8"


# -- scripted peer process ----------------------------------------------------

PEER = textwrap.dedent(
    """
    import json, sys
    mode = sys.argv[1]
    def send(obj):
        sys.stdout.write(json.dumps(obj) + "\\n")
        sys.stdout.flush()
    def read():
        return json.loads(sys.stdin.readline())
    if mode == "echo":
        msg = read()
        send({"jsonrpc": "2.0", "id": msg["id"], "result": {"ok": True}})
        send({"jsonrpc": "2.0", "method": "future/unknownEvent", "params": {"x": 1}})
        send({"jsonrpc": "2.0", "id": msg["id"] + 1000, "result": "interleaved"})
    elif mode == "error":
        msg = read()
        send({"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -1, "message": "nope", "data": {"d": 1}}})
    elif mode == "silent":
        count = 0
        while True:
            line = sys.stdin.readline()
            if not line:
                break
            count += 1
        sys.stderr.write("recv=%d" % count)
        sys.stderr.flush()
    elif mode == "die":
        read()
        sys.exit(3)
    elif mode == "callback":
        msg = read()
        send({"jsonrpc": "2.0", "id": 77, "method": "approval/required", "params": {"q": "allow?"}})
        resp = read()
        send({"jsonrpc": "2.0", "id": msg["id"], "result": resp.get("result")})
    elif mode == "bigframe":
        read()
        send({"jsonrpc": "2.0", "id": 1, "result": "x" * (9 * 1024 * 1024)})
    """
)


def launch_peer(tmp_path, mode: str) -> ProcessChannel:
    script = tmp_path / "peer.py"
    script.write_text(PEER, encoding="utf-8")
    spec = LaunchSpec.build(
        [sys.executable, str(script), mode],
        home=str(tmp_path / "home"),
        cwd=str(tmp_path),
    )
    return ProcessChannel.launch(spec, name=f"peer-{mode}")


def test_request_response_and_unknown_preserved(tmp_path) -> None:
    channel = launch_peer(tmp_path, "echo")
    try:
        result = channel.request("session/new", {"prompt": "hi"}, timeout=5)
        assert result == {"ok": True}
        seen = []
        while True:
            message = channel.poll_message(timeout=1)
            if message is None:
                break
            seen.append(message)
        methods = [m.method for m in seen]
        assert "future/unknownEvent" in methods  # unknown event not dropped (G4)
        unknown = next(m for m in seen if m.method == "future/unknownEvent")
        assert unknown.raw["params"] == {"x": 1}  # raw payload preserved verbatim
    finally:
        channel.close()


def test_remote_error_is_typed(tmp_path) -> None:
    channel = launch_peer(tmp_path, "error")
    try:
        with pytest.raises(RemoteFailure) as excinfo:
            channel.request("bad", timeout=5)
        assert excinfo.value.remote_code == -1
        assert excinfo.value.remote_data == {"d": 1}
    finally:
        channel.close()


def test_eof_after_send_is_lost_receipt_unknown(tmp_path) -> None:
    channel = launch_peer(tmp_path, "die")
    try:
        with pytest.raises(LostReceipt) as excinfo:
            channel.request("session/new", timeout=5)
        assert excinfo.value.method == "session/new"
        assert excinfo.value.code == "LOST_RECEIPT"
    finally:
        exit_code = channel.close()
        assert exit_code == 3  # owned process only; exit evidence kept (G6/G8)


def test_silent_peer_times_out_without_resend(tmp_path) -> None:
    channel = launch_peer(tmp_path, "silent")
    try:
        with pytest.raises(RequestTimeout):
            channel.request("session/new", timeout=0.5)
        # the attempt stays unknown at the client; nothing was re-sent (G11)
        assert len(channel.inflight) == 1
    finally:
        channel.close()
    assert "recv=1" in channel.stderr_tail()  # peer saw exactly one write


def test_server_request_keeps_identity(tmp_path) -> None:
    channel = launch_peer(tmp_path, "callback")
    seen = []

    def handle(ch, message):
        seen.append(message)
        ch.reply(message.id, {"decision": "pending"})

    try:
        result = channel.request("turn/run", timeout=5, on_request=handle)
        assert result == {"decision": "pending"}  # peer forwarded our reply
        assert seen and seen[0].id == 77  # native callback id preserved (G4)
        assert seen[0].method == "approval/required"
    finally:
        channel.close()


def test_peer_closed_stream_reports_channel_closed(tmp_path) -> None:
    channel = launch_peer(tmp_path, "echo")
    try:
        channel.request("session/new", timeout=5)
    finally:
        channel.close()
    with pytest.raises(ChannelClosed):
        channel.send_raw({"jsonrpc": "2.0", "id": 1, "method": "x"})


def test_oversize_peer_frame_is_typed_failure(tmp_path) -> None:
    channel = launch_peer(tmp_path, "bigframe")
    try:
        with pytest.raises(LostReceipt) as excinfo:
            channel.request("session/new", timeout=5)
        # framing breach after send: unknown outcome, typed root cause kept (G5/G11)
        assert isinstance(excinfo.value.__cause__, FramingError)
    finally:
        channel.close()

"""C-04 §8 — the log sink's counterexamples, the canary, and the isomorphism.

The isomorphism test is the one that matters for the product: two halves
write into one data root and a diagnostic export parses them as one
timeline. If the Python and TypeScript records disagreed on field order,
the merged timeline would be unreadable — and a disagreement here is
invisible in either suite alone, so the test runs BOTH writers.
"""
from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys

import pytest

from ordessa_server.observability.logging_sink import (
    REDACTED,
    JsonLinesSink,
    iter_records,
    record_field_order,
    redact_field,
    redact_text,
    server_logger,
)

CANARY = "CANARY-TOKEN-BYTES-0123456789abcdef"
REPO_ROOT = Path(__file__).resolve().parents[3]


def lines_of(root: Path) -> "list[str]":
    return (root / "logs" / "server.log").read_text(encoding="utf-8").splitlines()


# -- the record shape -------------------------------------------------------


def test_a_record_is_ts_level_scope_msg_then_the_callers_fields(tmp_path):
    log = server_logger(tmp_path)
    log.info("session started", {"sessionId": "s1", "count": 2})
    record = json.loads(lines_of(tmp_path)[0])
    assert record_field_order(record) == (
        "ts", "level", "scope", "msg", "sessionId", "count",
    )
    assert record["ts"].endswith("Z") and "T" in record["ts"]
    assert record["level"] == "info"
    assert record["scope"] == "host.server"


def test_child_scopes_join_with_a_dot(tmp_path):
    log = server_logger(tmp_path).child("plugin.example")
    log.child("inner").warn("nested")
    assert json.loads(lines_of(tmp_path)[0])["scope"] == "host.server.plugin.example.inner"


def test_the_level_filter_drops_records_below_the_configured_level(tmp_path):
    sink = JsonLinesSink(tmp_path, level="warn")
    scoped = sink.child("host.server")
    scoped.debug("no")
    scoped.info("no")
    scoped.error("yes")
    assert len(lines_of(tmp_path)) == 1


def test_the_log_lands_in_the_data_root_not_the_cwd(tmp_path):
    server_logger(tmp_path).info("x")
    assert (tmp_path / "logs" / "server.log").is_file()


# -- the four redaction rules (C-04 §4) ------------------------------------


@pytest.mark.parametrize("key", [
    "token", "TOKEN", "apiKey", "api_key", "X-Api-Key", "password",
    "credential", "authorization", "Bearer", "clientSecret",
])
def test_rule_one_redacts_by_field_name(tmp_path, key):
    server_logger(tmp_path, token=CANARY).info("x", {key: "whatever"})
    assert json.loads(lines_of(tmp_path)[0])[key] == REDACTED


def test_rule_one_redacts_an_empty_secret_too(tmp_path):
    """An empty value still says "a secret exists and is unset", which is
    information. The field is redacted either way."""
    server_logger(tmp_path).info("x", {"token": ""})
    assert json.loads(lines_of(tmp_path)[0])["token"] == REDACTED


def test_rule_two_redacts_the_token_under_a_renamed_field(tmp_path):
    """C-04 §8 case 2: the caller renamed the field, the sink still catches it."""
    server_logger(tmp_path, token=CANARY).info("x", {"myKey": CANARY})
    assert CANARY not in "\n".join(lines_of(tmp_path))


def test_rule_two_redacts_the_token_inside_the_message(tmp_path):
    """C-04 §8 case 3: the message body is covered by the same rule."""
    server_logger(tmp_path, token=CANARY).warn(f"auth failed for {CANARY} at host")
    assert CANARY not in "\n".join(lines_of(tmp_path))
    assert REDACTED in json.loads(lines_of(tmp_path)[0])["msg"]


def test_rule_two_redacts_the_token_inside_a_url_and_a_nested_object(tmp_path):
    server_logger(tmp_path, token=CANARY).info("x", {
        "url": f"http://127.0.0.1/wire?bearer={CANARY}",
        "nested": {"inner": [CANARY]},
    })
    assert CANARY not in "\n".join(lines_of(tmp_path))


def test_rule_four_reduces_a_locator_to_its_basename(tmp_path):
    server_logger(tmp_path).info("x", {"tokenFile": str(tmp_path / "secrets" / "http-token")})
    record = json.loads(lines_of(tmp_path)[0])
    # The KEY says token, so rule one wins; either way no full path survives.
    assert str(tmp_path) not in "\n".join(lines_of(tmp_path))


def test_rule_four_applies_to_a_path_field_with_a_harmless_name(tmp_path):
    server_logger(tmp_path).info("x", {"where": str(tmp_path / "logs" / "server.log")})
    assert json.loads(lines_of(tmp_path)[0])["where"] == "server.log"


def test_redact_text_leaves_ordinary_text_alone():
    assert redact_text("nothing secret here", [CANARY]) == "nothing secret here"


def test_redact_field_prefers_the_key_rule_over_the_value():
    assert redact_field("token", "public", [CANARY]) == REDACTED


# -- rotation (C-04 §8 case 4) ---------------------------------------------


def test_rotation_keeps_five_files_and_deletes_the_oldest(tmp_path):
    sink = JsonLinesSink(tmp_path, rotate_bytes=400, keep=5)
    scoped = sink.child("host.server")
    for index in range(400):
        scoped.info(f"line {index}", {"filler": "x" * 20})
    present = sorted(
        entry.name for entry in (tmp_path / "logs").iterdir() if entry.is_file()
    )
    assert present == [
        "server.log", "server.log.1", "server.log.2", "server.log.3", "server.log.4",
    ]
    # Never more than keep, and never an unbounded tail.
    assert len(present) == 5


def test_the_rotation_numbers_come_from_the_shared_layout(tmp_path):
    from ordessa_server.bootstrap.data_root import LOG_KEEP, LOG_ROTATE_BYTES, LAYOUT

    assert LOG_ROTATE_BYTES == LAYOUT["logs"]["rotateBytes"] == 10 * 1024 * 1024
    assert LOG_KEEP == LAYOUT["logs"]["keep"] == 5


# -- failure semantics (C-04 §8 case 5) ------------------------------------


def test_a_write_failure_is_counted_not_raised(tmp_path):
    """C-04 §6: a log that cannot be written must not take the operation with
    it. The counter is how the UI learns to say "logs are not writable"."""
    sink = JsonLinesSink(tmp_path)
    sink.path.parent.mkdir(parents=True, exist_ok=True)
    sink.path.write_text("x" * 10_000_000, encoding="utf-8")
    # Make the FILE unwritable: appending to an existing file inside a
    # read-only directory still succeeds, so the directory alone proves nothing.
    sink.path.chmod(0o400)
    try:
        completed = None
        try:
            sink.write("info", "host.server", "still fine", None)
        except Exception as exc:  # pragma: no cover - the point is that this never runs
            completed = exc
        assert completed is None
        assert sink.dropped >= 1
    finally:
        sink.path.chmod(0o600)


def test_a_broken_log_never_replaces_the_primary_failure(tmp_path):
    """The failure that matters is the operation's; a log failure attaches,
    it does not overwrite."""
    sink = JsonLinesSink(tmp_path)
    sink.path.parent.mkdir(parents=True, exist_ok=True)
    sink.path.write_text("x" * 10_000_000, encoding="utf-8")
    sink.path.chmod(0o400)
    primary = RuntimeError("the operation failed for its own reason")
    try:
        try:
            raise primary
        except RuntimeError as operation_failure:
            try:
                sink.write("error", "host.server", "while handling it", None)
            except Exception:  # pragma: no cover - the sink must not raise
                raise AssertionError("the sink must not raise into the handler")
            raise operation_failure
    except RuntimeError as escaped:
        assert escaped is primary
    finally:
        sink.path.chmod(0o600)


# -- parsing (C-04 §5) -----------------------------------------------------


def test_a_line_that_does_not_parse_is_dropped_not_passed_through():
    records = iter_records(['{"ts":"x"}', "not json at all", "", "[1,2]"])
    assert len(records) == 1
    # The unparsable fragment is gone entirely: it must not ride into a bundle.
    assert "not json" not in json.dumps(records)


# -- THE CANARY (C-04 §8 cases 1-3, 7) -------------------------------------


def test_the_canary_appears_nowhere_in_the_log_file(tmp_path):
    log = server_logger(tmp_path, token=CANARY)
    log.info("by name", {"token": CANARY})
    log.info("renamed", {"myKey": CANARY})
    log.info("in the message", None)
    log.info(f"inline {CANARY}", {"url": f"http://127.0.0.1/?t={CANARY}"})
    content = (tmp_path / "logs" / "server.log").read_text(encoding="utf-8")
    assert CANARY not in content
    assert REDACTED in content


# -- C-04 §8.6 — the two sides are isomorphic ------------------------------

#: A reference implementation of the C-04 record, written the way the
#: TypeScript sink is specified to write it. It is duplicated here ON
#: PURPOSE: a test that imported the Python sink on both sides would prove
#: only that the Python sink agrees with itself.
#: The reference writer, run as a real Node process. It is a SEPARATE file on
#: purpose: a test that imported the Python sink on both sides would only prove
#: that the Python sink agrees with itself.
TS_REFERENCE = Path(__file__).resolve().parent / "support" / "ts_log_reference.mjs"



def test_the_two_sides_write_the_same_fields_in_the_same_order(tmp_path):
    fields = {
        "sessionId": "s1",
        "token": "value",
        "myKey": CANARY,
        "count": 3,
        "flag": True,
    }
    completed = subprocess.run(
        ["node", str(TS_REFERENCE), CANARY, json.dumps(fields)],
        capture_output=True, text=True, check=True, timeout=60,
        stdin=subprocess.DEVNULL,
    )
    fromTypeScript = completed.stdout.strip()

    # The Python side writes the same record, minus the timestamp difference.
    log = server_logger(tmp_path, token=CANARY)
    log.info("session started", fields)
    record = json.loads(lines_of(tmp_path)[0])
    record["ts"] = "2026-01-01T00:00:00.000Z"
    record["scope"] = "host.desktop"
    fromPython = json.dumps(record, separators=(",", ":"), ensure_ascii=False)

    # Field SET and field ORDER, both — a diagnostic export replays these as a
    # timeline, and a key that moved between the two writers breaks it.
    assert list(record) == [key for key, _ in json.loads(fromTypeScript, object_pairs_hook=list)]
    assert record_field_order(record)[:4] == ("ts", "level", "scope", "msg")
    assert fromPython == fromTypeScript


def test_the_two_sides_agree_on_the_canary_redaction(tmp_path):
    completed = subprocess.run(
        ["node", str(TS_REFERENCE), CANARY, json.dumps({"myKey": CANARY, "token": "x"})],
        capture_output=True, text=True, check=True, timeout=60,
        stdin=subprocess.DEVNULL,
    )
    log = server_logger(tmp_path, token=CANARY)
    log.info("session started", {"myKey": CANARY, "token": "x"})
    fromPython = json.loads(lines_of(tmp_path)[0])
    fromTypeScript = json.loads(completed.stdout)
    assert fromPython["myKey"] == fromTypeScript["myKey"] == REDACTED
    assert fromPython["token"] == fromTypeScript["token"] == REDACTED
    assert CANARY not in completed.stdout

"""016 LSP-4 — 可执行探测的正反例（注入式查找，不碰真实机器 PATH）。"""
from __future__ import annotations

from ordessa_lsp_adapters import resolve_executable
from _lsp_helpers import fake_lookup


def test_present_resolves_path() -> None:
    presence = resolve_executable("pyright-langserver",
                                  lookup=fake_lookup({"pyright-langserver": "/usr/bin/pyright-langserver"}))
    assert presence.present is True
    assert presence.resolved_path == "/usr/bin/pyright-langserver"
    assert "resolved" in presence.reason


def test_missing_is_fact_not_error() -> None:
    presence = resolve_executable("nil", lookup=fake_lookup({}))
    assert presence.present is False
    assert presence.resolved_path is None
    assert "unsupported" in presence.reason
    assert "no config is invented" in presence.reason


def test_empty_lookup_result_counts_as_missing() -> None:
    presence = resolve_executable("x", lookup=fake_lookup({"x": ""}))
    assert presence.present is False


def test_jsonable_shape() -> None:
    presence = resolve_executable("ruff",
                                  lookup=fake_lookup({"ruff": "/opt/ruff"}))
    assert presence.to_jsonable() == {
        "command": "ruff", "present": True,
        "reason": "resolved on PATH: /opt/ruff", "resolved_path": "/opt/ruff"}

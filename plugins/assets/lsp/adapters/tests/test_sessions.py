"""016 LSP-5 — 两会话隔离。"""
from __future__ import annotations

from ordessa_lsp_api import LspSelection
from ordessa_lsp_adapters import SessionProjectionStore
from _lsp_helpers import fake_lookup, pyright_server, ruff_formatter

LOOKUP = fake_lookup({
    "pyright-langserver": "/usr/bin/pyright-langserver",
    "ruff": "/usr/local/bin/ruff",
})


def test_two_sessions_isolated() -> None:
    store = SessionProjectionStore()
    session_a = store.project(
        "sess-a", "pi",
        LspSelection(scope="session", servers=(pyright_server(),)),
        lookup=LOOKUP)
    session_b = store.project(
        "sess-b", "pi",
        LspSelection(scope="session", formatters=(ruff_formatter(),)),
        lookup=LOOKUP)

    assert [d.definition["name"] for d in session_a] == ["pyright"]
    assert [d.definition["name"] for d in session_b] == ["ruff-format"]

    # 重投影 A 不动 B；B 的快照逐字节等于它自己的规范转录
    from ordessa_lsp_adapters import canonical_decision_bytes
    before_b = canonical_decision_bytes(store.snapshot("sess-b"))
    store.project(
        "sess-a", "pi",
        LspSelection(scope="session",
                     servers=(pyright_server(),),
                     formatters=(ruff_formatter(),)),
        lookup=LOOKUP)
    assert canonical_decision_bytes(store.snapshot("sess-b")) == before_b
    assert [d.definition["name"] for d in store.snapshot("sess-a")] == \
        ["pyright", "ruff-format"]

    # 未投影会话 = 空快照（诚实空，不是别人的数据）
    assert store.snapshot("sess-c") == ()


def test_decisions_are_frozen_records() -> None:
    from dataclasses import FrozenInstanceError
    import pytest
    store = SessionProjectionStore()
    decisions = store.project(
        "sess-a", "codex",
        LspSelection(scope="profile", servers=(pyright_server(),)),
        lookup=LOOKUP)
    with pytest.raises(FrozenInstanceError):
        decisions[0].status = "projected"  # type: ignore[misc]

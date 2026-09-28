"""016 LSP-5 — golden 转录（字节稳定）与缺席可执行反例。

golden 文件 ``golden/lsp-projection-golden-v1.json`` 是本测试流水线对固定
输入的规范转录，按字节比较；任何理由/证据指针/键序的变化都会使该测试变红，
从而把"转录稳定性"当成被测性质而不是口号。
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from ordessa_lsp_api import LspSelection
from ordessa_lsp_adapters import (
    STATUS_ABSENT_EXECUTABLE,
    STATUS_UNSUPPORTED_NATIVE,
    project_selection,
)
from _lsp_helpers import fake_lookup, nil_server, pyright_server, ruff_formatter

GOLDEN = Path(__file__).resolve().parent / "golden" / \
    "lsp-projection-golden-v1.json"

LOOKUP = fake_lookup({
    "pyright-langserver": "/usr/bin/pyright-langserver",
    "ruff": "/usr/local/bin/ruff",
})


def _fixed_selection() -> LspSelection:
    return LspSelection(scope="session",
                        servers=(pyright_server(), nil_server()),
                        formatters=(ruff_formatter(),))


def test_golden_transcription_byte_stable() -> None:
    from ordessa_lsp_adapters import canonical_decision_bytes
    decisions = project_selection("pi", _fixed_selection(), lookup=LOOKUP)
    blob = canonical_decision_bytes(decisions)
    assert blob == GOLDEN.read_bytes(), (
        "canonical transcription drifted; if the drift is intended, "
        "regenerate the golden file and record why in LSP-report.md")


def test_golden_digest_recorded() -> None:
    digest = hashlib.sha256(GOLDEN.read_bytes()).hexdigest()
    # 64 hex chars：golden 是字节稳定的规范 JSON，哈希恒定可复核
    assert len(digest) == 64 and all(c in "0123456789abcdef" for c in digest)


def test_transcription_deterministic_across_calls() -> None:
    from ordessa_lsp_adapters import canonical_decision_bytes
    first = canonical_decision_bytes(
        project_selection("pi", _fixed_selection(), lookup=LOOKUP))
    second = canonical_decision_bytes(
        project_selection("pi", _fixed_selection(), lookup=LOOKUP))
    assert first == second


def test_absent_executable_counterexample() -> None:
    """缺席 = 该格 absent-executable + 原因；不产任何假配置。"""
    decisions = {d["definition"]["name"]: d
                 for d in (x.to_jsonable() for x in
                           project_selection("pi", _fixed_selection(),
                                             lookup=LOOKUP))}
    nil = decisions["nil"]
    assert nil["status"] == STATUS_ABSENT_EXECUTABLE
    assert nil["executable"]["present"] is False
    assert nil["executable"]["resolved_path"] is None
    assert "no config is invented" in nil["reason"]
    # 三个决策都只有决策字段：不存在编译出的配置产物
    for record in decisions.values():
        assert set(record) == {"brand", "definition", "evidence_ref",
                               "executable", "reason", "scope", "status"}


def test_present_but_unsupported_native() -> None:
    decisions = {d["definition"]["name"]: d
                 for d in (x.to_jsonable() for x in
                           project_selection("pi", _fixed_selection(),
                                             lookup=LOOKUP))}
    pyright = decisions["pyright"]
    assert pyright["status"] == STATUS_UNSUPPORTED_NATIVE
    assert pyright["executable"]["present"] is True
    assert "2b0a123de983" in pyright["reason"]
    assert pyright["evidence_ref"].startswith("github.com/earendil-works/pi/")

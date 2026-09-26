"""S 组 /tests/server — a-3 (c) 代交两行之钉：P8 组合形（filer 工厂）＋P9 β captured 可分辨。

授权＝`C-notice-S-proxy-two-lines.md`（05:16Z 中央代提交，写域限 runtime 一行/delegation β 一行/本钉文件）。
红-绿双向：两钉在代交前树（b821d85 无两行）＝预期红（ImportError/列缺），代交形＝绿；申报随件。
"""
from __future__ import annotations

from types import SimpleNamespace

from ordessa_server_compat.plugin import _core_filer
from ordessa_server.execution.delegation import DelegationService
from pacthold.work_core import db as core_db
from pacthold.work_core.repository import CoreRepository
from pacthold.work_core.services import ExecutionService, WorkService

import sys
sys.path.insert(0, "tests/server")
from test_a3_k2_filing_s import (  # noqa: E402  复用同域夹具（S 命名域内文件）
    EDITED, canonical, make_stack, rest_accept, row,
)


def test_p8_composed_filer_files_exactly_the_two_core_records(tmp_path):
    """组合形（04:55 会签入口 × runtime flip 同形）：filer 恰产 E 被摘两调用之收据。"""
    core_db.configure_database(tmp_path / "core.db")
    try:
        repo = CoreRepository()
        port = SimpleNamespace(
            work_service=WorkService(repo),
            execution_service=ExecutionService(repo),
            provider=SimpleNamespace(provider_id="harness-sidecar"),
        )
        receipt = _core_filer(port)(turn_id="t-9", session_id="s-9",
                                    execution_key="execution:t-9")
        assert receipt["dispatch_id"] is None  # 派发半边留在端口（批文 K2）
        work = repo.get_work(receipt["work_id"])
        assert work.objective == "AgentBox Session Turn"
        assert work.metadata == {"session_id": "s-9", "turn_id": "t-9"}
        with core_db.get_conn() as conn:
            ex = conn.execute("SELECT * FROM core_executions WHERE id=?",
                              (receipt["core_execution_id"],)).fetchone()
        assert ex is not None and ex["work_id"] == work.id
        assert ex["provider_id"] == "harness-sidecar"
    finally:
        core_db.configure_database(None)


def test_p9_captured_revision_distinguishable_from_later_edit(tmp_path):
    """β（甲案，04:23/05:01 双钉）：子行 captured 值随锚落库，与活行后续编辑可分辨。"""
    h = make_stack(tmp_path)
    parent_turn = rest_accept(h)
    child_session = h["sessions"].create_session("s-child", {
        "workspace_id": h["wid"], "profile_id": h["pid"]})[1]
    delegation = DelegationService(records=h["records"], profiles=h["profiles"],
                                   sessions=h["sessions"], objects=h["objects"])
    child_row = h["profiles"].get(h["pid"])
    captured_at = int(child_row["config_revision"])
    child_turn = delegation._create_child_turn(
        session_id=child_session["session_id"], child_profile=child_row,
        parent_turn_id=parent_turn, prompt="p", model=None)
    got = row(h, child_turn, "captured_profile_revision")["captured_profile_revision"]
    assert got == captured_at, "子行必须落锚时 captured 值（甲案）"
    # 活行后续编辑（bump revision）不改已落账的 captured 值——两值可分辨。
    edited = h["objects"].publish(canonical(EDITED)).digest
    live = h["profiles"].get(h["pid"])
    h["profiles"].update_configuration(
        profile_id=h["pid"], expected_version=int(live["version"]),
        config_digest=edited, key="cfg-b", request_digest="cfg-b",
    )
    after = row(h, child_turn, "captured_profile_revision")["captured_profile_revision"]
    live_after = int(h["profiles"].get(h["pid"])["config_revision"])
    assert after == captured_at and live_after != captured_at, (
        "captured≡历史事实、活行可再进——可分辨性即 β 的公开语义")

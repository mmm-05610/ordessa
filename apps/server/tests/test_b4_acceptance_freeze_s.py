"""S 组 /tests/server — INC1b b-4：直建受理路径「受理时冻结输入」钉（O-B3-1 单生产者）。

批准依据：`approvals/INC1b-release.md` + `decisions/INC1b-b4-confluence-interface.md` §1
（采 D2＋「同一次读」硬绑定）；INC1c 依据 `approvals/INC1c-release.md` s-c1/s-c2。
翻转记账（显式，非静默）：本文件 F1/F2 面替代原 git-外表征钉
`test_block3_freeze_gap_characterization_s.py` 的 T2——同一断言面由「表征现状 bug」收紧为
「断言修复后行为」，方向=收紧、非弱化；T1（队列对照）语义不变更。
INC1c s-c1 再翻转：F5 由「COALESCE 回退保留」翻为「历史 NULL 行暴露原始 NULL」（同方向=收紧）。
a-3 K3' 记账（显式，非静默）：受理冻结件在原有形状上**加性**携带 `permissions` 节
（受理时一次算定的 posture），F1/F4 的期望 digest 随之重算=收紧面扩大（digest 值变、
不透明引用语义不变、公开 wire 零动）；profile 活值列与此节无涉（:133 保持裸 CONFIG）。

- F1 冻结非活行：受理后编辑 Profile，`get_turn_context` 原始键
  `effective_config_object_digest` 恒=受理时冻结件（修前红=直建行该列 NULL）。
- F2 冻结行读取：s-c1 后 coalesced 键 `config_object_digest` 即原始冻结值本身（无回退）。
- F3 replay 不重冻：同键重放幂等先行，零 publish、零重派。
- F4 N1 强制交错（直建入口）：冻结计算与受理事务之间落一次配置编辑提交
  ⇒ PROFILE_REVISION_CONFLICT(409)、零 turn 行（锚不被绕、无漂移中间态）。
- F5 legacy（s-c1 翻转后）：既有 effective=NULL 行读侧暴露**原始 NULL**，不再活行回退；
  活值仅经显式别名 `profile_config_object_digest` 可读（删回退不损失信息）。
"""
from __future__ import annotations

import json
import threading

import pytest

from ordessa_server.credentials import CredentialRecords
from ordessa_server.errors import ServerError
from ordessa_server.execution import HarnessDescriptor, HarnessRegistry
from ordessa_server.idempotency import IdempotentRecords
from ordessa_server.persistence import ProductRepositoryView
from ordessa_server.profiles import ProfileRecords
from ordessa_server.profiles.permissions import resolve_all
from ordessa_server_compat.sessions import SessionRecords, SessionService
from pacthold.storage import Database, ObjectStore
from ordessa_server.workspaces import WorkspaceRecords

CONFIG_BEFORE = {"schema_version": 1, "harness_type": "alpha",
                 "configuration": {"model": "before"}}
CONFIG_AFTER = {"schema_version": 1, "harness_type": "alpha",
                "configuration": {"model": "after"}}


class RecordingPort:
    def __init__(self) -> None:
        self.accepted: list[str] = []

    def accept(self, turn_id) -> None:
        self.accepted.append(turn_id)


def canonical(value: dict) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode()


#: a-3 K3': the acceptance freeze now carries the once-resolved posture section
#: (fixture profiles are created without permission edits -> default preset,
#: empty rules), so the effective digest recomputation must mirror it exactly.
DEFAULT_POSTURE = resolve_all([], preset="default")


def frozen_effective(config: dict) -> bytes:
    return canonical({**config, "permissions": DEFAULT_POSTURE})


def alpha_registry() -> HarnessRegistry:
    registry = HarnessRegistry()
    registry.register(HarnessDescriptor(
        "alpha", credential_kind=None,
        configuration_validator=lambda value: None if isinstance(value, dict) else ValueError(),
        capability_claims={"stream": True},
    ))
    return registry


def make_stack(tmp_path, port):
    database = Database(tmp_path / "data")
    database.initialize()
    idempotency = IdempotentRecords(database)
    credentials = CredentialRecords(database)
    profiles = ProfileRecords(database, idempotency)
    records = SessionRecords(database, idempotency)
    workspaces = WorkspaceRecords(database, idempotency)
    objects = ObjectStore(tmp_path / "data")
    sessions = SessionService(
        records, idempotency, objects, harnesses=alpha_registry(),
        profiles=profiles, credentials=credentials, execution=port,
    )
    return database, profiles, sessions, records, objects, workspaces


def accept_one_turn(tmp_path, *, publish_calls=None):
    """装配+受理一枚直建 turn；返回句柄字典。"""
    port = RecordingPort()
    database, profiles, sessions, records, objects, workspaces = make_stack(tmp_path, port)
    before_digest = objects.publish(canonical(CONFIG_BEFORE)).digest
    profile = profiles.create(
        key="p", request_digest="p", name="role", harness_type="alpha",
        config_digest=before_digest, credential_id=None,
    )[1]
    workspace = workspaces.create(
        key="w", request_digest="w", distribution="Ubuntu", remote_user="tester",
        remote_path="/w", connection_id="c",
    )[1]
    session = sessions.create_session("s", {
        "workspace_id": workspace["workspace_id"],
        "profile_id": profile["profile_id"],
    })[1]
    if publish_calls is not None:
        original = objects.publish

        def counting(value):
            publish_calls.append(len(value))
            return original(value)

        objects.publish = counting
    _, turn = sessions.create_turn(session["session_id"], "turn-key",
                                   {"text": "hi", "expected_profile_revision": 1})
    frozen = objects.publish(frozen_effective(CONFIG_BEFORE)).digest
    return {"port": port, "profiles": profiles, "sessions": sessions,
            "records": records, "objects": objects, "pid": profile["profile_id"],
            "sid": session["session_id"], "turn_id": turn["turn_id"], "frozen": frozen}


def edit_profile(profiles, profile_id, objects, value) -> None:
    row = profiles.get(profile_id)
    digest = objects.publish(canonical(value)).digest
    profiles.update_configuration(
        profile_id=profile_id, expected_version=int(row["version"]),
        config_digest=digest, key="cfg-1", request_digest="cfg-1",
    )


def test_f1_f2_direct_turn_freezes_effective_config_against_later_edit(tmp_path):
    h = accept_one_turn(tmp_path)
    ctx0 = h["records"].get_turn_context(h["turn_id"])
    assert ctx0["effective_config_object_digest"] == h["frozen"], (
        "b-4：直建行必须落受理时冻结 digest（修前此列 NULL=V2 漂移根）")
    edit_profile(h["profiles"], h["pid"], h["objects"], CONFIG_AFTER)
    ctx = h["records"].get_turn_context(h["turn_id"])
    assert ctx["effective_config_object_digest"] == h["frozen"], (
        "受理后编辑不得改变已冻结的 effective 引用")
    assert json.loads(h["objects"].read(ctx["effective_config_object_digest"])) == {
        **CONFIG_BEFORE, "permissions": DEFAULT_POSTURE}
    assert ctx["config_object_digest"] == h["frozen"], (
        "COALESCE 在冻结非空行上取 t.effective_*，与 p.config_object_digest 活值脱钩")


def test_f3_replay_never_refreezes_or_redispatches(tmp_path):
    calls: list[int] = []
    h = accept_one_turn(tmp_path, publish_calls=calls)
    baseline = len(calls)
    replay = h["sessions"].create_turn(h["sid"], "turn-key",
                                       {"text": "hi", "expected_profile_revision": 1})
    assert replay[1]["turn_id"] == h["turn_id"]
    assert replay[1]["state"] == "accepted"
    assert len(calls) == baseline, "重放分支必须幂等先行：零 publish（不重冻结）"
    assert h["port"].accepted == [h["turn_id"]], "重放不得二次派发"


def test_f4_n1_forced_interleave_edit_between_freeze_and_tx_is_409(tmp_path):
    port = RecordingPort()
    database, profiles, sessions, records, objects, workspaces = make_stack(tmp_path, port)
    before_digest = objects.publish(canonical(CONFIG_BEFORE)).digest
    profile = profiles.create(
        key="p", request_digest="p", name="role", harness_type="alpha",
        config_digest=before_digest, credential_id=None,
    )[1]
    workspace = workspaces.create(
        key="w", request_digest="w", distribution="Ubuntu", remote_user="tester",
        remote_path="/w", connection_id="c",
    )[1]
    session = sessions.create_session("s", {
        "workspace_id": workspace["workspace_id"],
        "profile_id": profile["profile_id"],
    })[1]
    sid = session["session_id"]

    frozen_done = threading.Event()
    edit_done = threading.Event()
    original = records.create_turn

    def gated(**kwargs):
        # 服务层冻结计算已完成；在受理事务开始前，强制让编辑腿提交。
        frozen_done.set()
        assert edit_done.wait(5), "编辑腿未落窗"
        return original(**kwargs)

    records.create_turn = gated

    def editor():
        assert frozen_done.wait(5)
        edit_profile(profiles, profile["profile_id"], objects, CONFIG_AFTER)
        edit_done.set()

    thread = threading.Thread(target=editor)
    thread.start()
    with pytest.raises(ServerError) as caught:
        sessions.create_turn(sid, "turn-key",
                             {"text": "hi", "expected_profile_revision": 1})
    thread.join()
    records.create_turn = original
    assert caught.value.code == "PROFILE_REVISION_CONFLICT"
    assert caught.value.status == 409
    with database.read() as conn:
        rows = conn.execute(
            "SELECT COUNT(*) AS n FROM server_turns WHERE session_id=?", (sid,)).fetchone()
    assert int(rows["n"]) == 0, "交错窗内的编辑必须被同读锚拒掉，不留漂移行"
    # 锚定后恢复正常受理：编辑后的 revision 可正常冻结新值。
    revision = int(profiles.get(profile["profile_id"])["config_revision"])
    _, turn = sessions.create_turn(sid, "turn-key-2",
                                   {"text": "hi", "expected_profile_revision": revision})
    ctx = records.get_turn_context(turn["turn_id"])
    assert ctx["effective_config_object_digest"] == objects.publish(
        frozen_effective(CONFIG_AFTER)).digest


def test_f5_legacy_null_row_exposes_raw_null_after_s_c1(tmp_path):
    """INC1c s-c1 翻转钉（显式收紧记账）：legacy effective=NULL 行读侧暴露**原始 NULL**，
    不再活行回退。旧语义（COALESCE 回退）下本钉红、新语义下绿——方向=收紧、非弱化；
    accept 侧维持 β2 的 typed 拒绝（历史 NULL 行永不被执行，E 域现行为）。"""
    port = RecordingPort()
    database, profiles, sessions, records, objects, workspaces = make_stack(tmp_path, port)
    before_digest = objects.publish(canonical(CONFIG_BEFORE)).digest
    profile = profiles.create(
        key="p", request_digest="p", name="role", harness_type="alpha",
        config_digest=before_digest, credential_id=None,
    )[1]
    workspace = workspaces.create(
        key="w", request_digest="w", distribution="Ubuntu", remote_user="tester",
        remote_path="/w", connection_id="c",
    )[1]
    session = sessions.create_session("s", {
        "workspace_id": workspace["workspace_id"],
        "profile_id": profile["profile_id"],
    })[1]
    with database.transaction() as conn:
        conn.execute(
            "INSERT INTO server_turns(id,session_id,profile_id,profile_revision,"
            "native_generation,state,capture_state,cleanup_state,input_object_digest,"
            "created_at,updated_at) VALUES ('legacy-turn',?,?,'0',1,'accepted','pending',"
            "'pending','digest-in','2026-01-01T00:00:00+00:00','2026-01-01T00:00:00+00:00')",
            (session["session_id"], profile["profile_id"]),
        )
    ctx = records.get_turn_context("legacy-turn")
    assert ctx["effective_config_object_digest"] is None
    assert ctx["config_object_digest"] is None, (
        "s-c1：读回退已删，历史 NULL 行暴露原始 NULL（不静默改用当前配置）")
    assert ctx["profile_config_object_digest"] == profiles.get(
        profile["profile_id"])["config_object_digest"], (
        "活值仍可经显式别名 profile_config_object_digest 读到（回退删除不损失信息）")

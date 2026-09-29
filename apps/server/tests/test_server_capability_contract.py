"""服务端中立能力合同：校验、合并规则、有效能力门控（能力阶段 A 的定向证据）。

覆盖：canonical 校验（未知 id / 漂移别名 / 非真 bool）、合并规则逐条、supported⇒declared
不变式、observed 不回写静态声明、注册表 canonical 视图、部署座位严格校验、ACP 与 native
driver 的等价投影、checkpoint resumable / 附件 / 审批从有效能力读取，以及 Profile 能力来源。
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import queue
import shutil

import pytest

from pacthold_runtime_compat.resource_contracts import harness_capabilities as caps
from ordessa_server.bootstrap import build_runtime
from ordessa_server_compat.composition import build_runtime_from_sidecar_deployment
from ordessa_server_compat.execution import HarnessDescriptor, HarnessRegistry
from ordessa_server_compat.execution.sidecar import LocalProcessLauncher, SidecarError, SidecarHarnessPort
from ordessa_server_compat.execution.sidecar_backend import (
    _effective_attachment_support, _sidecar_attachments,
)
from ordessa_server_compat.profiles import ProfileRecords, ProfileService
from ordessa_server.credentials import CredentialRecords
from ordessa_server.idempotency import IdempotentRecords
from pacthold_runtime_compat.storage import Database, ObjectStore


REPO = Path(__file__).resolve().parents[3]
PLUGIN = REPO / "plugins"  / "harness"
SIDECAR_ENTRY = PLUGIN / "runtime" / "native-driver.mjs"  # worker-entry.mjs 随退役旧链移除
FAKE_PEER = PLUGIN / "tests" / "harness_remote" / "fake_acp_peer.mjs"
FIXTURE_DRIVER = Path(__file__).resolve().parent / "fixtures" / "fixture_native_driver.mjs"
DRIVER_BUNDLE_PATH = "agentbox-sidecar/deployment/fixture-native/driver.mjs"

#: 两条传输都用同一份静态上限：比较的是投影，不是谁声明得多。
EQUIVALENT_DECLARED = {
    "start": True, "observe": True, "finish": True, "stream": True,
    "attach": True, "native_continuation": True,
}
COMPARED_FIELDS = ("id", "scope", "declared", "observed", "supported", "reason")


# --------------------------------------------------------------------------
# canonical 合同与严格校验
# --------------------------------------------------------------------------

def test_capability_vocabulary_is_versioned_and_scoped():
    assert caps.CAPABILITY_SCHEMA_VERSION == 1
    assert caps.CANONICAL_CAPABILITY_IDS == (
        "start", "observe", "finish", "attach", "steer", "stream", "permissions",
        "native_continuation",
    )
    assert set(caps.CAPABILITY_SCOPES) == set(caps.CANONICAL_CAPABILITY_IDS)
    assert caps.IMPLEMENTATION_LEVEL_CAPABILITIES | caps.SEMANTIC_CAPABILITIES == set(
        caps.CANONICAL_CAPABILITY_IDS)
    assert not caps.IMPLEMENTATION_LEVEL_CAPABILITIES & caps.SEMANTIC_CAPABILITIES


@pytest.mark.parametrize("drifted,canonical", [
    ("streaming", "stream"), ("approvals", "permissions"), ("approval", "permissions"),
    ("attachments", "attach"), ("sessions", "native_continuation"), ("resume", "native_continuation"),
    ("prompt", "start"), ("abort", "finish"),
])
def test_unknown_capability_ids_and_drift_aliases_are_typed_errors(drifted, canonical):
    with pytest.raises(caps.CapabilityUnknownId) as refused:
        caps.validate_claims({drifted: True})
    assert refused.value.code == caps.CAPABILITY_UNKNOWN_ID
    # 别名只用来把错误说清楚：真正该写的是 canonical id。
    assert canonical in str(refused.value)
    with pytest.raises(caps.CapabilityUnknownId):
        caps.validate_claims({"teleport": True})


@pytest.mark.parametrize("value", ["yes", "true", 1, 0, None, [], {}, "false"])
def test_capability_values_must_be_real_booleans(value):
    with pytest.raises(caps.CapabilityValueNotBoolean) as refused:
        caps.validate_claims({"stream": value})
    assert refused.value.code == caps.CAPABILITY_VALUE_NOT_BOOLEAN


@pytest.mark.parametrize("claims", [None, [], ["stream"], "stream", 7])
def test_claim_shapes_that_are_not_mappings_are_rejected(claims):
    with pytest.raises(caps.CapabilityClaimsInvalid) as refused:
        caps.validate_claims(claims)
    assert refused.value.code == caps.CAPABILITY_CLAIMS_INVALID


def test_canonical_capabilities_returns_a_validated_canonical_snapshot():
    validated = caps.canonical_capabilities({"native_continuation": True, "stream": False})
    assert validated == {"stream": False, "native_continuation": True}
    assert list(validated) == ["stream", "native_continuation"]  # canonical 次序
    assert caps.CapabilityDeclarationError in caps.CapabilityUnknownId.__mro__
    assert issubclass(caps.CapabilityUnknownId, ValueError)


# --------------------------------------------------------------------------
# 合并规则：逐条 + 不变式
# --------------------------------------------------------------------------

@pytest.mark.parametrize("declared,observed,capability_id,supported,reason", [
    # true / true → 支持
    ({"stream": True}, {"stream": True}, "stream", True, None),
    # true / false → 原生明确否掉
    ({"stream": True}, {"stream": False}, "stream", False,
     caps.CAPABILITY_OBSERVED_UNSUPPORTED),
    # true / 未观测 → 一律不支持（实现级也一样：分类只说明证据从哪来，不代替观测）
    ({"stream": True}, {}, "stream", False, caps.CAPABILITY_NOT_OBSERVED),
    ({"native_continuation": True}, {}, "native_continuation", False,
     caps.CAPABILITY_NOT_OBSERVED),
    # false / true → fail closed，不得抬高产品能力
    ({"native_continuation": False}, {"native_continuation": True}, "native_continuation",
     False, caps.CAPABILITY_CONFLICT_OBSERVED_WITHOUT_DECLARATION),
    # 未声明 / 未观测 → 未声明
    ({}, {}, "attach", False, caps.CAPABILITY_NOT_DECLARED),
    # 未声明 / false → 未声明
    ({}, {"attach": False}, "attach", False, caps.CAPABILITY_NOT_DECLARED),
])
def test_merge_rules_are_applied_item_for_item(
    declared, observed, capability_id, supported, reason,
):
    by_id = {item.id: item for item in caps.merge_capabilities(declared, observed)}
    entry = by_id[capability_id]
    assert entry.supported is supported
    assert entry.reason == reason
    assert entry.declared is bool(declared.get(capability_id, False))


def test_merge_produces_every_canonical_id_and_keeps_supported_implies_declared():
    declarations = caps.merge_capabilities(
        {"start": True, "attach": True}, {"start": True, "attach": True},
    )
    assert tuple(item.id for item in declarations) == caps.CANONICAL_CAPABILITY_IDS
    for item in declarations:
        assert item.supported <= item.declared, item
        # 唯一规则：supported == declared and observed is True
        assert item.supported is (item.declared is True and item.observed is True), item
        assert item.scope == caps.CAPABILITY_SCOPES[item.id]
        if not item.declared:
            assert item.supported is False


def test_observed_never_rewrites_the_static_declaration():
    declared = {"native_continuation": True, "attach": False}
    snapshot = dict(declared)
    caps.merge_capabilities(declared, {"native_continuation": True, "attach": True})
    assert declared == snapshot, "观测不得回写静态声明"
    view = caps.capability_view("fixture", caps.merge_capabilities(declared, {"attach": True}))
    by_id = {item["id"]: item for item in view["capabilities"]}
    assert by_id["attach"]["declared"] is False
    assert by_id["attach"]["observed"] is True
    assert by_id["attach"]["supported"] is False


def test_native_evidence_is_only_reported_with_an_observation():
    declarations = {item.id: item for item in caps.merge_capabilities(
        {"start": True, "attach": True}, {"attach": True},
        evidence={"start": "sidecar.operation.start", "attach": "promptCapabilities.image"},
    )}
    assert declarations["attach"].native_evidence == "promptCapabilities.image"
    # start 没有观测 → 不编造观测来源
    assert declarations["start"].observed is None
    assert declarations["start"].native_evidence is None


# --------------------------------------------------------------------------
# 注册表 / 描述符 / 部署座位
# --------------------------------------------------------------------------

def test_descriptor_validates_claims_at_construction_and_registry_exposes_canonical_views():
    with pytest.raises(caps.CapabilityUnknownId):
        HarnessDescriptor("drifted", capability_claims={"streaming": True})
    with pytest.raises(caps.CapabilityValueNotBoolean):
        HarnessDescriptor("loose", capability_claims={"stream": "yes"})

    registry = HarnessRegistry()
    registry.register(HarnessDescriptor("alpha", capability_claims={"stream": True}))
    # claims_for 保持既有返回形状（canonical id → 声明）
    assert registry.claims_for("alpha") == {"stream": True}
    assert registry.claims_for("missing") == {}
    assert registry.canonical_claims("alpha") == {"stream": True}
    by_id = {item["id"]: item for item in registry.capability_view("alpha")["capabilities"]}
    assert set(by_id) == set(caps.CANONICAL_CAPABILITY_IDS)
    # 静态视图只报 declared 候选：没有运行观测，任何能力都不得报 supported
    assert by_id["stream"]["declared"] is True
    assert by_id["stream"]["observed"] is None
    assert by_id["stream"]["supported"] is False
    assert by_id["stream"]["reason"] == caps.CAPABILITY_NOT_OBSERVED
    # 语义级能力同样不会因为被声明就变成 supported
    assert by_id["native_continuation"]["reason"] == caps.CAPABILITY_NOT_DECLARED
    declarations = registry.capability_declarations("alpha")
    assert tuple(item.id for item in declarations) == caps.CANONICAL_CAPABILITY_IDS
    assert registry.capability_declarations("missing") == ()


def _deployment_record(tmp_path: Path, claims) -> Path:
    deployment = tmp_path / "sidecar-deployment.json"
    deployment.write_text(json.dumps({
        "schemaVersion": 1,
        "harnesses": [{
            "id": "fixture", "capabilityClaims": claims,
            "adapter": {"command": "/usr/bin/node", "args": []},
        }],
    }), encoding="utf-8")
    return deployment


@pytest.mark.parametrize("claims", [
    {"streaming": True}, {"approvals": False}, {"attachments": True}, {"sessions": True},
    {"teleport": True},
])
def test_deployment_seat_rejects_drifted_or_unknown_capability_ids(tmp_path, claims):
    if not (PLUGIN / "runtime").is_dir():
        pytest.skip("harness plugin runtime is unavailable")
    with pytest.raises(RuntimeError) as refused:
        build_runtime_from_sidecar_deployment(
            tmp_path / "server", _deployment_record(tmp_path, claims), plugin_root=PLUGIN,
        )
    assert refused.value.args[0].startswith("SIDECAR_DEPLOYMENT_INVALID")
    assert "CAPABILITY" in str(refused.value)


@pytest.mark.parametrize("claims", [
    {"stream": "yes"}, {"stream": 1}, {"stream": None}, {"stream": []}, {"stream": {}},
])
def test_deployment_seat_rejects_non_boolean_capability_values(tmp_path, claims):
    if not (PLUGIN / "runtime").is_dir():
        pytest.skip("harness plugin runtime is unavailable")
    with pytest.raises(RuntimeError) as refused:
        build_runtime_from_sidecar_deployment(
            tmp_path / "server", _deployment_record(tmp_path, claims), plugin_root=PLUGIN,
        )
    assert "CAPABILITY_VALUE_NOT_BOOLEAN" in str(refused.value)


def test_deployment_seat_accepts_the_canonical_spelling(tmp_path, monkeypatch):
    if not (PLUGIN / "runtime").is_dir():
        pytest.skip("harness plugin runtime is unavailable")
    # T014-S2b: the built-in connector builder now lives in the workspace
    # plugin; this stub patches its owning module.
    import ordessa_workspace.connectors as runtime_module

    # 只在 Linux 上跑装配：连接器只是占位，能力声明才是这条断言的证据。
    monkeypatch.setattr(runtime_module, "_builtin_connector", lambda _instance_id: object())
    runtime = build_runtime_from_sidecar_deployment(
        tmp_path / "server",
        _deployment_record(tmp_path, {"start": True, "stream": False, "native_continuation": True}),
        plugin_root=PLUGIN,
    )
    try:
        descriptor = runtime.plugin_host.provided_port('harness.directory').get("fixture")
        assert dict(descriptor.capability_claims) == {
            "start": True, "stream": False, "native_continuation": True,
        }
    finally:
        runtime.stop()


# --------------------------------------------------------------------------
# 端口：有效能力视图（脚本化 sidecar 通道，无需 node）
# --------------------------------------------------------------------------

class _ScriptedChannels:
    """A sidecar substitute: answers envelope ops and replays scripted events."""

    def __init__(self, *, start_result, events=(), prompt_result=None) -> None:
        self.start_result = dict(start_result)
        self.events = list(events)
        self.prompt_result = prompt_result or {"done": True}
        self.requests: list[dict] = []
        self._lines: queue.Queue = queue.Queue()

    def write_line(self, value: str) -> None:
        request = json.loads(value)
        self.requests.append(request)
        op = request.get("op")
        if op == "register":
            result = {"provenance": {"commit": "fixture"}}
        elif op == "start":
            result = self.start_result
        elif op in {"create", "open"}:
            result = {"sessionId": "native-fixture"}
        elif op == "prompt":
            for event in self.events:
                self._lines.put(json.dumps(event) + "\n")
            result = self.prompt_result
        elif op == "close":
            result = {"closed": True}
        elif op == "abort":
            result = {"aborted": True}
        else:
            result = {}
        self._lines.put(json.dumps({"id": request["id"], "ok": True, "result": result}) + "\n")

    def iter_chunks(self):
        while True:
            item = self._lines.get()
            if item is None:
                return
            yield item

    def close(self) -> None:
        self._lines.put(None)


class _ScriptedLauncher:
    def __init__(self, channels: _ScriptedChannels) -> None:
        self.channels = channels

    def launch(self, _environment):
        return self.channels


def _port(channels: _ScriptedChannels, **kwargs) -> SidecarHarnessPort:
    kwargs.setdefault("declared_capabilities", dict(EQUIVALENT_DECLARED))
    return SidecarHarnessPort(
        _ScriptedLauncher(channels), environment={"AGENTBOX_SIDECAR_ISOLATED": "1"},
        profile="fixture", **kwargs,
    )


def _entry(view: dict, capability_id: str) -> dict:
    return next(item for item in view["capabilities"] if item["id"] == capability_id)


def test_acp_resume_object_is_observed_and_makes_checkpoints_resumable():
    channels = _ScriptedChannels(start_result={"sessionCapabilities": {"resume": {}}})
    port = _port(channels)
    try:
        port.open_execution("execution-resume")
        entry = _entry(port.effective_capabilities("execution-resume"), "native_continuation")
        assert entry["declared"] is True and entry["observed"] is True
        assert entry["supported"] is True
        assert entry["nativeEvidence"] == "sessionCapabilities.resume"
        assert port.capture_execution("execution-resume")[1] is True
    finally:
        port.stop()


def test_explicit_resume_false_is_observed_unsupported():
    channels = _ScriptedChannels(start_result={"sessionCapabilities": {"resume": False}})
    port = _port(channels)
    try:
        port.open_execution("execution-no-resume")
        entry = _entry(port.effective_capabilities("execution-no-resume"), "native_continuation")
        assert entry["observed"] is False
        assert entry["supported"] is False
        assert entry["reason"] == caps.CAPABILITY_OBSERVED_UNSUPPORTED
        assert port.capture_execution("execution-no-resume")[1] is False
    finally:
        port.stop()


def test_declared_resume_without_native_advertisement_is_not_observed():
    channels = _ScriptedChannels(start_result={"sessionCapabilities": {}})
    port = _port(channels)
    try:
        port.open_execution("execution-silent")
        entry = _entry(port.effective_capabilities("execution-silent"), "native_continuation")
        assert entry["declared"] is True and entry["observed"] is None
        assert entry["supported"] is False
        assert entry["reason"] == caps.CAPABILITY_NOT_OBSERVED
        # checkpoint 也必须诚实：没有原生播发就不是 resumable。
        assert port.capture_execution("execution-silent")[1] is False
    finally:
        port.stop()


def test_native_resume_claim_without_static_declaration_fails_closed():
    channels = _ScriptedChannels(start_result={"sessionCapabilities": {"resume": {}}})
    port = _port(channels, declared_capabilities={"stream": True})
    try:
        port.open_execution("execution-conflict")
        entry = _entry(port.effective_capabilities("execution-conflict"), "native_continuation")
        assert entry["declared"] is False and entry["observed"] is True
        assert entry["supported"] is False
        assert entry["reason"] == caps.CAPABILITY_CONFLICT_OBSERVED_WITHOUT_DECLARATION
        assert port.capture_execution("execution-conflict")[1] is False
        # 静态声明没有被运行时观测改写
        assert port.declared_capabilities == {"stream": True}
    finally:
        port.stop()


def test_attachment_dispatch_is_refused_before_the_prompt_when_attach_is_not_effective():
    channels = _ScriptedChannels(start_result={"promptCapabilities": {}})
    port = _port(channels, declared_capabilities={"start": True})
    try:
        port.open_execution("execution-upload")
        assert _entry(port.effective_capabilities("execution-upload"), "attach")["supported"] is False
        with pytest.raises(SidecarError) as refused:
            port.prompt("execution-upload", "with a picture", [{"mime": "image/png", "data": "x"}])
        assert refused.value.code == "ATTACHMENT_UNSUPPORTED"
        assert not [item for item in channels.requests if item.get("op") == "prompt"], (
            "被拒绝的附件绝不能变成一次没有附件的派发")
    finally:
        port.stop()


def test_attachment_dispatch_is_allowed_when_declared_and_natively_advertised():
    channels = _ScriptedChannels(start_result={"promptCapabilities": {"image": True}})
    port = _port(channels, declared_capabilities={"start": True, "attach": True})
    try:
        port.open_execution("execution-upload-ok")
        entry = _entry(port.effective_capabilities("execution-upload-ok"), "attach")
        assert entry["observed"] is True and entry["supported"] is True
        assert entry["nativeEvidence"] == "promptCapabilities.image"
        port.prompt("execution-upload-ok", "with a picture", [{"mime": "image/png", "data": "x"}])
        prompt = next(item for item in channels.requests if item.get("op") == "prompt")
        assert prompt["attachments"] == [{"mime": "image/png", "data": "x"}]
    finally:
        port.stop()


def test_undeclared_permissions_stay_unsupported_while_the_request_stays_visible():
    events = [{"event": "permission_request", "data": {"requestId": "req-1", "options": []}}]
    observed: list[tuple[str, str, dict]] = []
    channels = _ScriptedChannels(start_result={}, events=events)
    port = _port(
        channels, declared_capabilities={"start": True, "stream": True},
        on_event=lambda execution_id, kind, payload: observed.append((execution_id, kind, payload)),
    )
    try:
        port.open_execution("execution-approval")
        port.prompt("execution-approval", "needs permission")
        entry = _entry(port.effective_capabilities("execution-approval"), "permissions")
        assert entry["declared"] is False and entry["observed"] is None
        assert entry["supported"] is False
        # 原生请求仍然如实上报，不假装支持也不吞掉事实。
        assert any(kind == "approval.requested" for _execution, kind, _payload in observed)
    finally:
        port.stop()


def test_declared_permissions_with_a_real_round_trip_are_observed():
    events = [{"event": "permission_request", "data": {"requestId": "req-2", "options": []}}]
    channels = _ScriptedChannels(start_result={}, events=events)
    port = _port(channels, declared_capabilities={"start": True, "permissions": True})
    try:
        port.open_execution("execution-approval-ok")
        port.prompt("execution-approval-ok", "needs permission")
        entry = _entry(port.effective_capabilities("execution-approval-ok"), "permissions")
        assert entry["observed"] is True and entry["supported"] is True
        assert entry["nativeEvidence"] == "sidecar.operation.permission_request"
    finally:
        port.stop()


def test_stream_and_finish_are_observed_from_the_real_operations():
    channels = _ScriptedChannels(
        start_result={},
        events=[{"event": "message_delta", "data": {"text": "hello"}}],
    )
    port = _port(channels)
    try:
        port.open_execution("execution-stream")
        before = _entry(port.effective_capabilities("execution-stream"), "stream")
        assert before["observed"] is None  # 还没有任何增量
        port.prompt("execution-stream", "talk")
        view = port.effective_capabilities("execution-stream")
        stream, finish = _entry(view, "stream"), _entry(view, "finish")
        assert stream["observed"] is True and stream["supported"] is True
        assert stream["nativeEvidence"] == "sidecar.event.message.delta"
        assert finish["observed"] is True and finish["supported"] is True
        assert finish["nativeEvidence"] == "sidecar.operation.prompt"
    finally:
        port.stop()


class _ReplayingChannels(_ScriptedChannels):
    """A scripted sidecar that answers a session open by replaying history.

    Pi's `session/load` is exactly this: reopening a stored Session re-emits the
    whole conversation through the same notification channel as live output.
    """

    def __init__(self, *, start_result, replay_events=(), prompt_events=()) -> None:
        super().__init__(start_result=start_result, events=prompt_events)
        self.replay_events = list(replay_events)

    def write_line(self, value: str) -> None:
        request = json.loads(value)
        if request.get("op") in {"create", "open"} and self.replay_events:
            for event in self.replay_events:
                self._lines.put(json.dumps(event) + "\n")
        super().write_line(value)


def _chunk(text: str) -> dict:
    return {"event": "acp_notification", "data": {"params": {
        "sessionId": "native-fixture",
        "update": {"sessionUpdate": "agent_message_chunk", "content": {"type": "text", "text": text}},
    }}}


def test_history_replayed_before_the_prompt_is_not_this_turns_answer():
    """A reopened Session's replay is history; only output after the prompt is
    the answer. Mixing them made every reply repeat the previous one."""
    channels = _ReplayingChannels(
        start_result={},
        replay_events=[_chunk("上一轮的全文")],
        prompt_events=[_chunk("这一轮的答复")],
    )
    observed: list[tuple[str, str]] = []
    port = _port(channels, on_event=lambda _execution, kind, payload: observed.append((kind, payload.get("text", ""))))
    try:
        port.open_execution("execution-replay")

        # 打开会话时到达的回放不算这一轮的增量（`started` 是生命周期事件，不是答复）。
        assert [text for kind, text in observed if kind == "message.delta"] == []
        assert port.replayed_history_chars("execution-replay") == len("上一轮的全文")

        port.prompt("execution-replay", "talk")

        assert [text for kind, text in observed if kind == "message.delta"] == ["这一轮的答复"]
        assert port.replayed_history_chars("execution-replay") == len("上一轮的全文")
    finally:
        port.stop()


def test_steer_is_never_promoted_in_this_stage():
    channels = _ScriptedChannels(start_result={"sessionCapabilities": {"resume": {}}})
    port = _port(channels, declared_capabilities={"start": True, "steer": True})
    try:
        port.open_execution("execution-steer")
        port.prompt("execution-steer", "turn left")
        entry = _entry(port.effective_capabilities("execution-steer"), "steer")
        assert entry["observed"] is None
        assert entry["supported"] is False
        assert entry["reason"] == caps.CAPABILITY_NOT_OBSERVED
    finally:
        port.stop()


def test_effective_capabilities_refuses_an_unknown_execution():
    port = _port(_ScriptedChannels(start_result={}))
    with pytest.raises(SidecarError) as refused:
        port.effective_capabilities("not-opened")
    assert refused.value.code == "EXECUTION_UNKNOWN"


def test_the_port_validates_declared_capabilities_and_has_no_brand_default():
    with pytest.raises(caps.CapabilityUnknownId):
        SidecarHarnessPort(
            _ScriptedLauncher(_ScriptedChannels(start_result={})),
            environment={"AGENTBOX_SIDECAR_ISOLATED": "1"}, profile="fixture",
            declared_capabilities={"streaming": True},
        )
    port = _port(_ScriptedChannels(start_result={}), declared_capabilities=None)
    try:
        # 缺省 = 全部 false：不猜、不默认 true
        assert port.declared_capabilities == {}
        assert port.profile == "fixture"
    finally:
        port.stop()
    default_profile = SidecarHarnessPort(
        _ScriptedLauncher(_ScriptedChannels(start_result={})),
        environment={"AGENTBOX_SIDECAR_ISOLATED": "1"},
    )
    assert default_profile.profile == "", "port 不再携带任何品牌默认 profile"


#: 一条 ACP 流式增量事件：与 driver 的 message_delta 是同一个产品事实。
_ACP_CHUNK_EVENT = {
    "event": "acp_notification",
    "data": {"params": {"update": {
        "sessionUpdate": "agent_message_chunk", "content": {"text": "chunk"},
    }}},
}


@pytest.mark.parametrize("transport,events", [
    ("acp", [_ACP_CHUNK_EVENT]),
    ("driver", [{"event": "message_delta", "data": {"text": "chunk"}}]),
])
def test_equivalent_abilities_project_identically_on_both_transports(transport, events):
    """driver 路径的 `capabilities.sessionCapabilities.resume` 等价于 ACP 的播发。"""
    channels = _ScriptedChannels(
        start_result={
            "sessionCapabilities": {"resume": {}},
            "promptCapabilities": {"image": True},
        },
        events=list(events),
    )
    port = _port(channels)
    try:
        port.open_execution(f"execution-{transport}")
        port.prompt(f"execution-{transport}", "same abilities")
        view = port.effective_capabilities(f"execution-{transport}")
        comparable = [tuple(item[field] for field in COMPARED_FIELDS)
                      for item in view["capabilities"]]
        assert comparable == [
            ("start", "execution", True, True, True, None),
            ("observe", "execution", True, True, True, None),
            ("finish", "execution", True, True, True, None),
            ("attach", "message", True, True, True, None),
            # steer/permissions 本次没有声明也没有观测：既不支持也不虚构原因。
            ("steer", "message", False, None, False, caps.CAPABILITY_NOT_DECLARED),
            ("stream", "message", True, True, True, None),
            ("permissions", "execution", False, None, False, caps.CAPABILITY_NOT_DECLARED),
            ("native_continuation", "session", True, True, True, None),
        ], view
    finally:
        port.stop()


# --------------------------------------------------------------------------
# 后端 / Profile
# --------------------------------------------------------------------------

def test_backend_reads_attachment_support_from_the_port_view_not_a_snapshot():
    class StubPort:
        def __init__(self, supported):
            self._supported = supported

        def effective_capabilities(self, execution_id):
            assert execution_id == "execution-1"
            return {"capabilities": [{"id": "attach", "supported": self._supported}]}

    assert _effective_attachment_support(StubPort(True), "execution-1") is True
    assert _effective_attachment_support(StubPort(False), "execution-1") is False
    assert _effective_attachment_support(StubPort(None), "execution-1") is False

    class Objects:
        def __init__(self, values): self._values = values

        def read(self, digest): return self._values[digest]

    stored = {"message": {"attachments": [
        {"mediaKind": "image", "ref": "a.png", "displayName": "a.png",
         "_contentDigest": "digest-1", "_mime": "image/png"},
        {"mediaKind": "file", "ref": "notes.txt", "_contentDigest": "digest-2"},
        {"mediaKind": "image", "ref": "b.png"},
    ]}}
    attachments, refs = _sidecar_attachments(
        Objects({"digest-1": b"png", "digest-2": b"text"}), stored,
    )
    assert attachments == [{
        "mime": "image/png", "filename": "a.png", "data": base64.b64encode(b"png").decode(),
    }]
    assert refs == ["notes.txt"]


def test_backend_refuses_attachment_dispatch_and_leaves_no_orphan_native_session():
    """后端在派发前读有效 attach；拒绝时关闭刚打开的原生会话。"""
    from pacthold_runtime_compat.resource_contracts import PromptFragmentV1
    from ordessa_server_compat.execution.sidecar_backend import SidecarExecutionBackend

    class Objects:
        def __init__(self, values): self._values = values

        def read(self, digest): return self._values[digest]

    class Port:
        def __init__(self):
            self.opened: list[str] = []
            self.closed: list[str] = []

        def open_execution(self, execution_id):
            self.opened.append(execution_id)
            return "native-fixture"

        def effective_capabilities(self, execution_id):
            return {"capabilities": [{"id": "attach", "supported": False}]}

        def close_execution(self, execution_id):
            self.closed.append(execution_id)

    port = Port()
    # 阶段 D 起：实际启动前的能力强制门要求装配边界已注入绑定与候选声明；
    # 本用例的面为空（无 launcher），注入一份无声明的最小候选即可过门，
    # 以继续验证附件拒绝语义本身。
    from pacthold_runtime_compat import capability as capability_api

    port.capability_binding = "fixture|binding"
    port.capability_authorized_providers = ("fixture",)
    port.capability_documents = (
        capability_api.SandboxDeclarationDocument(
            provider="fixture", revision=1, environment_binding="fixture|binding",
            declarations=(), digest="0" * 64,
        ),
    )
    objects = Objects({
        "input": json.dumps({"message": {"attachments": [
            {"mediaKind": "image", "ref": "a.png", "_contentDigest": "digest-1"},
        ]}}).encode(),
        "digest-1": b"png",
    })
    backend = SidecarExecutionBackend(
        records=None, objects=objects, approvals=None,
        port_factory=lambda _context, _on_event: port,
    )
    backend._turn_by_core["execution-1"] = "turn-1"
    backend._contexts["turn-1"] = {"input_object_digest": "input"}
    with pytest.raises(SidecarError) as refused:
        backend._start_run(
            "execution-1", "dispatch-1", None,
            PromptFragmentV1("turn", "text", "sha256:prompt"), None,
        )
    assert refused.value.code == "ATTACHMENT_UNSUPPORTED"
    assert port.opened == ["turn-1"]
    assert port.closed == ["turn-1"], "被拒绝的附件不得留下没有归属的原生会话"


def test_profile_capabilities_come_from_the_registry_not_a_stored_snapshot(tmp_path):
    registry = HarnessRegistry()
    registry.register(HarnessDescriptor("alpha", capability_claims={"stream": True}))
    database = Database(tmp_path / "data")
    database.initialize()
    idempotency = IdempotentRecords(database)
    records = ProfileRecords(database, idempotency)
    service = ProfileService(
        records, idempotency, ObjectStore(tmp_path / "data"),
        harnesses=registry, credentials=CredentialRecords(database),
    )
    _status, body = service.create("profile-key", {
        "name": "Alpha profile", "harness_type": "alpha",
        "configuration": {}, "credential_id": None,
    })
    assert body["capabilities"] == {"stream": True}
    assert body["capabilities"] == registry.canonical_claims("alpha")
    listed = service.list()
    assert [item["profile_id"] for item in listed] == [body["profile_id"]]
    assert listed[0]["capabilities"] == {"stream": True}
    # 数据库行本身不带任何能力快照：只能来自注册表。
    assert "capabilities" not in records.get(body["profile_id"])


# --------------------------------------------------------------------------
# 真实 sidecar 进程：ACP 与 native driver 的等价投影（需要 node）
# --------------------------------------------------------------------------

@pytest.fixture
def driver_bundle(tmp_path):
    """A bundle-shaped copy, so the driver module resolves the way it does in the guest."""
    view = tmp_path / "view"
    sidecar = view / "agentbox-sidecar"
    runtime = sidecar / "runtime"
    runtime.mkdir(parents=True)
    # worker-entry.mjs 随退役旧链移除（该文件全仓不存在、无生成器、官方注释明言已退役）
    for name in ("native-driver.mjs", "profile_extensions.mjs"):
        shutil.copyfile(PLUGIN / "runtime" / name, runtime / name)
    shutil.copytree(PLUGIN / "third_party" / "harness_remote",
                    sidecar / "third_party" / "harness_remote")
    driver = view / DRIVER_BUNDLE_PATH
    driver.parent.mkdir(parents=True)
    shutil.copyfile(FIXTURE_DRIVER, driver)
    return view


def _real_environment(tmp_path: Path) -> dict:
    home = tmp_path / "home"
    home.mkdir(parents=True, exist_ok=True)
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"), "HOME": str(home),
        "AGENTBOX_SIDECAR_ISOLATED": "1",
    }


@pytest.mark.skipif(not shutil.which("node"), reason="node is unavailable")
def test_real_acp_and_driver_routes_share_one_canonical_view(tmp_path, driver_bundle):
    """两条真实传输（ACP 注册 / 部署声明的 driver 模块）投影出同一个 canonical 视图。"""
    views: dict[str, dict] = {}
    for name, profile, launcher, adapter in (
        ("acp", "pi", LocalProcessLauncher(["node", str(SIDECAR_ENTRY)], cwd=str(PLUGIN)),
         {"command": "node", "args": [str(FAKE_PEER)]}),
        ("driver", "fixture-native", LocalProcessLauncher(
            ["node", str(driver_bundle / "agentbox-sidecar" / "runtime" / "worker-entry.mjs")]),
         {"command": "/runtime/bin/fixture-native", "args": ["run"],
          "driver": {"module": str(driver_bundle / DRIVER_BUNDLE_PATH)}}),
    ):
        port = SidecarHarnessPort(
            launcher, environment=_real_environment(tmp_path / name), profile=profile,
            adapter=adapter, declared_capabilities=dict(EQUIVALENT_DECLARED),
            state_directory=str(tmp_path / name / "state"), directory=str(tmp_path),
        )
        try:
            port.open_execution(f"execution-{name}")
            port.prompt(f"execution-{name}", "capability projection")
            views[name] = port.effective_capabilities(f"execution-{name}")
        finally:
            port.stop()
    by_transport = {
        name: {item["id"]: tuple(item[field] for field in COMPARED_FIELDS)
               for item in view["capabilities"]}
        for name, view in views.items()
    }
    # nativeEvidence 允许不同（来源确实不同），其余字段逐项相同——含
    # native_continuation：受控 ACP peer 与 driver fixture 都播发
    # `sessionCapabilities.resume`，因此两条传输必须得到同一支持结论。
    for capability_id in ("start", "observe", "finish", "attach", "stream", "permissions",
                          "steer", "native_continuation"):
        assert by_transport["acp"][capability_id] == by_transport["driver"][capability_id], (
            capability_id, json.dumps(views, indent=1)[:1200])
    assert by_transport["acp"]["native_continuation"] == (
        "native_continuation", "session", True, True, True, None)
    assert by_transport["acp"]["start"] == ("start", "execution", True, True, True, None)
    assert by_transport["acp"]["attach"] == ("attach", "message", True, True, True, None)

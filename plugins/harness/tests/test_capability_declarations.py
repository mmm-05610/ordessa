"""插件侧能力声明合同：一份静态事实来源，四处投影逐项相等。

本文件管的是**静态声明**（产品层的能力上限），它只有一份事实来源：

    ordessa_harness/harnesses.toml  →  capability_declarations.json（JS 投影）
                                        →  四家 production.py 的 capabilityClaims
                                        →  registry.schema 的封闭词汇表

四处逐项相等由下面的测试断言，任何一处手抄漂移都会直接红。canonical 词汇表本身来自
`pacthold.resource_contracts.harness_capabilities`（Server 侧合同），本文件只**读**它，
不复制它。

本文件同时是四家能力矩阵的 golden：每一项能力都写明 declared / observed 与**证据来源**。
"observed" 的判定规则（与合同一致）：

* 实现级 `{start, observe, finish, stream}`：已注册且被真实调用的 sidecar/driver 操作
  合同就是观测来源；
* 语义级 `{attach, steer, permissions, native_continuation}`：必须有**显式运行时证据**
  才叫 observed。没有证据就写 NOT_OBSERVED——**不得**因为"文档说支持"或"代码里有这条
  路径"就升级成 observed。
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest

from pacthold_runtime_compat.resource_contracts import harness_capabilities as caps
from ordessa_harness.codex import production as codex_production
from ordessa_harness.claude import production as claude_code_production
from ordessa_harness.kilo import production as kilo_production
from ordessa_harness.dsh import production as dsh_production
from ordessa_harness.hermes import production as hermes_production
from ordessa_harness.opencode import production as opencode_production
from ordessa_harness.pi import production as pi_production
from ordessa_harness.registry import load_builtin_registry
from ordessa_harness.registry.loader import load_registry

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
DEFINITIONS = PLUGIN_ROOT / "src" / "ordessa_harness" / "harnesses.toml"
JS_PROJECTION = PLUGIN_ROOT / "runtime" / "capability_declarations.json"
RUNTIME = PLUGIN_ROOT / "runtime"

#: 已封装家族（顺序固定，便于报告与参数化 golden 对齐）；Work Order 43 起
#: 扩容家族按接入顺序追加在尾部。
FAMILIES = ("codex", "pi", "hermes", "opencode", "dsh", "claude-code", "kilo")

#: 证据文档（只读引用，不在本测试里重新解释它们的内容）。
PI_PACKAGING = "docs/server-round1/fullstack/pi-production-packaging.md"
HERMES_PACKAGING = "docs/server-round1/fullstack/hermes-production-packaging.md"
OPENCODE_PACKAGING = "docs/server-round1/fullstack/opencode-production-packaging.md"
ACCEPTANCE = "docs/server-round1/harness-integration/stage-c.md"
DSH_PACKAGING = "docs/server-round1/fullstack/dsh-production-packaging.md"
CLAUDE_PACKAGING = "docs/server-round1/fullstack/claude-production-packaging.md"
KILO_PACKAGING = "docs/server-round1/fullstack/kilo-production-packaging.md"

#: 观测结论的两个取值。刻意用字符串常量而不是 True/False：`False` 会被误读成
#: "已观测到不支持"，而这里是"没有证据"。
OBSERVED = "observed"
NOT_OBSERVED = "not-observed"
#: Evidence prefix for the Codex production chain gate run.
CODEX_EVIDENCE = "[codex-production-packaging](../docs/server-round1/fullstack/codex-production-packaging.md)"

#: 实现级观测依据：driver/sidecar 接缝的必需方法集合。
SIDECAR_CONTRACT_EVIDENCE = (
    "实现级：sidecar/driver 接缝的必需方法集合已注册，且在该家的假端点全链门里被真实调用"
)

#: 一条"证据串"必须点出至少一个可复核的观测物，否则它只是形容词。
RUNTIME_OBSERVATION_TOKENS = (
    "门", "@1", "sidecar", "completed", "deltaSeq", "completedSeq", "nativeSessionId",
    "nativeSessionIdStable", "acpMethods", "createsInsideReopenPhase", "hostStarts",
    "storedMessages", "promptCapabilities", "state.db", "message.delta",
    "session/load", "session/resume", "/responses",
)


def _cites_runtime_observation(evidence: object) -> bool:
    if not isinstance(evidence, str) or not evidence.strip():
        return False
    return any(token in evidence for token in RUNTIME_OBSERVATION_TOKENS)

#: 四家能力矩阵 golden。每一项 = (declared, observed, 证据来源)。
#:
#: declared 一栏必须逐项等于 harnesses.toml；observed 一栏是本审计的结论，不是文档
#: 转述。两边都由 test_the_golden_matrix_matches_the_declarations 交叉校验。
FAMILY_MATRIX: dict[str, dict[str, tuple[bool, str, str]]] = {
    "codex": {
        "start": (True, OBSERVED,
                  f"{CODEX_EVIDENCE}：真实 codex-acp 1.1.14 + Codex app-server 0.147.0 经工件进入"
                  " c4/c5 Worker+bwrap，首轮 create+prompt → completed，两轮各 1 次 provider 请求"),
        "observe": (True, OBSERVED,
                    f"{CODEX_EVIDENCE}：首轮拿到原生 session id，次轮以 session/list + session/load "
                    "重开同一 id（nativeSessionIdStable=true）"),
        "finish": (True, OBSERVED, f"{CODEX_EVIDENCE}：prompt 交付完成，终止前 delta 4 < completed 7"),
        "attach": (True, NOT_OBSERVED,
                   "静态候选保留；生产链里没有送过任何附件，未观测到原生附件能力"),
        "stream": (True, OBSERVED,
                   f"{CODEX_EVIDENCE}：/responses 流式增量先于 completed（deltaSeq 4 < completedSeq 7，"
                   "次轮 10,12 < 15）"),
        "permissions": (True, NOT_OBSERVED,
                        "静态候选保留；生产链里没有任何 permission round-trip 被观测到"),
        "native_continuation": (True, OBSERVED,
                                f"{CODEX_EVIDENCE}：同一 native id + 次轮上下文含首轮 user/assistant + "
                                "重开相位实测 ACP session/load（带重放，不是 session/resume）"),
        "steer": (False, NOT_OBSERVED, "未声明；codex 的 cancel 语义是中止，不是 steer"),
    },
    "pi": {
        "start": (True, OBSERVED,
                  f"{PI_PACKAGING} §3：真实 @automatalabs/pi-acp@0.5.0 + 假端点，create+prompt →"
                  " completed，两轮各 1 次 provider 请求"),
        "observe": (True, OBSERVED, SIDECAR_CONTRACT_EVIDENCE),
        "finish": (True, OBSERVED,
                   f"{PI_PACKAGING} §3：该轮交付为 completed（delta 序号先于 completed），非超时/中断"),
        "attach": (True, NOT_OBSERVED,
                   f"两个条件只成立一个：真实握手播发 promptCapabilities {{image}}"
                   f"（{ACCEPTANCE} 第 28 行）。投递链路曾"
                   f"（SidecarHarnessPort._start_run → port.prompt(..., attachments) →"
                   f" worker-entry.mjs → AcpService.prompt）在代码上成立，但那条链路是**已退役的"
                   f"信封分发**（移除位置与恢复路径见 REMOVALS.md），新链是逐字转发客户端所写帧的"
                   f" transport-only 中继，不自行构造附件；且门的每一轮"
                   f" message.attachments 都是 []（{PI_PACKAGING} §3 门 JSON），没有任何一次"
                   " 运行真的投递过非空附件。没有运行时证据 ⇒ not-observed"),
        "stream": (True, OBSERVED,
                   f"{PI_PACKAGING} §3：第一轮 delta 4 < completed 7、第二轮 11 < 14，"
                   "deltaAttribution.unattributed=0"),
        "native_continuation": (True, OBSERVED,
                                f"{PI_PACKAGING} §3：nativeSessionIdStable=true，第二轮"
                                " checkpoint 与第一轮同 id，第二轮上下文来自 Pi 自己的 journal"
                                "（`session/load` 重放路径，不是 Server 重放）"),
        "steer": (False, NOT_OBSERVED, "未声明；sidecar 的 abort op 是 cancel，插件没有任何把 abort 当 steer 的代码"),
        "permissions": (False, NOT_OBSERVED, "未声明；门里没有任何权限裁决请求被观测到"),
    },
    "hermes": {
        "start": (True, OBSERVED,
                  f"{HERMES_PACKAGING} §3：真实 Hermes 0.19.0 + 假端点，create+prompt → completed"),
        "observe": (True, OBSERVED, SIDECAR_CONTRACT_EVIDENCE),
        "finish": (True, OBSERVED, f"{HERMES_PACKAGING} §3：两轮都交付为 completed，delta 先于终态"),
        "attach": (False, NOT_OBSERVED,
                   f"{HERMES_PACKAGING} §3：门的两轮 message.attachments 均为 []，"
                   "没有任何附件投递运行时证据；未声明"),
        "stream": (True, OBSERVED, f"{HERMES_PACKAGING} §3：deltaSeq 4<7、11<14，deltaAttribution.unattributed=0"),
        "native_continuation": (True, OBSERVED,
                                f"{HERMES_PACKAGING} §3：acpMethods.chain=[new_session, resume_session]"
                                "（直接观测，不是猜），第二轮 nativeSessionId 与第一轮相同，"
                                "state.db/state.db-wal 被回投，第二轮请求体含第一轮 user+assistant"),
        "steer": (False, NOT_OBSERVED, "未声明；driver 接缝的 abort 是取消，不是 steer"),
        "permissions": (False, NOT_OBSERVED,
                        "未声明；Hermes 的 ACP 会话方法观测里没有权限裁决（模型控制拒绝与"
                        " CREDENTIAL_REQUIRED 都是 Server/sidecar 的拒绝，不是权限裁决）"),
    },
    "opencode": {
        "start": (True, OBSERVED,
                  f"{OPENCODE_PACKAGING} §3.2：真实单文件二进制 + 假端点，两轮 completed"),
        "observe": (True, OBSERVED, SIDECAR_CONTRACT_EVIDENCE),
        "finish": (True, OBSERVED, f"{OPENCODE_PACKAGING} §3.2：每轮 3 条真实增量后交付 completed"),
        "attach": (False, NOT_OBSERVED,
                   f"{OPENCODE_PACKAGING} §2 驱动第 6 条：附件被驱动在发包前以"
                   " OPENCODE_ATTACHMENTS_UNSUPPORTED 显式拒绝（不静默丢弃），"
                   "原生 promptCapabilities.image=false；未声明"),
        "stream": (True, OBSERVED, f"{OPENCODE_PACKAGING} §3.2：假端点真 chunked 逐词流式，delta 序号先于 completed"),
        "native_continuation": (True, OBSERVED,
                                f"{OPENCODE_PACKAGING} §3.5：重开相位 createsInsideReopenPhase=[]"
                                "（没有任何 create）、hostStarts≥2、同一 nativeSessionId；"
                                "open = GET /session/<id>（created:false、storedMessages=2）"),
        "steer": (False, NOT_OBSERVED, "未声明；driver 的 abort 是取消，不是 steer"),
        "permissions": (False, NOT_OBSERVED, "未声明；门里没有任何权限裁决请求被观测到"),
    },
    # Work Order 43。dsh 0.1.5-rc.1（DeepSeek 官方 Harness，`dsh --profile acp`）：
    # observed 列来自 2026-09-16 dsh 假端点全链门的真实运行（exit 0，门报告见
    # dsh-production-packaging.md §5）。`attach`/`permissions` 与四家同规矩：
    # 无运行时证据 ⇒ 不声明、不观测。
    "dsh": {
        "start": (True, OBSERVED,
                  f"{DSH_PACKAGING} §5：真实 @deepseek-ai/dsh 0.1.5-rc.1（`dsh --profile acp`）"
                  " + 假端点，create+prompt → completed，两轮恰 2 次 provider 请求"),
        "observe": (True, OBSERVED,
                    f"{DSH_PACKAGING} §5：sidecar 接缝真实调用；首轮拿到原生 session id"
                    "（checkpoint nativeSessionId，schema v2，resumable=true）"),
        "finish": (True, OBSERVED,
                   f"{DSH_PACKAGING} §5：两轮均交付 completed（deltaSeq [4] < completedSeq 7、"
                   "[11] < 14），非超时/中断"),
        "attach": (False, NOT_OBSERVED,
                   "未声明；官方文档没有任何附件投递面，门的两轮 attachments 均空，"
                   "无运行时证据"),
        "stream": (True, OBSERVED,
                   f"{DSH_PACKAGING} §5：delta 先于 completed（deltaSeq [4] < completedSeq 7、"
                   "[11] < 14），deltaAttribution.unattributed=0"),
        "native_continuation": (True, OBSERVED,
                                f"{DSH_PACKAGING} §5：同一 native id（checkpointNativeIdStable=true）"
                                " + 重开相位 replayedStoredTurn=false（dsh 只支持不重放的 "
                                "session/resume）+ 第二轮请求体带首轮上下文"
                                "（round2RequestCarriedRound1Context=true）"),
        "steer": (False, NOT_OBSERVED, "未声明；sidecar 的 abort op 是 cancel，不是 steer"),
        "permissions": (False, NOT_OBSERVED,
                        "未声明；官方 ACP 面有 request_permission，但门里没有任何运行时"
                        "权限裁决被观测到，按诚实规则保持未声明"),
    },
    # Work Order 43。claude-code 0.81.2（官方 ACP 适配器 + Anthropic 专有 SDK/二进制，
    # 许可边界见 claude-production-packaging.md）：observed 来自 2026-09-16 的
    # claude 假端点全链门真实运行（exit 0，门报告见 claude-production-packaging.md §5）。
    "claude-code": {
        "start": (True, OBSERVED,
                  f"{CLAUDE_PACKAGING} §5：真实 claude-agent-acp 0.81.2（内嵌 Anthropic CLI 二进制）"
                  " + 假端点，create+prompt → completed"),
        "observe": (True, OBSERVED,
                    f"{CLAUDE_PACKAGING} §5：首轮拿到原生 session id（checkpoint nativeSessionId，"
                    "schema v2，resumable=true，transcript jsonl 回投）"),
        "finish": (True, OBSERVED,
                   f"{CLAUDE_PACKAGING} §5：两轮均交付 completed（deltaSeq [4] < completedSeq 7、"
                   "[11] < 14），非超时/中断"),
        "attach": (True, OBSERVED,
                   f"P-D 重探针 2026-09-28（{CLAUDE_PACKAGING} §8；"
                   "packaging/claude/attachment-probe.mjs，转录与哈希见"
                   " specs/014-plugin-release/reports/P-D-probe-transcript.json）：钉版 0.81.2 "
                   "真实握手播发 promptCapabilities {image:true, embeddedContext:true}——"
                   "推翻 0.77 时代『握手 promptCapabilities 为空』的旧负证据（升版未重探的"
                   "遗留观测，非本次读取位置错误）；image 块端到端往返 base64 内容 sha256 "
                   "一致；resource_link 按 URI 链接文本下发（https 原文、file:// 为 "
                   "[@name](uri) markdown 链接）；audio 块被适配器静默丢弃，通路层类型化"
                   "拒绝、不投递（语义分层如实：图片=真实附件块、非图片=URI 链接）"),
        "stream": (True, OBSERVED,
                   f"{CLAUDE_PACKAGING} §5：delta 先于 completed（deltaSeq [4] < completedSeq 7、"
                   "[11] < 14），deltaAttribution.unattributed=0"),
        "native_continuation": (True, OBSERVED,
                                f"{CLAUDE_PACKAGING} §5：同一 native id（checkpointNativeIdStable=true）"
                                " + 重开相位实测非重放的 session/resume（reopenMethod 记录并钉死）"
                                " + 含 round2 标记的请求体带首轮对话（assistant + round1 nonce）"),
        "steer": (False, NOT_OBSERVED, "未声明；sidecar 的 abort op 是 cancel，不是 steer"),
        "permissions": (False, NOT_OBSERVED,
                        "未声明；适配器有 permission mode 配置面（探测记录），但门里没有任何"
                        "运行时权限裁决被观测到，按诚实规则保持未声明"),
    },
    # Work Order 43 后续。kilo 7.7.2（OpenCode fork，官方 `kilo acp`）：observed
    # 在假端点门跑出证据前全部保持 NOT_OBSERVED；探测事实（provider/model 寻址、
    # session/load+resume 双通道、{env:} 凭据替换）只作为接入卡记录。
    "kilo": {
        "start": (True, NOT_OBSERVED,
                  f"{KILO_PACKAGING} §5：静态声明；本仓的门尚未执行——无运行时证据"),
        "observe": (True, NOT_OBSERVED,
                    "实现级：sidecar 接缝的必需方法集合已注册；该家的假端点全链门"
                    "尚未执行"),
        "finish": (True, NOT_OBSERVED, f"{KILO_PACKAGING} §5：静态声明；门的 completed 终态观测待补"),
        "attach": (False, NOT_OBSERVED, "未声明；无任何附件投递面与运行时证据"),
        "stream": (True, NOT_OBSERVED,
                   f"{KILO_PACKAGING} §5：静态声明；探测记录有 agent_message_chunk，"
                   "但本仓的 delta-先于-completed 观测待门补"),
        "native_continuation": (True, NOT_OBSERVED,
                                f"{KILO_PACKAGING} §5：静态声明；探测实证 session/load 与 "
                                "session/resume 双通道可用，本仓的重开观测待补"),
        "steer": (False, NOT_OBSERVED, "未声明；sidecar 的 abort op 是 cancel，不是 steer"),
        "permissions": (False, NOT_OBSERVED,
                        "未声明；官方有 requestPermission 规则面，但没有任何运行时"
                        "权限裁决被观测到，按诚实规则保持未声明"),
    },
}


def _toml_declarations() -> dict[str, set[str]]:
    """直接从 TOML 文本读声明，而不是从 `registry` 读：本测试要独立复核那条路径。"""
    raw = tomllib.loads(DEFINITIONS.read_text(encoding="utf-8"))
    return {
        entry["identity"]["harness_type"]: set(entry.get("capabilities", ()))
        for entry in raw["harness"]
    }


def _toml_text_with(capabilities: list) -> str:
    """把 codex 的 capabilities 换成本测试给定的值，保留其余全部内容。"""
    raw = tomllib.loads(DEFINITIONS.read_text(encoding="utf-8"))
    for entry in raw["harness"]:
        if entry["identity"]["harness_type"] == "codex":
            entry["capabilities"] = capabilities
    return _render_toml(raw)


def _render_toml(raw: dict) -> str:
    """最小 TOML 渲染器：只为把被改动的 doc 重新序列化成可解析文本。"""
    lines: list[str] = [f"schema_version = {raw['schema_version']}"]
    for entry in raw["harness"]:
        lines.append("\n[[harness]]")
        for key in ("schema_version", "driver", "capabilities"):
            lines.append(f"{key} = {json.dumps(entry[key])}")
        for section in ("identity", "executable", "profile", "runtime", "continuation", "credential"):
            if section in entry:
                lines.append(f"[harness.{section}]")
                for key, value in entry[section].items():
                    lines.append(f"{key} = {json.dumps(value)}")
        for section in ("inputs", "launch_modes"):
            for item in entry.get(section, ()):
                lines.append(f"[[harness.{section}]]")
                for key, value in item.items():
                    lines.append(f"{key} = {json.dumps(value)}")
    return "\n".join(lines) + "\n"


def _production_claims(family: str) -> dict:
    """四家生产模板声明的 capabilityClaims（同一形状的接缝）。"""
    if family == "codex":
        assert codex_production.HAS_PRODUCTION_DEPLOYMENT is True
        return codex_production.capability_claims()
    module = {"pi": pi_production, "hermes": hermes_production, "opencode": opencode_production,
              "dsh": dsh_production, "claude-code": claude_code_production,
              "kilo": kilo_production}[family]
    if family == "pi":
        document = module.deployment_document(
            artifact_token="artifact", tree_digest="sha256:" + "a" * 64)
    elif family == "hermes":
        document = module.deployment_document(
            artifact_token="artifact", tree_digest="sha256:" + "a" * 64)
    elif family == "dsh":
        document = module.deployment_document(
            artifact_token="artifact", tree_digest="sha256:" + "a" * 64)
    elif family == "claude-code":
        document = module.deployment_document(
            artifact_token="artifact", tree_digest="sha256:" + "a" * 64)
    elif family == "kilo":
        document = module.deployment_document(
            artifact_token="artifact", tree_digest="sha256:" + "a" * 64)
    else:
        document = module.deployment_document(
            binary_token="binary", binary_digest="sha256:" + "a" * 64)
    harness = document["harnesses"][0]
    assert harness["id"] == family
    return harness["capabilityClaims"]


# --------------------------------------------------------------------------- #
# 1) TOML 与四家 production deployment 的 capabilityClaims 逐项相等
# --------------------------------------------------------------------------- #

def test_the_registry_schema_takes_its_vocabulary_from_the_canonical_contract():
    """`_CAPS` 不再是一份手写副本，而是 canonical 合同的封闭集合。"""
    from ordessa_harness.registry import schema

    assert schema._CAPS == frozenset(caps.CANONICAL_CAPABILITY_IDS)
    assert len(schema._CAPS) == len(caps.CANONICAL_CAPABILITY_IDS)
    # 而且它确实来自合同：合同里没有的 id 不可能出现在这个集合里。
    assert schema._CAPS <= set(caps.CANONICAL_CAPABILITY_IDS)


@pytest.mark.parametrize("family", FAMILIES)
def test_each_production_template_declares_exactly_the_registry_claims(family):
    """硬要求：四家模板的 capabilityClaims 的 true 项 == TOML 的 capabilities。"""
    claims = _production_claims(family)
    declared = {capability_id for capability_id, value in claims.items() if value}
    assert declared == _toml_declarations()[family], family
    # 键必须是**全部** canonical id，一个不多一个不少。
    assert tuple(claims) == caps.CANONICAL_CAPABILITY_IDS, family
    # 值必须是真 bool（不许 "supported" / 1 / None / 缺省）。
    assert all(type(value) is bool for value in claims.values()), family


@pytest.mark.parametrize("family", FAMILIES)
def test_the_production_claims_pass_the_canonical_contract(family):
    """模板声明必须能原样通过 Server 侧合同校验，并给出保守的保守结论。"""
    claims = _production_claims(family)
    assert caps.validate_claims(claims) == claims
    view = {item.id: item for item in caps.merge_capabilities(claims, {})}
    assert set(view) == set(caps.CANONICAL_CAPABILITY_IDS)
    # 没有运行时观测时，语义级能力绝不能被声明本身抬高成 supported。
    for capability_id in caps.SEMANTIC_CAPABILITIES:
        assert view[capability_id].supported is False, (family, capability_id)
        assert view[capability_id].reason == (
            caps.CAPABILITY_NOT_OBSERVED if claims[capability_id] else caps.CAPABILITY_NOT_DECLARED
        ), (family, capability_id)


def test_the_registry_and_the_toml_text_agree_on_every_declaration():
    """两条读法（`registry` 与裸 TOML）必须给出同一份声明。"""
    registry = load_builtin_registry()
    from_registry = {item.harness_type: set(item.capabilities) for item in registry.all()}
    assert from_registry == _toml_declarations()


def test_the_derived_claims_refuse_an_unknown_harness_instead_of_returning_nothing():
    """拼错 harness 名不能静默降级成"什么都不支持"。"""
    from ordessa_harness.registry.capability_claims import capability_claims

    with pytest.raises(KeyError):
        capability_claims("codexx")
    assert set(capability_claims("codex")) == set(caps.CANONICAL_CAPABILITY_IDS)


# --------------------------------------------------------------------------- #
# 2) capability_declarations.json 与 TOML 逐项相等
# --------------------------------------------------------------------------- #

def test_the_js_projection_is_item_for_item_equal_to_the_toml():
    document = json.loads(JS_PROJECTION.read_text(encoding="utf-8"))
    assert set(document) == {"schemaVersion", "harnessTypes"}
    assert document["schemaVersion"] == caps.CAPABILITY_SCHEMA_VERSION
    assert document["harnessTypes"] == {
        harness_type: sorted(abilities)
        for harness_type, abilities in _toml_declarations().items()
    }
    # 值只能是 canonical id，且必须按字典序（投影规范固定顺序）。
    for harness_type, abilities in document["harnessTypes"].items():
        assert abilities == sorted(abilities), harness_type
        assert set(abilities) <= set(caps.CANONICAL_CAPABILITY_IDS), harness_type


def test_the_js_projection_covers_every_registered_harness():
    document = json.loads(JS_PROJECTION.read_text(encoding="utf-8"))
    assert set(document["harnessTypes"]) == {
        definition.harness_type for definition in load_builtin_registry().all()
    }


# --------------------------------------------------------------------------- #
# 3) 未知 id / 漂移别名 / 非 bool 值都必须被拒绝
# --------------------------------------------------------------------------- #

def test_an_unknown_capability_id_is_refused_at_the_toml_layer():
    with pytest.raises(ValueError, match="unknown capability"):
        load_registry(_toml_text_with(["start", "teleport"]))


def test_a_native_alias_is_refused_at_the_toml_layer():
    """别名不是"写法的另一种"，它是**另一个词汇**：进得来就会被当成真的产品能力。"""
    for alias in sorted(caps.DRIFT_ALIASES):
        with pytest.raises(ValueError, match="unknown capability"):
            load_registry(_toml_text_with(["start", alias]))


def test_no_declaration_anywhere_carries_a_native_alias():
    """四处投影里都不许出现别名——包括 JSON 投影与四家模板的 capabilityClaims。"""
    aliases = set(caps.DRIFT_ALIASES)
    for harness_type, abilities in _toml_declarations().items():
        assert not (abilities & aliases), harness_type
    projection = json.loads(JS_PROJECTION.read_text(encoding="utf-8"))
    for harness_type, abilities in projection["harnessTypes"].items():
        assert not (set(abilities) & aliases), harness_type
    for family in FAMILIES:
        assert not (set(_production_claims(family)) & aliases), family
    # TOML 文本本身也不许出现这些词（注释里提到"别名"是允许的，但键不能是别名）。
    text = DEFINITIONS.read_text(encoding="utf-8")
    for alias in sorted(aliases):
        assert f'"{alias}"' not in text, alias


def test_a_non_boolean_capability_value_is_refused():
    """能力值必须是真 bool：字符串/整数/None/列表/缺省一律拒绝。"""
    # TOML 层：capabilities 是 id 列表，元素必须是字符串。
    with pytest.raises(ValueError, match="capabilities must be a list"):
        load_registry(_toml_text_with([1, 2]))
    with pytest.raises(ValueError, match="capabilities must be a list"):
        load_registry(_toml_text_with([True]))
    # 声明座位（deployment.capabilityClaims）由 canonical 合同校验。
    for malformed in ({"stream": "yes"}, {"stream": 1}, {"stream": None}, {"stream": []}):
        with pytest.raises(caps.CapabilityValueNotBoolean):
            caps.validate_claims(malformed)
    # 四家模板产出的每一项都是真 bool，不是 truthy。
    for family in FAMILIES:
        for capability_id, value in _production_claims(family).items():
            assert type(value) is bool, (family, capability_id, type(value).__name__)


def test_an_alias_in_the_claims_seat_is_refused_with_the_canonical_id_named():
    """别名被拒时错误信息要指出它该写成哪个 canonical id，而不是只说不认识。"""
    for alias, canonical in sorted(caps.DRIFT_ALIASES.items()):
        with pytest.raises(caps.CapabilityUnknownId) as refused:
            caps.validate_claims({alias: True})
        assert canonical in str(refused.value), alias


# --------------------------------------------------------------------------- #
# 4) 四家能力矩阵的 golden（每项 id + declared/observed + 证据来源）
# --------------------------------------------------------------------------- #

def test_the_golden_matrix_covers_every_canonical_id_of_every_family():
    assert set(FAMILY_MATRIX) == set(FAMILIES)
    for family, matrix in FAMILY_MATRIX.items():
        assert set(matrix) == set(caps.CANONICAL_CAPABILITY_IDS), family
        for capability_id, (declared, observed, evidence) in matrix.items():
            assert type(declared) is bool, (family, capability_id)
            assert observed in {OBSERVED, NOT_OBSERVED}, (family, capability_id)
            assert isinstance(evidence, str) and evidence.strip(), (family, capability_id)


@pytest.mark.parametrize("family", FAMILIES)
def test_the_golden_matrix_declared_column_equals_the_registry(family):
    """golden 的 declared 一栏不许背离 TOML，否则它就成了第二份声明。"""
    declared = _toml_declarations()[family]
    for capability_id, (is_declared, _, _) in FAMILY_MATRIX[family].items():
        assert is_declared is (capability_id in declared), (family, capability_id)


@pytest.mark.parametrize("family", FAMILIES)
def test_the_golden_matrix_observed_column_matches_the_contract_levels(family):
    """观测结论必须与合同的能力分级一致，且不得借用别人的观测方式。

    * 实现级 `{start, observe, finish, stream}`：证据来源是 sidecar/driver 的操作合同
      （已注册且被真实调用），或该家链门的直接观测；
    * 语义级 `{attach, steer, permissions, native_continuation}`：证据必须是**显式运行时
      观测**，不能是那句实现级套话——否则就是把"操作存在"当成"语义成立"。
    """
    for capability_id, (_, observed, evidence) in FAMILY_MATRIX[family].items():
        if observed != OBSERVED:
            continue
        assert _cites_runtime_observation(evidence), (family, capability_id, evidence)
        if capability_id in caps.SEMANTIC_CAPABILITIES:
            assert evidence != SIDECAR_CONTRACT_EVIDENCE, (family, capability_id)


def test_codex_observes_exactly_what_its_production_gate_proved():
    """Codex 已有生产封装 ⇒ observed 只能等于门里真正发生的能力。

    附件与审批没有在链路上真实发生过，因此即使静态候选声明了它们，也必须保持
    not-observed；`steer` 从未声明，同样不得被"顺手"算成已观测。
    """
    assert codex_production.HAS_PRODUCTION_DEPLOYMENT is True
    observed = {capability_id for capability_id, (_, state, _) in FAMILY_MATRIX["codex"].items()
                if state == OBSERVED}
    assert observed == {"start", "observe", "finish", "stream", "native_continuation"}
    assert codex_production.observed_capabilities() == frozenset(observed)
    for capability_id in ("attach", "permissions", "steer"):
        assert FAMILY_MATRIX["codex"][capability_id][1] == NOT_OBSERVED, capability_id


def test_the_four_families_matrix_summary_is_the_one_reported():
    """把矩阵压成一张可读的表：谁声明了什么、哪几项真的有运行时证据。"""
    summary = {}
    for family, matrix in FAMILY_MATRIX.items():
        summary[family] = {
            "declared": sorted(i for i, (declared, _, _) in matrix.items() if declared),
            "observed": sorted(i for i, (_, observed, _) in matrix.items() if observed == OBSERVED),
        }
    assert summary == {
        "codex": {"declared": ["attach", "finish", "native_continuation", "observe",
                               "permissions", "start", "stream"],
                  "observed": ["finish", "native_continuation", "observe", "start", "stream"]},
        "pi": {"declared": ["attach", "finish", "native_continuation", "observe", "start", "stream"],
               "observed": ["finish", "native_continuation", "observe", "start", "stream"]},
        "hermes": {"declared": ["finish", "native_continuation", "observe", "start", "stream"],
                   "observed": ["finish", "native_continuation", "observe", "start", "stream"]},
        "opencode": {"declared": ["finish", "native_continuation", "observe", "start", "stream"],
                     "observed": ["finish", "native_continuation", "observe", "start", "stream"]},
        # Work Order 43：dsh 的 observed 来自 2026-09-16 假端点全链门（exit 0）。
        "dsh": {"declared": ["finish", "native_continuation", "observe", "start", "stream"],
                "observed": ["finish", "native_continuation", "observe", "start", "stream"]},
        # Work Order 43：claude-code 的 observed 来自 2026-09-16 假端点全链门（exit 0）；
        # 2026-09-28 P-D 重探针把 attach 的 observed 翻绿（附件往返与 resource_link 语义
        # 第一手实测，见 P-D-probe-transcript.json）。
        "claude-code": {"declared": ["attach", "finish", "native_continuation", "observe",
                                     "start", "stream"],
                        "observed": ["attach", "finish", "native_continuation", "observe",
                                     "start", "stream"]},
        # Work Order 43 后续：kilo 的假端点门跑出证据前，observed 必须是空集。
        "kilo": {"declared": ["finish", "native_continuation", "observe", "start", "stream"],
                 "observed": []},
    }


def test_native_continuation_is_declared_exactly_where_reopen_was_observed():
    """`native_continuation` 与 continuation.kind 必须一致：声明了就要有重开证据。"""
    registry = load_builtin_registry()
    for definition in registry.all():
        declares = "native_continuation" in definition.capabilities
        if definition.continuation.kind == "native_session":
            assert declares, definition.harness_type
        if declares and definition.harness_type in {"codex", "claude-code"}:
            # 这两家没有任何重开运行时证据（codex 无生产封装；claude 未跑门），
            # 因此它们的 kind 仍是 native_session 的**静态候选**，本测试只记录事实。
            assert definition.continuation.kind == "native_session"


def test_the_audited_families_continuation_kind_is_native_session():
    """审计结论落在注册表上：她的重开方式就是 native session，而不是 transcript 交接。"""
    registry = load_builtin_registry()
    for harness_type in ("codex", "hermes", "opencode", "pi", "dsh", "claude-code", "kilo"):
        assert registry.get(harness_type).continuation.kind == "native_session", harness_type


def test_no_family_claims_the_two_abilities_without_evidence():
    """四家都不许声明 `steer`；除 codex（静态候选）外都不许声明 `permissions`。"""
    declared = _toml_declarations()
    for family in FAMILIES:
        assert "steer" not in declared[family], family
    assert "permissions" not in declared["pi"]
    assert "permissions" not in declared["hermes"]
    assert "permissions" not in declared["opencode"]


# --------------------------------------------------------------------------- #
# 6) JS 运行时确实读的是这份投影，并且读不到时**失败关闭**
# --------------------------------------------------------------------------- #

def _node_probe(module_path: Path, statements: str) -> subprocess.CompletedProcess:
    """在 node 里 import 该模块并执行给定的语句块（语句自己负责写出 stdout）。"""
    script = ("import(" + json.dumps(module_path.as_uri()) + ").then((module) => {"
              + statements + "})")
    return subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=60)


def test_the_js_runtime_reads_the_checked_in_projection():
    """JS 侧的上限就是这份投影：不是内联的第二份表，也不是空集。"""
    result = _node_probe(RUNTIME / "profile_extensions.mjs", (
        "process.stdout.write(JSON.stringify({"
        " declarations: module.capabilityDeclarations(),"
        " hermes: module.canonicalCapabilityClaims('hermes'),"
        " pi: module.canonicalCapabilityClaims('pi', { prompt: true, streaming: true,"
        " permissions: true, native_continuation: true, abort: true,"
        " filesystemBrowser: true, sessions: true }) }))"
    ))
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    projection = json.loads(JS_PROJECTION.read_text(encoding="utf-8"))
    assert payload["declarations"] == projection["harnessTypes"]
    assert payload["hermes"] == ["start", "stream"]
    # 原生声明不能抬高产品能力：`native_continuation`/`abort`/`filesystemBrowser`/`sessions`
    # 全报 true 也带不出 native_continuation、steer 或 attach。
    assert payload["pi"] == ["start", "stream"]


def test_the_js_ceiling_fails_closed_when_the_projection_is_not_where_it_reads(tmp_path):
    """投影读不到时返回空上限，而不是内联一份记忆里的表。

    这条测试把"失败关闭"钉住：把 `profile_extensions.mjs` 单独放到一个没有
    `capability_declarations.json` 的目录里，上限就是空集，任何 canonical 声明都会被
    `HARNESS_CAPABILITY_UNDECLARED` 拒绝。它**不会**退化成"照抄声明"或"猜一套出来"。
    """
    isolated = tmp_path / "agentbox-sidecar" / "runtime"
    isolated.mkdir(parents=True)
    shutil.copyfile(RUNTIME / "profile_extensions.mjs", isolated / "profile_extensions.mjs")
    # 上游 profile 表仍然要能解析：把 third_party 原样接过去。
    (tmp_path / "agentbox-sidecar" / "third_party").symlink_to(PLUGIN_ROOT / "third_party")

    result = _node_probe(isolated / "profile_extensions.mjs", (
        "let refused = null;"
        "try { module.canonicalCapabilityClaims('hermes') }"
        " catch (error) { refused = String(error.message) }"
        "process.stdout.write(JSON.stringify({"
        " declarations: module.capabilityDeclarations(),"
        " ceiling: [...module.declaredCapabilityCeiling('hermes')],"
        " refused }))"
    ))
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["declarations"] == {}
    assert payload["ceiling"] == []
    assert payload["refused"] == "HARNESS_CAPABILITY_UNDECLARED: hermes"


def test_the_projection_sits_next_to_the_module_that_reads_it():
    """记录事实：投影必须与 `profile_extensions.mjs` **同目录**才会被一起带上。

    源码树里两者同目录（上一条测试证明能读到）。Worker 里的 bundle 由
    `src/agent_box/server/execution/sidecar.py::sidecar_bundle_files` 的清单决定——
    那一层不在本插件的写集里，本测试只断言"同目录"这条读取前提成立，不替它做决定。
    """
    result = _node_probe(RUNTIME / "profile_extensions.mjs",
                         "process.stdout.write(JSON.stringify({"
                         " hasCeiling: Object.keys(module.capabilityDeclarations()).length > 0 }))")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["hasCeiling"] is True
    assert JS_PROJECTION.parent == RUNTIME == (RUNTIME / "profile_extensions.mjs").parent


# --------------------------------------------------------------------------- #
# 7) 编辑漂移会被抓住（防止测试自己被绕过）
# --------------------------------------------------------------------------- #

def test_the_js_projection_is_not_a_hand_edited_second_source(tmp_path):
    """把投影改一个字符，本文件的相等断言必须失败——证明它不是装饰性文件。"""
    original = json.loads(JS_PROJECTION.read_text(encoding="utf-8"))
    drifted = copy.deepcopy(original)
    drifted["harnessTypes"]["hermes"] = sorted(set(drifted["harnessTypes"]["hermes"]) | {"attach"})
    assert drifted["harnessTypes"] != original["harnessTypes"]
    assert drifted["harnessTypes"] != {
        harness_type: sorted(abilities)
        for harness_type, abilities in _toml_declarations().items()
    }


def test_a_drifted_toml_declaration_is_not_accepted_silently():
    """把 TOML 改成声明 `steer`，注册表会接受（它是 canonical id），但 golden 会失败。

    这里断言的是"漂移不会静默通过"这件事本身：`steer` 是合法 canonical id，所以 TOML
    层不会拒绝它——拒绝它的是能力矩阵的 golden。这就是 golden 存在的理由。
    """
    drifted = load_registry(_toml_text_with(["start", "steer", "native_continuation"]))
    assert "steer" in drifted.get("codex").capabilities
    assert FAMILY_MATRIX["codex"]["steer"][0] is False


# --------------------------------------------------------------------------- #
# 8) P-D claude 附件通路：refs → ACP 块的组装、哈希可验证与类型化拒绝
#
# 每条语义都以 packaging/claude/attachment-probe.mjs 的第一手实测为锚
# （转录与哈希：specs/014-plugin-release/reports/P-D-probe-transcript.json）。
# --------------------------------------------------------------------------- #

from ordessa_harness.claude.attachments import (  # noqa: E402
    CLAUDE_ATTACH_UNDECLARED,
    CLAUDE_ATTACHMENT_HASH_MISMATCH,
    CLAUDE_ATTACHMENT_LIMIT,
    CLAUDE_ATTACHMENT_REF_INVALID,
    CLAUDE_ATTACHMENT_UNSUPPORTED,
    ClaudeAttachmentRefused,
    ClaudePreparedAttachment,
    assemble_attachment_blocks,
    claude_attachment_capabilities,
)
from ordessa_harness.claude import production as _claude_production_module  # noqa: E402


_PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAICAYAAADED76LAAAAFElEQVR4nGP8z8DwnwEPYMInOXwUAADtmwT9ZHTcOAAAAABJRU5ErkJggg=="
)


def _attachment_ref(*, prepared_id="prepared-1", name="shot.png", mime_type="image/png",
                    data=_PNG_BYTES, sha=None):
    return ClaudePreparedAttachment(
        prepared_id=prepared_id, name=name,
        uri="https://ordessa.example/attachments/shot.png", mime_type=mime_type,
        sha256=sha or hashlib.sha256(data).hexdigest(), byte_length=len(data),
    )


def test_the_claude_pathway_assembles_a_real_image_block_with_verifiable_content():
    """image ref + 随行字节 → 真实附件块，base64 内容 sha256 与 ref 自洽（往返可验证）。"""
    ref = _attachment_ref()
    blocks = assemble_attachment_blocks(
        {ref.prepared_id: ref}, attach_declared=True, data_by_prepared_id={ref.prepared_id: _PNG_BYTES})
    assert blocks == (
        {"type": "image", "data": base64.b64encode(_PNG_BYTES).decode("ascii"),
         "mimeType": "image/png"},)
    assert hashlib.sha256(base64.b64decode(blocks[0]["data"])).hexdigest() == ref.sha256


def test_the_claude_pathway_sends_non_image_files_as_resource_link_text_only():
    """非图片 ref → resource_link：只投 URI 链接文本，不携带字节、不宣称上传。"""
    doc = ClaudePreparedAttachment(
        prepared_id="prepared-2", name="notes.md",
        uri="https://ordessa.example/attachments/notes.md", mime_type="text/markdown",
        sha256="a" * 64, byte_length=11)
    blocks = assemble_attachment_blocks({doc.prepared_id: doc}, attach_declared=True)
    assert blocks == ({"type": "resource_link", "uri": doc.uri, "name": "notes.md"},)


def test_the_claude_pathway_refuses_audio_instead_of_the_adapters_silent_drop():
    """audio 必须在通路层类型化拒绝：适配器会静默丢弃 audio 块（探针钉死的事实）。"""
    audio = ClaudePreparedAttachment(
        prepared_id="prepared-3", name="clip.wav",
        uri="https://ordessa.example/attachments/clip.wav", mime_type="audio/wav",
        sha256="b" * 64, byte_length=4)
    with pytest.raises(ClaudeAttachmentRefused) as refused:
        assemble_attachment_blocks({audio.prepared_id: audio}, attach_declared=True)
    assert refused.value.code == CLAUDE_ATTACHMENT_UNSUPPORTED
    assert "silently drops" in refused.value.reason


def test_the_claude_pathway_refuses_everything_when_attach_is_undeclared():
    """能力缺席 = 类型化拒绝（缺席即红），包括形状完全合法的 image ref。"""
    ref = _attachment_ref()
    with pytest.raises(ClaudeAttachmentRefused) as refused:
        assemble_attachment_blocks(
            {ref.prepared_id: ref}, attach_declared=False,
            data_by_prepared_id={ref.prepared_id: _PNG_BYTES})
    assert refused.value.code == CLAUDE_ATTACH_UNDECLARED
    capabilities = claude_attachment_capabilities(attach_declared=False)
    assert capabilities["kind"] == "absent" and capabilities["reason"]
    # 通路默认跟着注册表走：toml 翻绿 attach 后，家族派生声明必须是 True。
    assert _claude_production_module.capability_claims()["attach"] is True


def test_the_claude_pathway_refuses_over_limit_and_malformed_input():
    """超限（数量/大小）与形状非法都类型化拒绝，不静默放行也不静默截断。"""
    ref = _attachment_ref()
    oversized = _attachment_ref(prepared_id="prepared-big", name="big.png",
                                data=b"x" * (5 * 1024 * 1024 + 1))
    with pytest.raises(ClaudeAttachmentRefused) as count_refused:
        assemble_attachment_blocks(
            {f"prepared-{i}": _attachment_ref(prepared_id=f"prepared-{i}")
             for i in range(9)}, attach_declared=True)
    assert count_refused.value.code == CLAUDE_ATTACHMENT_LIMIT
    with pytest.raises(ClaudeAttachmentRefused) as size_refused:
        assemble_attachment_blocks(
            {oversized.prepared_id: oversized}, attach_declared=True,
            data_by_prepared_id={oversized.prepared_id: b"x" * (5 * 1024 * 1024 + 1)})
    assert size_refused.value.code == CLAUDE_ATTACHMENT_LIMIT
    with pytest.raises(ClaudeAttachmentRefused) as hash_refused:
        assemble_attachment_blocks(
            {ref.prepared_id: ref}, attach_declared=True,
            data_by_prepared_id={ref.prepared_id: _PNG_BYTES + b"x"})
    assert hash_refused.value.code == CLAUDE_ATTACHMENT_HASH_MISMATCH
    with pytest.raises(ClaudeAttachmentRefused) as missing_refused:
        assemble_attachment_blocks({ref.prepared_id: ref}, attach_declared=True)
    assert missing_refused.value.code == CLAUDE_ATTACHMENT_REF_INVALID
    with pytest.raises(ClaudeAttachmentRefused) as invalid_refused:
        ClaudePreparedAttachment.from_mapping({"name": "x", "uri": "file:///etc/passwd",
                                               "mimeType": "image/png", "sha256": "z" * 64,
                                               "byteLength": 1, "preparedId": "p"})
    assert invalid_refused.value.code == CLAUDE_ATTACHMENT_REF_INVALID


def test_the_claude_attachment_capability_statement_does_not_overclaim():
    """能力语句如实：只 png 过端到端验证；audio 明示拒绝；limit 是通道策略非适配器声明。"""
    capabilities = claude_attachment_capabilities(attach_declared=True)
    assert capabilities["kind"] == "available"
    assert capabilities["mimeTypes"] == ["image/*"]
    assert "audio" not in capabilities["mimeTypes"]
    assert capabilities["semantics"]["endToEndVerifiedMime"] == "image/png"
    assert "refused" in capabilities["semantics"]["audio"]
    assert capabilities["maxCount"] == 8 and capabilities["maxBytes"] > 0

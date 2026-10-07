# Codex 原 owner 纯只读接入与真实 Jev 验证

用户明确批准 downstream-next.md 的单家族范围扩展。实现只补原 CodexRuntimeProvider 的两个公开纯读端口，复用原 ConfigurationChangeRequest 与 _compile_change；未建 owner／执行器／registry／数据权威。原实例 describe_configuration 与原 value/reset/optional skip 语义保留。

只证明 codex.defaults.compile/0.157.1 声明编译范围。offer 为 unknown、complete=false；模型存在、installation/runtimeReady/unit/application/effect/credentials 不升级为已知。回执是输入摘要绑定的 computed_nonpersistent 计算证据，不是原生操作持久证据。未知 must／无 must 均 unverifiable；已知 must＋未知 advisory 不声称 advisory 已支持；格式及原编译拒绝 invalid，内部故障传播。

| 场景／反例 | 证据 |
| --- | --- |
| 编译正例、输入摘要／版本／义务精确绑定、纯读公开核心转发 | codex-owner-final-green.txt、codex-family.xml |
| 未知／缺 must、未知 advisory、optional 具名跳过、reset 原两字段语义、reset/value 重叠 | codex-family.xml，147项家族回归通过 |
| 形状、未知字段／版本、必需控制字符、重复声明、错误 owner/context/source bool | codex-family.xml；所有禁止方法独立计数=0，非法路径也不豁免 |
| 内部 AssertionError/RuntimeError 误报用户 invalid | codex-internal-errors-red.txt：2F/25P；收窄捕获后通过，未删除断言 |
| 原 owner source Profile 撤权、独立来源退役／换代／descriptor 漂移、缺 Node/Profile、外国 namespace／未知 scheme、owner 回调后替换 | codex-native-source-attacks.txt：12项；实际 Codex 主 owner＋真实临时 SQLite 核心，无原生效果 |
| 原 schema 长度／字段数／纯枚举不能被通用组合器识别 | codex-schema-red.txt；保留 owner 原约束，补通用子集，95项 flow 回归通过 |
| offerRef 或 evidenceRefs 与实际原 owner 不符 | codex-offer-binding-red.txt：2F/5P；修复后16项探针组合回归通过，篡改在 key/ledger 前拒绝 |
| collector 首预检 sourceRefs tuple 不符合 native safe_json mapping 编码 | codex-preflight-initial-failure.txt；改为规范包装映射，失败发生在 key/HTTP 前 |
| 原客户端夹具仍从退役 Agent Tools 传输模块导入 Message | 固定基线 codex-client-baseline-red.txt：16F/104P；当前首次16F/127P。夹具改用现有公开 ordessa_harness_transport.Message，断言不变，不复活兼容链；现家族147P |

首次家族收集缺 isolated harness-transport，见 codex-native-owner-green.txt；本树无网 editable安装既有本地 transport 后推进。离线入口已纳入这两个本地 editable依赖及整个 Codex家族回归；不安装原生二进制，不启动用户 Harness。家族 client 测试中的脚本 peer 是 L1 夹具，不是实际 Codex 协议兼容性证明。

最终 offline/：Decision全套352项、67个独立场景、固定基线／当前各57核心ID、独立Decision wheel重建／无网安装通过；Codex家族147项也通过。新12个source攻击的逐用例结果在完整Junit中，不能只看总数。旧全Server/Harness红、真实断电／远程FS、Python3.10等范围不因本批关闭。

## 真实模型 + 实际家族 owner

live/ 包含冻结计划、源快照（collector/工厂/原Codex owner）、零凭据预检、实际官方SDK答案、scope ledger、原图轨迹及持久终态。候选及硬检查仍是明确受控合成资料，不能据此声称真实单元／安装已准备；owner评估确实经原公开核心转发到实际CodexRuntimeProvider。

最多6请求／45秒，实际6次 Zen免费端点 jev-1.13-free，重试0、原生效果0。原task-gate六维pass；候选／组合／校验1/1/1；原owner编译义务passed，应用依据义务unknown，原图clarify/proposal_unverifiable、无payload。这是正确拒绝升级未知的有限场景，不能推广为全面抗注入或七动作可用。

verify_archive.py 独立从复制归档复验hash链、terminal.commit、manifest、工厂／owner源码与plan/FlowRef、question/answer摘要、native input双摘要映射、义务和调用计数；不读取凭据／发送HTTP／调用Harness，结果见live/independent-verification.json。

本批5532输入／269输出tokens，费用UNKNOWN；累计220真实请求、已报告176303输入／14227输出，历史3次usage未知。旧英文标签失败、66选项概率／协议不稳定、超时与历史丢答案全部保留。JD009现在有Codex编译纯读能力，但真实应用仍未验证；Pi/Claude仍unsupported，JD010仍PARTIAL，all_work_complete=false。

```bash
.venv-decision/bin/python packages/backend/decision/checks/offline_acceptance.py
.venv-decision/bin/python specs/031-jev-decision-module/evidence/codex-pure-read-20261005/verify_archive.py
```

真实Harness启动／配置应用未授权，未执行；不得将本次纯读批准或Jev免费调用授权扩大解释为原生操作授权。

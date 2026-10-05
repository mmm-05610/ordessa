# 真实 Jev 贯穿原业务图

同一已授权 Zen 免费端点、jev-1.13-free、官方 SDK；36 次 HTTP，重试0，原生效果0，费用 UNKNOWN。用户“授权无上限”仅延续该合成免费调用范围，每次运行仍使用冻结有限预算。三个计划均先固定预期再读取凭据。

| 批次 | 原图实际结果 | 请求 | 范围 |
| --- | --- | --- | --- |
| flow | ready；受控拒绝后沿原 Repair 边修订为 ready | 12 | 一次与两次组合/校验，修订配置0.7→0.8 |
| vague | 两次 clarify | 12 | 模糊任务，不进入组合或校验 |
| multi | 两次 revise | 12 | 两个独立交付，不进入组合或校验 |

复用原 `build_assignment_flow`、runtime/gateway/permit、官方 SDK 和持久 FileEvidenceSink。候选、组合和校验端口是明确的受控合成资料，不是原生 owner，不能证明真实家族支持或实际配置生效。这里只验证真实 Jev 的任务门与原业务图的提案/反馈路由；单候选路径不需要排名调用。

各子目录含冻结计划、实际运行源码快照、账本、typed answer、原图轨迹和持久终态。`independent-verification.json` 独立复查六个 run 的哈希链、terminal.commit、result digest、源码/计划摘要及 FlowRef。正例运行先于支持外部负例 expected 的探针改动，保留当时源码，不用最新源码冒充旧运行。

`offline/` 是当时完整249项、67逐场景与57固定基线/当前核心ID检查；最终源码复验另外记录。归档复查脚本首次误写投影状态 complete（实际 completed），第二次误取 disposition 路径，均是审计脚本错误，不涉及 HTTP 或修改原始运行；修正后六项全验证。历史协议/标签失败不因这里通过而改写。

离线预检（不读取凭据）：

```bash
.venv-decision/bin/python packages/backend/decision/evaluation/reference_flow_probe.py prepare --plan packages/backend/decision/evaluation/reference-flow-plan.json --output .decision-tmp/reference-prepare
```

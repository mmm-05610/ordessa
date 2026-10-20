# Nova feature delivery

此方法包将 OpenStack Nova 从 Blueprint 到正式 Nova release 的完整外部流程写在 [PROCESS.md](PROCESS.md)。完整流程支持状态为 **unsupported**。唯一投影在 [`projection/`](projection/) 下，以 `ordessa.nova-feature-delivery.report-smoke` 作为 report capture smoke，仅登记阶段报告。

投影图仅声明单次真实 `engineering.artifacts.create` operation，用于将一份 `phase-report` 报告登记为 Engineering artifact；本任务未执行该图。其 `completed`/`rejected` 是 artifact 命令结果；完整 Nova 流程、权限和外部状态仍由 Nova/OpenDev 执行者负责。单份报告登记不是阶段执行，也不等价于全程执行。逐阶段边界见 [COVERAGE.md](COVERAGE.md) 与 [GAPS.md](GAPS.md)。

投影资源、schema、模板和 workflow 均在 `projection/method.yaml` 中显式登记 SHA-256。来源与许可记录见 [SOURCES.md](SOURCES.md) 及 [_support/sources/index.json](_support/sources/index.json)。给定的 2025.1 virtiofs/Manila 实例在官方 2025.1 implemented spec 与 Nova release notes 中得到核实；Launchpad Blueprint 页面无法由本次 Web 工具访问，用户给出的 2025-03-06 完成日期仍标为未核实，未延伸成 CI 历史、客户部署或 adoption 结论。

`_support/design-traces/` 下三类多份 JSON/Markdown 报告示例是设计走查材料，不是 workflow、输入夹具或执行证据。统一编译和实际检查结果由协调者补录于 `_support/verification/`；本包当前不声称已运行。


协调者已完成同一核心快照的无网络检查：单次登记smoke加载/校验/编译通过，五类不支持/非法反例真实拒绝；报告schema与实际payload/input mapping通过。此投影不能直接按当前Work入口启动，完整流程仍unsupported。证据见 [_support/verification/README.md](_support/verification/README.md) 和 [设计缺口](_support/verification/design-findings.md)。

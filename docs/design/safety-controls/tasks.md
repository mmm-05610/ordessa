# Tasks：Spec Kit 可执行任务与依赖

执行者接本包后先核对最终基线，所有任务必须有先红后绿、实际命令/退出码/原始日志。FR 与验证案例在 [verification.md](verification.md) 逐一对应；文档状态不是完成证明。

| ID | 所属/依赖 | 任务与交付 |
| --- | --- | --- |
| T00 | 主控，起点 | 固定三核心包与插件实现的集成 SHA、pins、官方/源码/受控分层矩阵、当前红 ID 与所有数据路径；核对 pre-effect authorizer 能否被真正执行器消费，并申请**精确公共接缝**缺口，不能先做假 API |
| T01 | Permissions；T00 | 定义强类型规则/上限与裁决合成，拒绝未知 key、跨 scope 提升和 last-match 放宽；单测在旧实现上先红 |
| T02 | Permissions；T00 | 将旧 `ApprovalRecords` 的唯一权威迁入，保留记录 ID/事件/CAS/幂等语义，补 native receipt/失联查询；双权威并存测试先红 |
| T03 | Permissions；T01/T02 | Pi/Codex/Claude 权限 adapter：严格 `assess/compile/verify`，逐 pin 测已允许工具类型，受控真实 pre-effect gate；没有证据的格只支持显式拒绝 |
| T04 | Sandbox；T00 | 原生 sandbox schema/平台限制/coverage、读写网络约束与上级上限校验；明确不同于中性 SandboxV1 |
| T05 | Sandbox；T04 | Pi/Codex/Claude adapter 与隔离效果探针：Pi 扩展缺席红；Claude 非 Bash 工具不能冒称覆盖；Codex 管理限制无法被 Profile 放宽 |
| T06 | 各域；T03/T05 | 各注册 Profile/Settings，Permissions 注册 Chat 审批区；无 UI 时后端策略仍成立，跨 scope 迟到响应不得串写 |
| T07 | Harness/集成主控；T03/T05 | 单一 ACP owner 的请求/响应授权接线与同一提交闸门；原生配置 C2 字段 claim 互斥，禁止直接从 renderer 产生 grant；请求中卸载/断连/取消负例 |
| T08 | 集成主控；T06/T07 | 旧 Profile 权限存储及 `approvals.decide` 迁移、compat 消解，产品显式启用两个可选域；不更改 wire ID/既有数据身份 |
| T09 | 主控；T08 | 独立安装与依赖方向、旧红账本逐 ID、受控 L2 三品牌及 UI 键盘/错误场景；记录 L3 未测、真实模型禁止、许可证/NOTICE 审核 |

无阻塞时 A/B 并行，T07/T08 串行。局部品牌 `unknown` 不阻止其他品牌完成，但不能把本批“全部三品牌强制能力”记作全绿；可交付明确定义为已证支持格与显式不支持格均准确，不必伪造对所有工具/OS 的支持。若共同接缝缺失，T01/T02/T04/T05 的纯域实现可继续；相关生产验收仍 blocked，不能称已完成。

# UI 公共机制增量接收说明

设计 ID：UI-FOUNDATIONS-20261004。用户要求更新方案包并提供正在执行 Codex 的补充提示词。采用原 incremental-work-order 流程，复用唯一牵头执行者；不新建工作树、调度账或业务核心。

## 来源与范围

设计来源：`/home/maoqh/projects/ordessa/specs/026-open-environment-migration/`。
实施位置：`/home/maoqh/projects/ordessa/worktree/026-open-environment-migration/`。
合同：`contracts/ui-foundations.md`。工单：`supplemental-orders/UI01-public-workspace.md`。
本增量 UI-T01–08、UI-A01–12 独立于原任务/case 注册表；不要把原 12 单/129 任务/111 case 的历史记录改写成已覆盖本增量。

目标是公共布局、导航、菜单、设置容器和可复用控件，不是重做全部插件页面。不修改用户数据格式、登录或模型配置。只在受控产品接线两个中性消费者，领域插件逐个改造另行审查。

## 安全纳入步骤

1. 当前代码/子代理切片先到安全边界；记录实施 HEAD、脏文件、当前工单及阶段。不 reset、不 stash 用户修改、不覆盖未完成切片。
2. 将本文件、合同、补充工单按内容导入实施树，README 仅合并增量入口；不整体复制 specs，不覆盖 status/evidence/checks 或旧裁决。
3. 在本树现有 status 追加接收回执；保存 `evidence/ui-foundations/receipt.json`：designId、源文件 SHA256、receivedAt、implementationHEAD、currentOrder/stage、mergedFiles、contractDelta、 preservedEvidence、nextSafeBoundary。设计未提交时记录文件摘要，不伪造设计 SHA。
4. 现有配置单写者、可靠提交、恢复与发行缺口继续完成；UI01 默认追加在当前收尾单之后。若现有实现已触及本增量的公共模块，可在安全边界复用符合合同的改动，单独留本增量证据，不重复实施。
5. UI-T01 冻结增量接口和归属后再编码；优先沿用已有 Workbench/Lumino/F5/公共交互，不新增第二命令、弹层、状态或设置业务核心。
6. 只有公开接口已冻结且文件互不重叠时允许控件与只读验收准备并行；主代理独占契约、共享样式、Workbench、产品装配、Git 和结果账。
7. 本增量沿用现有授权边界。计划更新不新增真实模型、系统安装、真实数据迁移或服务重启授权。无需调用模型的受控 UI 验证优先使用 fixture。
8. 单测、受控集成、真实 GUI、发行证据分账。缺 GUI 环境可继续代码和受控测试，但记 PARTIAL/UI-pending；不能将源码存在、截图 fixture 或套件全绿当作实际产品全通过。

## 修订范围与不变项

仅此增量取代“公共 UI 只需基础控件即可”的理解；不取代 F5 状态/查询/编辑/任务合同、Agent 唯一配置权威、Profile 可选/字段覆盖、品牌差异归 Harness、unknown 不重发、插件 scope 生命周期或兼容清理要求。
窗口控制仍归 Desktop；布局和弹层归 Workbench；视觉基础归 ui；动态组件选择归 ui-components；插件提供业务值、动作和内容。没有本增量所需能力的插件可缺席，不创建无效功能按钮。

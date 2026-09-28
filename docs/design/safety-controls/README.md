# Safety controls：权限/审批与 Harness 原生 sandbox

日期：2026-09-28。状态：**DESIGN_REVIEW_READY；未授权实施**。按 GitHub Spec Kit 的需求→研究→契约→任务→验证结构编写，不是实现或测试报告。

## 裁定

两个相邻但不混同的业务所有者：`plugins/permissions/` 拥有工具调用授权、审批规则、用户/管理员上限及拒绝证据；`plugins/assets/sandbox/` 拥有 **Harness 原生 sandbox 配置**、版本/平台能力验证及效果核验。二者各向 Profile、Settings、Harness 的公开点贡献，彼此不 import 私有模块。权限的 allow 不能关闭隔离；有 sandbox 不能免除必需审批。两插件卸载后不抹去存储，但不能继续声称其配置仍生效。

这不是 `pacthold` 的 `SandboxV1` 执行资源：前者配置 Codex/Claude/Pi 自身的原生隔离，后者是 Ordessa 执行工作负载的中性资源端口；不得共用身份或以其中一个充当另一个的证明。

## 与 Profile v2 先前裁定

[Profile v2 契约 §1](../profile-v2/contracts.md)写“首版不要求新增独立 permission 插件，出现跨 Harness 的独立策略管理需求时再设计”。那是避免把 Profile 的单个设置项误膨胀为前置依赖，不是禁止以后独立。**本轮已达到其条件**：Pi/Codex/Claude 的授权语义不同，但要在无人值守、断连和多会话情形下统一保存策略、重验上限、路由审批并出具拒绝证据；该业务不能由一个 Harness 的 Profile glue 或 Chat UI 所有。因此新建可选 `permissions` 域。无此插件时 Profile/Chat/原生 Harness 继续既有路径；不假造一套默许权限或把缺失服务当允许。

## 阅读次序

1. [spec.md](spec.md)：用户故事、边界、可验收需求。
2. [research-and-reuse.md](research-and-reuse.md)：官方/仓内事实、复用与许可裁定。
3. [data-model.md](data-model.md)：策略、作用域、审批与原生隔离快照。
4. [contracts.md](contracts.md)：公开贡献、后端权威及拒绝语义。
5. [harness-adapters.md](harness-adapters.md)：三品牌矩阵及证据级别。
6. [ux.md](ux.md)：Settings、Profile、Chat 与审批体验。
7. [plan.md](plan.md)、[tasks.md](tasks.md)、[verification.md](verification.md)：阶段、可并行面、门禁与反例。

## 完成口径

本包只允许“配置/请求/拒绝的真实后端闭环”算绿。官网有字段、写盘成功、ACP 收到事件、UI 显示模式均不能单独证明执行时限制生效。品牌版本与当前 Ordessa ACP 链的证据分层；未证明者显示 unsupported/unknown 并拒绝受该要求约束的操作。禁止真实模型调用与读取用户私有配置，除非单独获授权。

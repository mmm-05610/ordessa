# Prompts：指令与人格插件实施包

日期：2026-09-28。状态：**DESIGN_REVIEW_READY**。用户已确认领域方向；本包新增细节待审核，不是实现授权或验收通过报告。

采用 Spec Kit 的用户故事、需求、研究、数据模型、契约、实施计划、任务与验收结构。仅设计文档，未运行 Spec Kit 生成命令。

## 定案摘要

- 一个业务插件 `plugins/assets/prompts/` 管理补充指令、人格、原生系统提示替换；不是三个插件。
- 内容与修订由 Prompts 保存，Profile 只保存引用和顺序；Profile 专用内容也留在 Prompts。
- 默认跟随内容最新修订；每次提交冻结解析结果，下次用户输入才应用，不打断输出。
- Prompts 内的品牌 adapter 注册到 Harness；后者统一执行写入/重载/恢复与确认。Prompts 不自行控制进程。
- 不接管项目 AGENTS.md/CLAUDE.md，不引入命令模板、Skill、子代理、权限管理或自动记忆。
- 首版不加 Chat 常驻选择器，不新增 Assets 总服务，不改核心业务边界。

## 方案文件

| 文件 | 用途 |
| --- | --- |
| [spec.md](spec.md) | 用户故事、范围与成功条件 |
| [data-model.md](data-model.md) | 内容修订、引用、归档、并发与快照 |
| [contracts.md](contracts.md) | 服务 API、Profile/Settings/Harness 注册点 |
| [harness-adapters.md](harness-adapters.md) | 品牌映射、合成、重置和验证边界 |
| [ux.md](ux.md) | 管理页、Profile 编辑区、异常交互 |
| [research-and-reuse.md](research-and-reuse.md) | 官方来源与逐模块复用裁定 |
| [plan.md](plan.md) | 目录、依赖、迁移和实施顺序 |
| [tasks.md](tasks.md) | 逐项可验收任务 |
| [verification.md](verification.md) | 反例、运行步骤、开工与完工清单 |

上位依赖：[Harness v2](../harness-v2/README.md)、[Profile v2](../profile-v2/README.md)、[平台 UI 方案](../platform-ui-foundations/README.md)。本包不重新定义它们的注册器、Token、应用事务或会话所有权。

## 实施依赖，不掩饰为已就绪

1. 平台最终集成 SHA、Profile v2 贡献 API、Harness v2 应用端口尚需冻结；本包设计可先审核，实现不能依赖其他工作树未提交状态。
2. 官方文档能证明原生机制，不代表当前 Ordessa pin 的 ACP 路径已支持；逐品牌版本表与受控装载/恢复证据是开工及交付条件。
3. 本批强制 Pi/Codex/Claude 的补充指令生产链；人格和系统替换逐格验证后提供，不做模拟成功。Hermes 是机制参考和后续适配目标，不自动扩成第四家完整集成任务。

本批“完成”必须同时包含真实内容服务、前端注册、Profile 引用与三主品牌补充指令的受控全链，不能只有表单或 fake Harness。其他能力明确不支持不算兼容债；但不得下架既有支持来掩盖回归。

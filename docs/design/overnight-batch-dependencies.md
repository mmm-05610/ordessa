# 下一批实施的跨包顺序与共同验收门

日期：2026-09-28。状态：设计协调记录，**不是实施授权或完成报告**。本页只规定多个 Spec Kit 包之间的前置关系；每个业务需求、接口和反例仍以各包文件为准。

## 共同起点

1. 从最终验收并合入的 `main` 固定 SHA、真实公开符号、产品启用清单、版本 pin、四套件及桌面回归的失败 ID/原因基线。设计文档里的 API 名称不能当成已经发布的接口。尤其核对 Harness C1–C5、Profile facet/提交闸门、Chat 输入贡献、ACP 单一 owner 和工具副作用前授权接缝。
2. 新工作树必须从这个固定 SHA 创建；方案文档须先进入可到达提交或受控补丁，再分派。根工作树保持 `main`。现有 `worktrees/model-provider-spec` 与 `worktrees/plugin-model-provider-impl` 是只读来源，不自动视为已集成，也不重新造同名服务。
3. 各实现只写其业务域和已批准的公开契约/产品装配接线。发现接缝缺失时，提交精确的 DTO、调用方、反例与最小变更；不得在插件内建第二宿主、ACP client、凭据仓或配置应用器。未接通的功能保留 `PARTIAL/UNKNOWN`，不能用 fake 门代替生产门。

## 依赖与可并行面

| 方案包 | 可先独立实现 | 必须等待的真实接缝 | 不可假报的完成门 |
| --- | --- | --- | --- |
| [Model-provider](model-provider/README.md) | 沿用并审入旧部分实现的记录、探测、目录和 UI；迁移 `server-compat` 所有权 | Harness C2/C4/C5、Profile 覆盖、Chat/ACP 单一提交 owner | Pi/Codex/Claude 各自受控同会话下轮切换；必要时 restart 后 resume **同一原生会话**，双会话互不污染 |
| [Skills](skills-v2/README.md)、[Prompts](prompts/README.md)、[命令模板](command-templates/README.md)、[原生子代理定义](native-subagents/README.md) | 各自的内容、不可变版本、作用域分配和独立 UI；不合并成 Assets 总服务 | Profile facet、Harness C2；命令模板另等 Chat 输入贡献，子代理调用另等真实原生/受审扩展入口 | 定义/表单不等于已装载；Pi 子代理扩展示例不等于内建；模板插入草稿不等于发送 |
| [Safety controls](safety-controls/README.md) | Permissions 规则/审批记录与 Sandbox 原生配置可按不重叠文件并行 | 真正工具副作用前的授权入口、ACP 单 owner；Sandbox 另需 C2 与隔离效果观测 | UI 允许或写盘成功都不等于强制策略/隔离生效；未覆盖工具、失联、未知状态按受限策略拒绝 |
| [MCP](mcp/README.md) | 定义、版本、作用域分配、受控探测与工具目录 | native lane 等 Harness C2 与实例隔离；managed lane 等受控工具桥；实际 `tools/call` 等 Permissions 生产授权门 | 一个连接只有一个运行/关闭 owner；三个品牌各有受控调用和拒绝证据，不能以 `tools/list` 冒充可调用 |

可并行的是**不同文件所有者的领域实现**，不是同一产品清单、ACP owner、Harness 注册表或兼容数据表的并发改写。Safety 的权限规则与原生 sandbox 可以分开写，但其共同的副作用前门在集成批次统一验收。MCP 的定义阶段不必等 Permissions；MCP 受管工具调用必须等有效授权，不能因夜间无人值守而默认放行。

## 建工作树前的发放检查

- 用户审核这些包中的产品默认值，特别是命令模板固定修订与显式插入、Pi 子代理扩展依赖、MCP managed lane 与权限门、原生 sandbox 覆盖范围。
- 为每个执行树指定唯一文件所有者、起点 SHA、先红后绿反例、原始日志/JUnit、失败 ID/原因差分、干净安装/构建门，以及可继续的独立任务与不可越过的跨包阻塞。
- 真模型、真实外部 MCP 服务、用户凭据/配置目录、push/merge 均不由方案包授权；若后来需要，分别申请明确范围。夜间代理只能报告已证的能力格，不能为了整包全绿删除断言或把 `UNKNOWN` 改写成成功。

合并顺序不是按文档完成时间：先公共接缝与唯一 owner，再各业务域，最后产品装配和跨包全链验收。每次集成重跑主线账本；局部包绿不自动允许下一批合并。

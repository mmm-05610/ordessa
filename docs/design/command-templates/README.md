# 命令模板实施方案包

日期：2026-09-28。状态：**DESIGN_REVIEW_READY**，不是已实现或已验收。本包按 Spec Kit 的需求、研究、数据、契约、实施、任务与验证组织；没有运行 Spec Kit 生成命令。

## 定案

- 业务域位于 `plugins/assets/command-templates/`。它保存可复用的**一次性参数化用户消息**、修订和启用分配；不执行代码、不提供新的系统提示层，也不成为 Skill 仓库。
- `plugins/commands` 目前是通用贡献容器加 `execute(id)` 回调分派，**不是命令执行引擎**；Chat `/`、`+` 是发现与交互入口；它们都不保存模板内容。模板插件拟以 Chat 已审设计中的 `addInputSource` 接入（main 尚未发布该 API），展开结果进入可编辑草稿，**选择和展开均不发送**。
- `Skill` 可被模型自动发现、可含附件/脚本、遵从其原生规则；模板只能由用户显式选用并将确定文本置入草稿。`Prompts` 管持久指令/人格/系统替换；模板不进入它的配置层。Harness 内建命令和可执行扩展命令仍由各自所有者执行，不得以同名模板遮蔽。
- 内容归模板插件；用户全局/项目启用规则归模板插件；Profile 仅保存模板引用和覆盖；Harness 负责可选原生投影及运行实例，品牌适配器位于模板业务域。首版跨品牌必达路径是 Ordessa Chat 预览→草稿→原有提交，不假定品牌原生支持。若原生投影与该路径语义不同，拒绝投影并保留 Chat 路径。
- 默认使用已批准、固定修订；更新不悄悄改变分配。展开时固定修订与参数，随后草稿是普通用户可编辑文本；内容修订不重写已有草稿。本版不加独立 AssetsService、不改 Server/Pacthold/Workbench 核心。

## 文件

1. [spec.md](spec.md)：用户场景、FR 与边界。
2. [research-and-reuse.md](research-and-reuse.md)：官方事实、源码复用裁定。
3. [data-model.md](data-model.md)：模板、修订、分配、展开快照。
4. [contracts.md](contracts.md)：服务、Profile、Chat/Harness 接缝。
5. [harness-adapters.md](harness-adapters.md)：品牌矩阵及原生投影门。
6. [ux.md](ux.md)：设置、Profile、斜杠/加号交互。
7. [plan.md](plan.md)、[tasks.md](tasks.md)、[verification.md](verification.md)：实施顺序和反例门。

上位设计：[Skills](../skills-v2/README.md)、[Prompts](../prompts/README.md)、[Harness v2](../harness-v2/README.md)、[Profile v2](../profile-v2/README.md)、[Chat 输入契约](../chat-zcode-reuse/input-contracts.md)。实现前须以已验收集成 SHA 核对这些**设计契约**是否真的发布；当前 main 不含完整 Chat 入口，不可把设计文档当运行事实。

## 需用户复核的产品默认值

1. 模板展开始终生成可编辑用户草稿，不自动发送或调用工具；这是本包的基础语义。
2. 模板启用引用固定修订，更新需显式批准；沿 Skills 而非 Prompts 的版本模式。
3. 首版参数为受限字符串/枚举/整数/授权项目引用；不提供脚本、网络、文件读取型变量。若要开放这些能力，另开安全与数据所有权设计。

以上是为可实施性做的明确默认裁定，未代替用户审核。

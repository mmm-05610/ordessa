# Research：Profile 的不同模型与复用裁决

研究日期 2026-09-27。优先官方文档与源码。以下区分文档事实、读到的代码和 Ordessa 的设计推论；没有运行上游产品或验证真实 Harness 切换。官网内容会变化；源码条目固定提交。

## 1. 五组参考

| 项目 | 实际解决的问题 | 对 Ordessa 的取舍 |
| --- | --- | --- |
| [Hermes Profiles](https://hermes-agent.nousresearch.com/docs/user-guide/profiles/) | 独立配置/状态 home，含配置、会话、记忆等；不等同 sandbox | 借能力配置与用途表达，不复制其“一 Profile 一整份状态目录”模型 |
| [VS Code Profiles](https://code.visualstudio.com/docs/configure/profiles) | 成组编辑器定制，可选择包含哪些配置资源、复制/空白创建，提供专门编辑器 | 借管理页与内容选择、明确配置来源；不抄窗口级 active profile，更不抄“修改当前环境就直接写回预设” |
| [Roo API Profiles](https://roocodeinc.github.io/Roo-Code/features/api-configuration-profiles/) / [Custom Modes](https://roocodeinc.github.io/Roo-Code/features/custom-modes/) | API 连接预设与工作模式分离；模式可声明工具组/编辑限制，任务与配置有关联 | 借 provider 配置与行为配置分离、来源明确；不合并凭据保险箱，也不沿用其任务持久绑定取代我们的可切换语义 |
| [OpenCode Agents](https://opencode.ai/docs/agents/) | 命名 Agent 定义包含 prompt、model、permissions，可用 JSON/Markdown 配置 | 借显式 allow/ask/deny 和工具/行为分组；它不是通用 Profile 系统，不把 Agent/Subagent 身份等同 Profile |
| [Goose Recipe reference](https://github.com/aaif-goose/goose/blob/main/documentation/docs/guides/recipes/recipe-reference.md) | 可分享的指令/扩展/参数组合，显式扩展集合有自己的语义 | 借可读配置组合与秘密引用思路；Recipe 带任务/运行语义，不作为本项目预设格式或 Skill 的替代品 |

另外 [Hermes Tools & Toolsets](https://hermes-agent.nousresearch.com/docs/user-guide/features/tools/) 展示按工具集启用的表达方式；**启用工具不自动等于免审批，也不等于文件系统隔离**。这是我们设计时要显式拆开的维度，不宣称各项目本来都采用相同模型。

结论：没有一个可直接搬入的“多 Harness + 会话逐项覆盖 + 插件化字段”全套实现。优先保留 Ordessa 已有领域数据逻辑，定点提取 UI/校验小模块；不为复用替换整个服务栈。

## 2. 已读源码与可提取位置

### Hermes

固定提交 [`8c9fe964009096e46f44292d036c1e0ac33c3026`](https://github.com/NousResearch/hermes-agent/tree/8c9fe964009096e46f44292d036c1e0ac33c3026)。

- [`apps/desktop/src/plugins/hermes-bots/profile-config.tsx`](https://github.com/NousResearch/hermes-agent/blob/8c9fe964009096e46f44292d036c1e0ac33c3026/apps/desktop/src/plugins/hermes-bots/profile-config.tsx)：已读 CheckList/CapabilityEntry、AdvancedProfileConfig 和 dirty-section 的相关源码。能力行的名称/说明/勾选布局与未改区域不写回的思路可提取。它依赖 Hermes SDK、bot/backend、模型控制；不得搬整个组件。Ordessa 改为按 item patch，不复制 dirtyMcp/dirtyModel 等硬编码分支。
- [`apps/desktop/src/app/profiles/create-profile-dialog.tsx`](https://github.com/NousResearch/hermes-agent/blob/8c9fe964009096e46f44292d036c1e0ac33c3026/apps/desktop/src/app/profiles/create-profile-dialog.tsx)：已读 imports/表单与验证相关片段；作为创建表单交互参考。其目录名校验不适合直接约束我们的中文 displayName；不复制 createProfile/updateProfileSoul 原生 API。
- Profiles index 在研究重读时收到 429，不能以该次请求为成功依据；源码复制前需完整重读实际移植文件。许可证请求也遇到限流：本批**不授权直接复制 Hermes 代码**，实施前须核对该固定提交根许可证和嵌套插件许可证/NOTICE。可先按已读逻辑设计，不虚称完成许可门。

### VS Code

固定提交 [`4336606aa949efdcddb89b3db3e216562730b2bf`](https://github.com/microsoft/vscode/tree/4336606aa949efdcddb89b3db3e216562730b2bf)。已读 [`src/vs/platform/userDataProfile/common/userDataProfile.ts`](https://github.com/microsoft/vscode/blob/4336606aa949efdcddb89b3db3e216562730b2bf/src/vs/platform/userDataProfile/common/userDataProfile.ts) 中 IUserDataProfile、UseDefaultProfileFlags、toUserDataProfile 的资源映射。只参考资源拥有者与默认来源显式化；不移植其 URI/DI/文件系统及完整配置服务。原 LICENSE 路径请求 404，不算许可证通过；本计划不复制该代码。

### Roo Code

固定提交 [`b867ec9145750d0ae1ff7f02d35406e9bf2a0b16`](https://github.com/RooCodeInc/Roo-Code/tree/b867ec9145750d0ae1ff7f02d35406e9bf2a0b16)。

- [`packages/types/src/mode.ts`](https://github.com/RooCodeInc/Roo-Code/blob/b867ec9145750d0ae1ff7f02d35406e9bf2a0b16/packages/types/src/mode.ts)：已读分组 schema、重复组验证与模式字段；候选复用为配置集合唯一性校验及测试模式，删除内置角色提示词/品牌枚举。工具 group 不是 Profile 核心字段，不原样移植。
- [`src/core/config/ProviderSettingsManager.ts`](https://github.com/RooCodeInc/Roo-Code/blob/b867ec9145750d0ae1ff7f02d35406e9bf2a0b16/src/core/config/ProviderSettingsManager.ts)：已读 profile schema、锁内 saveConfig 保持 ID 与 secret storage 边界；仅参考，不复制 VS Code ExtensionContext、全局 currentApiConfigName 或 provider API 构造器。
- 固定提交根 LICENSE 读取为 Apache-2.0；正式复制仍需核对文件 notices，标明修改。API tree 请求限流未拿到全树，不声称审过全部 UI。

OpenCode/Goose 本轮为官方文档级参考，未固定并审阅源模块，不列为可直接移植源码。本轮收到限流后没有继续批量重试。

## 3. 本仓现有代码的优先复用

只读基线 `feature/plugin-profile-impl @ b77f9f23cb`，路径 `plugins/profile/src/ordessa_profile/`。

| 模块 | 处置 |
| --- | --- |
| storage.py / repository.py / profiles.py | 保留稳定 ID、CAS、不可变修订、归档、幂等思路；迁移新增机制策略/命名空间/应用操作表，不重建数据库 |
| resolution.py / facet item 覆盖 | 保留逐 item 合并及来源投影；补 absent/reset/clear 区分、默认快照与未知提供者检查 |
| facets.py | 升级为 schema/语义版本、scope 所有权、纯校验/编译、真实能力预检；旧 session_apply 字符串不再证明实际应用 |
| sessions.py / core.read_back_verify | 保留选择/覆盖数据语义，重写与真实 Harness 生效有关的边界；仅 DB read-back 不能作为后端应用证明，不能先清覆盖再等待后端证据 |
| plugin.py | 当前 build 返回空 PluginRegistration，只证明可发现；要适配新宿主注册面并提供实际服务，不能写 apps/server 的业务分支 |
| sensitive.py | 敏感键扫描仅是兜底，不能声称防止所有秘密；使用声明式字段 schema 与 opaque credential ref，禁止任意透传未知 JSON |
| 现有测试 | 重跑并保存逐 ID 语义；旧“DB 应用成功”的断言分拆成存储事务与运行证明，不通过删失败断言制造绿 |

现有包只有 Python 代码，前端需新增；70 测试通过出自旧 evidence 报告，本轮未重跑。旧 profile_sessions 用 session_id 单字段，跨连接/服务/native session 重名需改为真实稳定领域引用，不从显示名拼 key。

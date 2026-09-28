# Domain and contribution contracts

## Skills service

一个 `skills.service` 后端端口和 `skills.*` wire 方法族，借 Server 公共 method/contribution API 注册；保持现有外部持久 ID/历史 wire 兼容，具体映射列入迁移账。请求 principal/serverScope 由鉴权注入，不接受自报 owner 或任意本地文件路径。

| 方法族 | 语义 |
| --- | --- |
| catalogue/list/get/revisions/preview/diff | 内容与版本；列表仅元数据，预览文本/附件有大小界限 |
| import.begin/chunk/preview/commit/cancel | 可远程 Server 的分块导入，摘要与原文件漂移校验；提交是唯一发布点 |
| sources/checkUpdate/approveRevision | 固定源引用，更新先看变更；审批新增本地 revision 不改绑定 |
| assignments/list/upsert/remove | 全局或项目范围，expectedVersion+operationKey；Profile 存储走其自身贡献面 |
| resolve/previewEffective | 输入已授权 target(project/harness/profile)，输出来源、版本、冲突、能力矩阵；无写入 |
| discoverNative | 受限只读目标实例结果；返回来源类别/冲突，不导入正文 |
| invokeDescriptor | 仅已验证的本会话显式调用路由；无则标 browse-only |

`resolve` 校验同域权限、内容归属、Profile 修订、目标安装与 Harness 版本；引用缺失、名字冲突、版本未批准等为类型化拒绝。不可用不以静默过滤达成“成功”。查询与每次提交的 plan 共享同一解析算法。

## Profile / Workspace / Settings

- Profile facet `assets.skills`，每 Skill 保存 `inherit | enable(revision) | disable`，Profile 专用内容只保存引用。安装实体仍归 Skills。会话覆盖按 Profile 已有 item 机制执行，不新建会话覆盖库。
- Workspace 只提供已授权 projectId 与根/状态；Skills 自有项目分配服务及 Project settings/UI 贡献。Workspace 不出现 Skills 字段或分支。
- Workbench Settings 登记 Skills 管理页：内容库、来源、用户全局分配以及带项目选择器的项目分配区。Profile editor 登记 Skill 选择区。首版不要求新增 Workbench 项目设置注册点；未来有该公开接缝时可把同一业务视图贡献到项目上下文。
- 可选注册不能反转依赖：公共内容 CRUD 不强依赖 Profile、Chat 或 Harness 已启用；实际应用必需相应 adapter。

## Harness 配置贡献

点 `harness.configuration-adapters` v1；Skills 在本域提供按品牌模块。payload 包含 `assetId/revision/treeDigest` 及已经验证的原生元数据，并绑定 runtimeGeneration/projectId/profileRevision/assignmentRevision；由 Harness 从自身私有内容装载目标操作，不信适配器给任意绝对路径。

`assess` 以版本/入口/作用域判断能否独立隔离、发现、reload/reset；`compile` 产出 Harness `MountContent`/`RemoveOwnedContent`/声明动作；`verify` 解释真实原生发现或加载结果。三个动作均不能自行写 HOME、spawn、发送 prompt 或执行 Skill 脚本。借 Harness 一次提交的 plan/apply/reconcile，与模型/Prompts 一起冲突预检。

可用性最少区分：stored、selected、projected、loaded、used、unknown。前四有各自证据；没有独立调用事件不得标 used。配置投影的 digest 匹配只能证明 projected，不能当“agent 已学会这个 Skill”。

## Chat 可消费的贡献

Skills 通过 Chat 已有 `/` 和 `+` 命令/附件菜单贡献点提供 `SkillChoice`：会话目标、assetId、revision、名称、说明、来源、状态、explicitInvocationSupported、invokeDescriptor?。菜单从当前已确认有效 snapshot 查询；旧 generation 响应不更新新会话。

显式选用经 Chat/ACP 唯一会话 owner 发原生调用，并计入当次输入；不能在菜单选择时暗发消息，也不自动把 `SKILL.md` 正文粘进聊天框。品牌无显式调用入口时只浏览/预览，自动触发能力仍由原生 Harness 决定。斜杠名称冲突按 Chat registry 拒绝或命名空间区分，不覆盖产品系统命令。

首次实现只以公共 Chat 注册点接入；若当前 Chat contract 不提供命令贡献，需向其所有者加最小领域接缝并验证，再交付本项，不能直接 import Chat 内部组件绕过边界。

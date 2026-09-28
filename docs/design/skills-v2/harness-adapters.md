# Harness 装载与撤销

## 品牌适配原则

品牌适配器在 Skills 插件内部，注册到 Harness v2 `harness.configuration-adapters`。每个适配器只解释原生 Skill 格式、目录/会话入口、发现优先级、reload、显式调用、撤销与观察结果；运行实例和装载目录句柄属于 Harness。一个 Skill 包的 `name`、说明、附件/脚本必须经目标品牌所用的实际解析器检查；未认识的前置信息只作为数据保留，不能宣称其限制生效。

本批 Pi、Codex、Claude Code 是受控验收目标。三家“支持 Agent Skills 格式”不足以证明当前 Ordessa 固定版本、ACP 入口和同会话更新已经支持；每个格子需固定 native/adapter 版本、受控入口、优先级和卸载/恢复证据。Hermes/OpenCode 等可在同一注册点以后接入，无空模块冒充支持。

## 当前官方加载规则带来的限制

- [Pi 官方 Skills 文档](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/skills.md)：开头只载入名称/说明/路径，使用时才读正文；支持用户/项目目录并可 `/reload`；同名发现冲突可能只保留先发现的一份。装入文件与最终列表必须分别观测。
- [Claude Code 官方 Skills 文档](https://code.claude.com/docs/en/skills)：个人、项目、嵌套项目、插件等位置有自己的优先级，插件 Skill 可带命名空间；自动调用、用户调用以及某些字段的语义各不同。目标品牌适配不能把 Ordessa 的项目例外等同于在 `.claude/skills` 写一份文件。
- [Codex 官方 Skills 文档](https://learn.chatgpt.com/docs/build-skills)：默认发现仓库/用户等目录，渐进装载元数据和正文。当前生产版本的根、额外目录与显式调用能力仍须固定版本受控验证。
- [Agent Skills 规范](https://agentskills.io/specification)供可移植 `SKILL.md` 基础字段校验。品牌扩展字段需按本品牌固定版本单独验证。

以上为文档事实，当前项目可用性以受控实测为准。当前旧 `harness_delivery` 的复制只证明投放；其 `verify_load` 在目标目录摘要一致时记 loaded，仍缺原生加载器独立证据。迁移中必须纠正，不能继续沿用误导名称。

## 映射步骤

1. Skills 解析有效集合，确认本地批准 revision 的 treeDigest，目标版本兼容性、名字冲突、现有原生发现项及分配权限。
2. 各品牌 adapter 对这个集合一次性生成完整目标声明：受管内容引用、原生命名及加载控制，不按 Skill 逐份修改用户或项目目录。
3. Harness 将已校验、只读的版本投放到私有 runtime generation，拥有目标目录/动作和清理责任。适配器不接收可任意写入的路径。
4. 原生进程/受控 session 采用该 generation，适配器通过原生目录枚举、加载事件、API 或受控 fake 对端核验精确 name+digest/revision。若原生入口无法提供独立证据，状态保持 projected/unknown。
5. 增删/升级在下一次用户提交时重合成完整集合；支持安全 reload 用 reload，不支持则由 Harness 重启并恢复原会话。恢复失败不另起空会话代替。

不能确认实例配置与项目自动扫描隔离时，不许对两个不同 Profile 共享一个会导致相互污染的原生进程。独立配置根不自动屏蔽当前 cwd/父目录的原生发现；适配器必须测到这些路径对集合的实际影响。若原生项目 Skill 仍自动可见，对它的“禁用”只能显示无法管理并阻止虚假全量确认。

## 原生包安全与使用事实

导入/装载不执行 scripts；脚本若被模型调用，仍受既有工具权限/审批和运行资源约束，不能凭 Skill 的 `allowed-tools` 自动提高权限。原生包可能有动态命令或跨文件引用：只允许在受控版本树内解析；版本树之外的文件、宿主 HOME 路径和网络依赖未授权时拒绝。

`loaded` 要求原生装载事实或经过固定适配器的确定性载入结果；`used` 要求本会话特定版本的独立调用事件。模型口头声称“我用了”不算证据。没有 used 观测端口就标 unknown，不在 UI 伪装精确统计。

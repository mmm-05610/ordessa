# Q2 接缝请求（api-requests）

按 `specs/011-plugin-rollout/contracts/checkpoints.md`「依赖不构成整线停机」要求：先形成**实际符号缺口清单**，
每条含调用者、目标操作、DTO、失败反例与请求 owner。缺失性判定基于本树实测，不基于设计文档声称。

## 本树实测的可用性（判定依据）

| 接缝 | 本树状态 | 证据 |
| --- | --- | --- |
| Server 方法注册 | **可用**：`server_plugin_api.contract.ServerMethodDescriptor / ServerPluginRegistration / ServerPluginContext(plugin_id, data_root, ports)` | `packages/server-plugin-api/src/server_plugin_api/contract.py:164-215`（已 `import` 通过） |
| 插件私有数据根 | **可用**：`ServerPluginContext.data_root` | 同上 `:180` |
| Workbench Settings 贡献 | **可用**：`WorkbenchSettingsSection`、`Workbench.addSettingsSection`、`openSettings`、`WorkbenchToken` | `packages/desktop-platform/contracts/workbench/src/workbench.ts:25,41,45,59`；宿主实现 `plugins/workbench/src/model.ts:124` |
| Workspace 项目解析服务 | **存在**（本域 `project-ref` 授权解析的候选真实依赖） | `plugins/workspace/src/ordessa_workspace/{plugin,records,http}.py` |
| Profile v2 facet / 贡献 API | **不可用**：`plugins/profile` 目录不存在，检查点 `codex/011-profile-api-ready` 未创建 | `test -e plugins/profile` → ABSENT；`git for-each-ref 'refs/heads/codex/011-*ready*'` → 空 |
| Chat scoped `addInputSource` | **不可用**：`plugins/chat` 不存在，检查点 `codex/011-chat-api-ready` 未创建 | `test -e plugins/chat` → ABSENT；refs 空 |
| Harness v2 配置贡献 / 应用端口 | **不可用**：`codex/011-harness-api-ready` 未创建；本树 `plugins/harness` 有 runtime/adapters，但无发布的 `harness.configuration-adapters` v1 公开端口 | refs 空；符号需 C0 发布后逐格核对 |
| 平台 UI 原语（Panel/Textarea/Toolbar/…） | **不可用**：`packages/desktop-platform/ui` 不存在（设计复用单指向 platform-frontend `82b7ef1fc3` 的出口，尚未进入本基线） | `test -e packages/desktop-platform/ui` → ABSENT |
| foundation 检查点 | **不可用**：`codex/011-foundation-ready` 未创建 | refs 空 |

`docs/design/*/research-and-reuse.md` 的复用单把上述三项（UI 原语、Profile 贡献、Chat 输入源）列为
「观察 SHA 而非实施批准 SHA」，与本表一致：**上游可见 ≠ 本仓已导出**，因此本线不 import 相邻工作树未提交产物。

## AR-Q2-01 → owner: Z1（profile-api）

- 调用者：`plugins/assets/prompts`（Profile facet `assets.prompts`，instructions 有序列表 + persona + systemReplacement 三 item）；
  `plugins/assets/command-templates`（facet `assets.command-templates`，`templateId -> inherit|enable(revision)|disable` 三态）。
- 需要：`FacetDescriptor` schema 校验端口、引用校验（scope/版本/大小/用途）回调、专用内容授权端口、
  会话 item 覆盖（列表整项覆盖，不逐元素 merge）、scope dispose 撤销贡献。
- DTO：见 `docs/design/prompts/contracts.md` §2 与 `docs/design/command-templates/contracts.md`「Profile contribution」。
- 失败反例（本线已准备，接线后即跑）：A Profile 专用内容被 B 解析；facet 缺席时 apply 必须拒绝而不是下发未知字段；
  退出 Profile 不停内容库；provider 卸载隐藏 UI 但不删数据。
- 现状：本线已把三 item 的领域校验放在自家纯域模块内可独立测试，缺公开端口时才拒绝创建 profile-scope 内容。

## AR-Q2-02 → owner: Z2（chat-api）

- 调用者：`command-templates` 前端 Chat glue（`/` 与 `+` 同源目录、参数表单→服务预览→插入草稿）。
- 需要：scoped `addInputSource`（namespaced id、group `templates`、availability、AbortSignal 查询）；
  **插入草稿的公开动作**且能表达「字面文本提交」——若正文恰以 `/` 起头，send 时不得再次被本地/原生命令解析。
- 反例：选择即发送；旧 generation/目标切换后晚到展开落入新草稿；同名遮蔽内建/Skill/extension 命令。
- 现状：本树无 `plugins/chat`，检查点未发布 → CT T10/T11 不得实现为平行入口，登记为阻塞项。
  本线已把 receipt/validateInsert 的服务端语义（零发送、TTL、目标指纹）实现在域内并给出反例。

## AR-Q2-03 → owner: C0（harness-api）

- 调用者：两域的品牌 adapter（`harness.configuration-adapters` v1，facet `assets.prompts` / `assets.command-templates`）。
- 需要：受控目标句柄与 typed intents（`MountContent` / `RemoveOwnedContent`）、reload/restart-resume 与唯一提交闸门、
  verify 阶段的受控观察事实（加载器观察或受控 fake 对端），以及固定 pin 的版本能力查询。
- 反例：把 system-replacement 悄悄降级为 append 或普通 user message；reset 用空字符串假装恢复默认；
  resume 变成 `session/new`；Claude 与 Skills 双投影同一文件。
- 现状：pin 已知（Claude `@agentclientprotocol/claude-agent-acp` 0.81.2、Codex `@agentclientprotocol/codex-acp` 1.1.14 + sdk 1.3.0、
  Pi `@automatalabs/pi-acp` 0.5.0 + sdk 1.3.0）；但 adapter 端口未发布 → 三品牌受控 L3 全链（prompts T12 / CT T11/T14）
  登记为阻塞，待 harness-api 发布后按固定 SHA 接线复跑。

## AR-Q2-04 → owner: C0（foundation / 平台 UI 原语）

- 调用者：两域 Settings 管理页与 Profile 编辑器（`prompts.library-editor.v1`、`prompts.profile-selector.v1`）。
- 需要：已发布的 `Panel/Toolbar/ScrollArea/Field/Input/Textarea/Select/Button/Notice` 公共出口与安全 Markdown renderer；
  ui-components 装载 Outlet 的公开 API。
- 反例：孤立组件绿但真实加载失败；编辑器抢全局快捷键；焦点/Escape 破坏平台 overlay。
- 现状：Workbench Settings 契约可用（见上表），UI 原语包缺失。本线策略：先用**现有真实契约**
  （`addSettingsSection` + React）实现可装载的贡献层与键盘/IME/窄窗反例，
  一旦 foundation 发布 UI 原语即替换为公共件；不自造第二注册器、不复制 Chat 私有 renderer。

## AR-Q2-05 → owner: C0（产品装配）

产品启用与构建锁由 C0 生成（`products/**` 独占）。本线交付两插件 descriptor、装配前置条件与复跑命令；
见 `integration-request.md` IR-Q2-03。
